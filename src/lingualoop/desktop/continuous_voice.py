"""QML continuous-call state. All model/RTC operations use the shared worker."""

import asyncio
from collections import deque
from collections.abc import Callable
from pathlib import Path
import sys
from threading import Event
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import (
    QObject,
    Property,
    Signal,
    Slot,
    Qt,
    QCoreApplication,
    QMicrophonePermission,
    QUrl,
)
from PySide6.QtGui import QDesktopServices

from lingualoop.application.continuous_voice import ContinuousConversation
from lingualoop.realtime.audio_process import AudioSessionProcess
from lingualoop.realtime.continuous_assets import (
    VAD_PACKAGE,
    prepare_assets,
    prepared_assets,
    server_package,
    vad_path,
)
from lingualoop.local_speech.installation import managed_status, runtime_plan


class ContinuousVoiceController(QObject):
    changed = Signal()
    componentsChanged = Signal()
    _received = Signal(str, str, int, object)

    def __init__(self, voice):
        super().__init__(voice)
        self.voice, self.vm, self.worker = voice, voice.vm, voice.worker
        database = getattr(
            self.vm._workbench._event_store, "path", Path.cwd() / "build" / "voice.sqlite3"
        )
        self._root = Path(database).parent / "voice-runtime"
        self.process_factory = AudioSessionProcess
        self.bridge_factory = None
        self.bridge = self.process = self.runner = None
        self._connection, self._input, self._output = "off", "idle", "idle"
        self._reply = "idle"
        self._muted, self._closed, self._rebuild = True, False, False
        self._id, self._generation, self._audio_generation = "", 0, ""
        self._mic_generation = 0
        self._error = self._notice = ""
        self._turn = ""
        self._attribution = ""
        self._sources = {}
        self._retained = None
        self._sent_revision = None
        self._jobs = set()
        self._reconnects = 0
        self._cancel_prepare = Event()
        self._capture_pending = 0
        self._connection_job = ""
        self._permission_pending = self._permission_error = False
        self._connection_stage = ""
        self.timings = {}
        self.faults = deque(maxlen=32)
        self._received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.worker.jobCompleted.connect(self._job_done, Qt.ConnectionType.QueuedConnection)

    @property
    def root(self) -> Path:
        return self._root

    @root.setter
    def root(self, value: Path) -> None:
        self._root = Path(value)
        self.componentsChanged.emit()

    def notify(self):
        if not self._closed:
            self.changed.emit()
            self.voice._notify()

    @Property(bool, notify=changed)
    def active(self):
        return self._connection not in {"off", "failed"}

    @Property(str, notify=changed)
    def connectionState(self):
        return self._connection

    @Property(str, notify=changed)
    def inputState(self):
        return self._input

    @Property(str, notify=changed)
    def outputState(self):
        return self._output

    @Property(str, notify=changed)
    def replyState(self):
        return self._reply

    @Property(bool, notify=changed)
    def muted(self):
        return self._muted

    @Property(str, notify=changed)
    def errorText(self):
        return self._error

    @Property(bool, notify=changed)
    def canOpenMicrophoneSettings(self) -> bool:
        return self._permission_error and sys.platform == "win32"

    @Slot()
    def openMicrophoneSettings(self) -> None:
        if self.canOpenMicrophoneSettings:
            QDesktopServices.openUrl(QUrl("ms-settings:privacy-microphone"))

    @Property(str, notify=changed)
    def noticeText(self):
        return self._notice or (
            QCoreApplication.translate("Desktop", "未启用自动朗读；识别后的发言仍会发送。")
            if self._connection == "active" and not self.voice._speak_enabled()
            else ""
        )

    @Property(str, notify=changed)
    def attributionText(self):
        return self._attribution

    @Property(bool, notify=changed)
    def canSendText(self):
        return (
            self._connection == "active"
            and self._muted
            and self._input == "idle"
            and not self.vm._busy
        )

    @Property(bool, notify=changed)
    def canRetryInput(self):
        return self._retained is not None and self._connection == "active" and self._muted

    @Property(bool, notify=componentsChanged)
    def environmentReady(self):
        try:
            return managed_status(self.root, "rtc-cpu").get("prepared", False)
        except (ImportError, ValueError):
            return False

    @Property(bool, notify=componentsChanged)
    def assetsReady(self):
        return prepared_assets(self.root)

    @Property(str, notify=componentsChanged)
    def setupSizeText(self):
        plan = runtime_plan(self.root, "rtc-cpu")
        assets = [*VAD_PACKAGE.files, *server_package().files]
        pending = sum(a.size for a in assets if not (self.root / "downloads" / a.sha256).is_file())
        return (
            QCoreApplication.translate(
                "Desktop", "组件需下载约 %1 MiB · 准备空间约 %2 MiB；准备期间不开麦。"
            )
            .replace("%1", f"{(plan.download_bytes + pending) / 1024**2:.1f}")
            .replace("%2", f"{(plan.disk_bytes + sum(a.size * 3 for a in assets)) / 1024**2:.1f}")
        )

    @Property(str, notify=changed)
    def statusText(self):
        if self._permission_pending:
            return QCoreApplication.translate("Desktop", "正在请求麦克风权限…")
        if self._connection == "preparing":
            return QCoreApplication.translate("Desktop", "正在准备连续语音，麦克风尚未开启…")
        if self._connection == "connecting":
            if self._connection_stage == "stt":
                return QCoreApplication.translate("Desktop", "正在加载识别模型，麦克风尚未开启…")
            if self._connection_stage == "tts":
                return QCoreApplication.translate("Desktop", "正在加载朗读模型，麦克风尚未开启…")
            return QCoreApplication.translate("Desktop", "正在连接语音，麦克风尚未开启…")
        if self._connection == "reconnecting":
            return QCoreApplication.translate("Desktop", "语音连接中断，正在重新连接…")
        if self._connection == "stopping":
            return QCoreApplication.translate("Desktop", "正在停止语音…")
        if self._connection != "active":
            return ""
        if self._muted:
            return QCoreApplication.translate("Desktop", "麦克风已静音，可发送文字")
        if self._input == "recognizing":
            return QCoreApplication.translate("Desktop", "正在识别 · 可以继续说")
        if self._input == "speaking":
            return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")
        if self._output == "playing":
            return QCoreApplication.translate("Desktop", "正在朗读 · 可以插话")
        if self._reply == "generating":
            return QCoreApplication.translate("Desktop", "正在回复 · 可以继续说")
        return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")

    def post(self, operation):
        job = "call-" + uuid4().hex
        self._jobs.add(job)
        self.worker.submit_job(job, operation)
        return job

    @Slot(str, object, str)
    def _job_done(self, job, result, error):
        if job in self._jobs:
            self._jobs.discard(job)
            self.worker.forget_job(job)

    def _emit(self, identity, kind, value=None, generation=0):
        self._received.emit(identity, kind, generation, value)

    @Slot()
    def prepare(self):
        if self.active or self.voice._job:
            return
        self._id = uuid4().hex
        identity = self._id
        self._cancel_prepare.clear()
        self._connection, self._error = "preparing", ""
        self.notify()

        async def run():
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                from lingualoop.local_speech.installation import prepare_managed_runtime

                self._emit(identity, "preparing_server")
                await asyncio.to_thread(
                    prepare_managed_runtime,
                    self.root,
                    "rtc-cpu",
                    cancel=self._cancel_prepare,
                    progress=lambda done, total: self._emit(identity, "progress", (done, total)),
                )
                await asyncio.to_thread(
                    prepare_assets,
                    self.root,
                    cancel=self._cancel_prepare,
                    progress=lambda done, total: self._emit(identity, "progress", (done, total)),
                )
                if self._cancel_prepare.is_set():
                    return
                from lingualoop.realtime.local_server import ensure_server

                self._emit(identity, "preparing_server")
                await asyncio.to_thread(
                    ensure_server,
                    self.root / "sfu",
                    download=True,
                    cancel=self._cancel_prepare,
                    progress=lambda done, total: self._emit(identity, "progress", (done, total)),
                )
                self._emit(identity, "prepared")
            except Exception:
                self._emit(identity, "failed", "prepare_failed")

        self.post(run)

    def _new_bridge(self):
        if self.bridge_factory:
            bridge = self.bridge_factory()
        else:
            from .pcm_audio import PcmAudioBridge

            bridge = PcmAudioBridge(self.vm._audio, self)
        bridge.capture.connect(self._capture)
        bridge.rendered.connect(self._rendered)
        bridge.credit.connect(self._credit)
        bridge.drained.connect(self._drained)
        bridge.fault.connect(self._device_fault)
        return bridge

    @Slot()
    def start(self):
        if self.active or self.voice._job or not self.vm.sessionActive:
            return
        self._id = uuid4().hex
        self._with_microphone_permission(self._start_permitted, starting=True)

    def _start_permitted(self):
        if not self.environmentReady or not self.assetsReady:
            self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "连续语音组件尚未准备，请前往设置 → 音频设备。"
            )
            self.notify()
            return
        self._reconnects = 0
        self._connect()

    def _with_microphone_permission(
        self, continuation: Callable[[], None], *, starting: bool = False
    ) -> None:
        if self._permission_pending:
            return
        app = QCoreApplication.instance()
        permission = QMicrophonePermission()

        def complete(status):
            self._permission_pending = False
            self._permission_error = status != Qt.PermissionStatus.Granted
            if self._permission_error:
                if starting:
                    self._connection = "failed"
                self._error = QCoreApplication.translate(
                    "Desktop", "麦克风权限未开启，请允许此应用使用麦克风，再重新开始语音。"
                )
                self.notify()
            else:
                continuation()

        status = app.checkPermission(permission)
        if status != Qt.PermissionStatus.Undetermined:
            complete(status)
            return
        identity = self._id
        self._permission_pending = True
        if starting:
            self._connection = "permission"
        self.notify()

        def granted(result):
            # A dismissed call or a late OS prompt must never open the microphone.
            if not self._closed and identity == self._id:
                complete(result.status())

        app.requestPermission(permission, self, granted)

    def _connect(self, *, resume=True, reconnect=False):
        self._rebuild = False
        self._id, self._generation, self._audio_generation = uuid4().hex, 0, ""
        identity = self._id
        self._connection = "reconnecting" if reconnect else "connecting"
        self._muted, self._input, self._output = True, "idle", "idle"
        self._retained = None
        self._error = self._notice = ""
        self._connection_stage = "stt"
        self._sources.clear()
        try:
            if self.bridge:
                self.bridge.close()
                self.bridge.deleteLater()
            self.bridge = self._new_bridge()
            config = self.bridge.formats()
            config.update(
                cache=str(self.root / "sfu"),
                vad=str(vad_path(self.root)),
                pause_ms=int(self.vm.preferences.voicePauseMs),
            )
        except Exception:
            self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "音频设备不可用，请选择麦克风和播放设备后重试。"
            )
            self.notify()
            return
        self.process = self.process_factory(
            identity, lambda header, data: self._emit(identity, "transport", (header, data))
        )
        process = self.process
        if type(process) is AudioSessionProcess:
            status = managed_status(self.root, "rtc-cpu")
            if status.get("prepared"):
                process.python = status["python"]
        from .voice import _SpeechRoute

        stt, tts = _SpeechRoute(self.vm, "stt"), _SpeechRoute(self.vm, "tts")
        language = self.vm._speech_language()
        speak = self.voice._speak_enabled()
        self.runner = ContinuousConversation(
            self.vm._workbench,
            process,
            lambda kind, generation, value: self._emit(identity, kind, value, generation),
        )
        self.notify()

        async def connect():
            try:
                await asyncio.to_thread(vad_path, self.root, verify=True)
                for route, required in ((stt, True), (tts, False)):
                    if route is tts and not speak:
                        continue
                    try:
                        self._emit(identity, "connection_stage", "stt" if required else "tts")
                        bound = await route.bind(language)
                        warm = getattr(bound, "prepare", None)
                        if warm:
                            await warm()
                    except Exception:
                        if required:
                            raise
                if identity != self._id or self._closed:
                    return
                self._emit(identity, "connection_stage", "rtc")
                result = await process.start(config)
                self._emit(identity, "connected", (resume, result))
            except BaseException:
                await process.close()
                self._emit(identity, "failed", "connection_failed")

        self._connection_job = self.post(connect)

    @Slot()
    def muteMicrophone(self):
        if self._connection != "active":
            return
        self._muted, self._input = True, "idle"
        self._retained = None
        self.bridge.mute()
        self._notice = QCoreApplication.translate("Desktop", "麦克风已静音；尚未提交的语音已丢弃。")
        runner, process = self.runner, self.process
        runner.input_allowed = False

        async def mute():
            await runner.cancel_input()
            await process.request("mute")

        self.post(mute)
        self.notify()

    @Slot()
    def resumeMicrophone(self):
        if self._connection != "active" or not self._muted:
            return
        self._with_microphone_permission(self._resume_permitted)

    def _resume_permitted(self):
        if self._rebuild:
            self._restart(resume=True)
            return
        self._notice = ""
        self._retained = None
        identity, process = self._id, self.process

        async def resume():
            try:
                result = await process.request("resume")
                self._emit(identity, "resume_device", result)
            except Exception:
                self._emit(identity, "failed", "connection_failed")

        self.post(resume)

    @Slot()
    def stop(self):
        if not self.active or self._connection == "stopping":
            return
        if self.runner:
            self.runner.input_allowed = False
        self._cancel_prepare.set()
        self._permission_pending = False
        self.worker.cancel_job(self._connection_job)
        self._id = uuid4().hex
        identity = self._id
        self._connection, self._muted = "stopping", True
        self._input = self._output = "idle"
        self._reply = "idle"
        self._audio_generation = ""
        if self.bridge:
            self.bridge.close()
        self._retained = None
        self._sources.clear()
        self.vm._streaming_text = ""
        self.notify()

        async def stop():
            await self.aclose()
            self._emit(identity, "stopped")

        self.post(stop)

    async def aclose(self):
        runner, process = self.runner, self.process
        self.runner = self.process = None
        try:
            if runner:
                await runner.close()
        finally:
            if process:
                await process.close()

    @Slot()
    def stopReply(self):
        if not self.runner:
            return
        self.bridge.stop_output()
        self._audio_generation = ""
        self._output = "idle"
        runner = self.runner
        self.post(lambda: runner.interrupt("user_stopped"))
        self.notify()

    def stop_speech(self):
        if self.runner:
            self.bridge.stop_output()
            self._audio_generation = ""
            self._output = "idle"
            runner = self.runner
            self.post(runner.stop_speech)
            self.notify()

    def send_text(self, text, *, retry_turn=None, speech_only=False):
        if not self.canSendText or not (text.strip() or retry_turn):
            return
        from .voice import _SpeechRoute

        stt, tts = _SpeechRoute(self.vm, "stt"), _SpeechRoute(self.vm, "tts")
        speak = self.voice._speak_enabled() or speech_only
        source = self.vm.source_context_provider()
        self._sent_revision = (
            (self.vm._draft_revision, self.vm.draft)
            if not retry_turn and text == self.vm.draft
            else None
        )
        runner = self.runner
        self.post(
            lambda: runner.send_text(
                text, source, stt, tts, speak, retry_turn=retry_turn, speech_only=speech_only
            )
        )

    @Slot()
    def retryInput(self):
        if self.canRetryInput:
            header, data, source = self._retained
            self._submit_input(header, data, source, retry=True)

    def _submit_input(self, header, data, source, *, retry=False):
        from .voice import _SpeechRoute

        stt, tts = _SpeechRoute(self.vm, "stt"), _SpeechRoute(self.vm, "tts")
        self._retained = (header, data, source)
        self._input, self._error = "recognizing", ""
        runner, speak = self.runner, self.voice._speak_enabled()
        self.post(lambda: runner.receive(header, data, source, stt, tts, speak, manual_retry=retry))
        self.notify()

    @Slot(object, bytes)
    def _capture(self, header, data):
        if self._muted or self._connection != "active":
            return
        # Bound queued Qt->async work as well as the child's PCM queue.
        if self._capture_pending + len(data) > self.bridge.input_format.bytesForDuration(200000):
            self._device_fault("input_gap")
            return
        self._capture_pending += len(data)
        process = self.process

        async def send():
            try:
                await process.send("capture", data, **header)
            finally:
                self._capture_pending -= len(data)

        self.post(send)

    @Slot(object, bytes)
    def _rendered(self, header, data):
        if self.process and header["generation"] == self._audio_generation:
            process = self.process
            self.post(lambda: process.send("rendered", data, **header))
            if self.runner:
                self.timings.setdefault(
                    "device_first_submit_ms", (perf_counter() - self.runner.started_at) * 1000
                )

    @Slot()
    def _credit(self):
        if self.process:
            process = self.process
            self.post(lambda: process.send("credit"))

    @Slot(str)
    def _drained(self, generation):
        if generation != self._audio_generation or not self.runner:
            return
        self._audio_generation = ""
        self.bridge.stop_output()
        self._output = "idle"
        runner = self.runner
        turn = self._turn
        if turn:
            self.post(lambda: self._delivery(runner, turn))
        self.notify()

    async def _delivery(self, runner, turn):
        runner.workbench.record_speech_delivery(turn, "completed", runner.segment_count - 1)
        runner.audio_started = False

    @Slot(str)
    def _device_fault(self, code):
        if self._connection != "active":
            return
        self._record_fault(code)
        if code in {"audio_output_failed", "output_overflow"}:
            self.stop_speech()
            self._error = (
                QCoreApplication.translate(
                    "Desktop", "待播音频超出容量，已停止朗读；静音麦克风后可重试，文字回复继续。"
                )
                if code == "output_overflow"
                else QCoreApplication.translate(
                    "Desktop", "播放设备未能输出声音；静音麦克风后可重试朗读，文字回复继续。"
                )
            )
            if self._turn:
                self.voice._speech_errors[self._turn] = self._error
            self.notify()
            return
        self._rebuild = code in {"audio_devices_changed", "microphone_failed"}
        self.muteMicrophone()
        self.stopReply()
        if code == "input_gap":
            self._error = QCoreApplication.translate(
                "Desktop", "麦克风音频传输中断，已暂停监听并丢弃未发送的语音；请恢复监听后重说。"
            )
        elif code == "input_limit":
            self._error = QCoreApplication.translate(
                "Desktop", "当前语音达到长度上限，已暂停监听；请缩短发言后恢复监听。"
            )
        elif code == "audio_devices_changed":
            self._error = QCoreApplication.translate(
                "Desktop", "所选音频设备已移除或改变，请在音频设置中重新选择，再恢复监听。"
            )
        elif code == "microphone_failed":
            self._permission_error = True
            self._error = QCoreApplication.translate(
                "Desktop", "麦克风无法采集声音，请检查系统麦克风权限和所选设备，再恢复监听。"
            )
        else:
            self._error = QCoreApplication.translate(
                "Desktop", "语音处理异常，已暂停监听；请恢复监听后重试，文字仍可使用。"
            )
        self.notify()

    def _record_fault(self, code: str | None, *, stage: str | None = None) -> None:
        # Bounded diagnostics contain no speech, transcript or model exception.
        self.faults.append(
            {
                "at": perf_counter(),
                "code": code,
                "input": self._input,
                "output": self._output,
                "capture_pending": self._capture_pending,
                "stage": stage,
            }
        )

    def device_changed(self):
        if self.active and self._connection != "active":
            self._rebuild = True
        self._device_fault("audio_devices_changed")

    def _restart(self, *, resume=False):
        old_runner, old_process = self.runner, self.process
        if old_runner:
            old_runner.input_allowed = False
        self._id = uuid4().hex
        identity = self._id
        self._muted, self._connection = True, "reconnecting"
        self.bridge.close()
        self._rebuild = False
        self.notify()

        async def restart():
            try:
                if old_runner:
                    await old_runner.close()
            finally:
                if old_process:
                    await old_process.close()
            self._emit(identity, "restart", resume)

        self.post(restart)

    @Slot(str, str, int, object)
    def _event(self, identity, kind, generation, value):
        if self._closed or identity != self._id:
            return
        if kind == "transport":
            header, data = value
            event = header["kind"]
            if (
                event in {"near_speech", "input_started", "utterance"}
                and header.get("mic_generation", self._mic_generation) != self._mic_generation
            ):
                return
            if self._muted and event in {"near_speech", "input_started", "utterance"}:
                return
            if event == "playback":
                if not self._audio_generation or header["generation"] != self._audio_generation:
                    return
                self.bridge.enqueue(header["generation"], data)
                # Device faults may synchronously invalidate the output generation.
                if header["generation"] == self._audio_generation and self._output != "playing":
                    self._output = "playing"
                    self.notify()
                # PCM frames are not UI changes. In particular, do not reevaluate
                # hidden settings, device lists and installation plans at 50 Hz.
                return
            elif event == "output_drained":
                self.bridge.finish_output(header["generation"])
            elif event in {"near_speech", "input_started"}:
                self.bridge.stop_output()
                self._audio_generation = ""
                runner = self.runner
                if event == "input_started":
                    self._input = "speaking"
                    self.post(lambda: runner.input_started(header["utterance"], header["revision"]))
                else:
                    self.post(lambda: runner.interrupt("user_interruption"))
            elif event == "utterance" and not self._muted:
                key = header["utterance"]
                self._sources.setdefault(key, self.vm.source_context_provider())
                self._submit_input(header, data, self._sources[key])
            elif event == "disconnected":
                if self._connection not in {"stopping", "off", "reconnecting"}:
                    if self._reconnects == 0:
                        self._reconnects += 1
                        self._restart()
                    else:
                        self.stop()
                        self._error = QCoreApplication.translate(
                            "Desktop", "语音连接未恢复，请重新开始语音。"
                        )
            elif event in {"input_gap", "input_limit", "output_overflow", "operation_failed"}:
                self._device_fault(event)
        elif kind == "connection_stage":
            self._connection_stage = value
        elif kind == "connected":
            resume, metrics = value
            self.timings.update(metrics)
            self._connection = "active"
            try:
                self.bridge.open()
                if resume and not self._rebuild:
                    self.resumeMicrophone()
                else:
                    self._notice = QCoreApplication.translate(
                        "Desktop", "语音已连接，请点击恢复监听。"
                    )
            except Exception:
                self._device_fault("microphone_failed")
        elif kind == "resume_device":
            try:
                self._mic_generation = value.get("mic_generation", self._mic_generation + 1)
                self.runner.input_allowed = True
                self.bridge.resume()
                self._muted, self._notice = False, ""
                self._permission_error = False
                self._error = ""
            except Exception:
                self._device_fault("microphone_failed")
        elif kind == "restart":
            self._connect(resume=value, reconnect=True)
        elif kind == "prepared":
            self.componentsChanged.emit()
            self._connection, self._notice = (
                "off",
                QCoreApplication.translate("Desktop", "连续语音组件已准备。"),
            )
        elif kind == "preparing_server":
            self._notice = QCoreApplication.translate("Desktop", "正在准备本机语音连接组件…")
        elif kind == "progress":
            done, total = value
            self._notice = (
                QCoreApplication.translate("Desktop", "语音组件下载：%1 / %2 MiB")
                .replace("%1", f"{done / 1048576:.1f}")
                .replace("%2", f"{total / 1048576:.1f}")
            )
        elif kind == "failed":
            self.componentsChanged.emit()
            self._record_fault(value, stage=self._connection_stage)
            self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "连续语音未能准备或连接，请在音频设置中重试。"
            )
        elif kind == "stopped":
            self.componentsChanged.emit()
            self._connection = "off"
            self.vm._refresh_session_state()
            self.vm.messagesChanged.emit()
        elif generation >= self._generation:
            self._generation = generation
            if kind == "recognizing":
                self._input = "recognizing"
            elif kind == "input_started":
                self._input = "speaking"
            elif kind == "generating":
                self.timings = {}
                self._attribution = ""
                self._input, self._reply = "idle", "generating"
                self._output = "synthesizing" if self.voice._speak_enabled() else "idle"
                self.vm._streaming_text = ""
            elif kind == "confirmed":
                turn, session = value
                self._turn = turn.id
                self._input, self._retained = "idle", None
                self._sources.clear()
                if self._sent_revision == (self.vm._draft_revision, self.vm.draft):
                    self.vm.draft = ""
                self._sent_revision = None
                self.vm._refresh_session_state(session)
                self.vm.messagesChanged.emit()
                self.vm.historyChanged.emit()
            elif kind == "delta":
                self.vm._streaming_text += value
            elif kind == "attribution":
                self._attribution = value
            elif kind == "output_begin":
                self._audio_generation = value
                try:
                    self.bridge.begin_output(value)
                except Exception:
                    self.stop_speech()
                    self._error = QCoreApplication.translate(
                        "Desktop", "朗读未能播放，文字回复继续生成。"
                    )
            elif kind == "text_completed":
                self._reply = "idle"
                self.vm._streaming_text = ""
                self.vm._refresh_session_state(value.session)
                self.vm._restore_last_reply()
                self.vm.messagesChanged.emit()
            elif kind == "result":
                self._reply = "idle"
                result, metrics = value
                self.timings.update(metrics)
                self._output = "draining" if self._audio_generation else "idle"
                if result.text_status == "failed":
                    self.voice._turn_errors[result.turn_id] = QCoreApplication.translate(
                        "Desktop", "回复未完成，已发送的发言已保留。"
                    )
                elif result.speech_status == "failed":
                    self._record_fault(result.error_code, stage=result.error_stage)
                    self.voice._speech_errors[result.turn_id] = (
                        QCoreApplication.translate(
                            "Desktop", "语音合成未完成，文字回复已保留；可重试朗读。"
                        )
                        if result.error_stage == "tts"
                        else QCoreApplication.translate(
                            "Desktop", "朗读音频未能送达播放设备，文字回复已保留；可重试朗读。"
                        )
                    )
                self.vm._refresh_session_state()
                self.vm.messagesChanged.emit()
                self.vm.historyChanged.emit()
            elif kind == "recognition_failed":
                self._input = "idle"
                # Retain only this bounded failed utterance. Do not mix it with later audio.
                retained = self._retained
                self.muteMicrophone()
                self._retained = retained
                self._error = QCoreApplication.translate(
                    "Desktop", "识别未完成，发言未发送。可重试识别或丢弃后继续。"
                )
            elif kind in {"interrupted", "speech_stopped"}:
                self._output = "idle"
                if kind == "interrupted":
                    self._reply = "idle"
                    self.vm._streaming_text = ""
            elif kind == "reply_failed":
                self._reply = "idle"
                self._output = "idle"
                self._error = QCoreApplication.translate(
                    "Desktop", "回复未完成，已发送的发言已保留。"
                )
            elif kind == "interruption_completed":
                self.vm._refresh_session_state()
                self.vm.messagesChanged.emit()
        self.notify()

    def close(self):
        self._closed = True
        if self.runner:
            self.runner.input_allowed = False
        self._cancel_prepare.set()
        self._id = ""
        self._retained = None
        self._sources.clear()
        if self.bridge:
            self.bridge.close()
