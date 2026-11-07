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
from lingualoop.desktop.conversation_presentation import ConversationEvent
from lingualoop.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from lingualoop.realtime.audio_process import AudioSessionProcess
from lingualoop.realtime.continuous_assets import (
    VAD_PACKAGE,
    prepare_assets,
    prepared_assets,
    server_package,
    vad_path,
)
from lingualoop.local_speech.installation import managed_status, runtime_plan
from lingualoop.local_speech.usage import storage_usage
from .speech_errors import safe_speech_code, speech_error_text
from .speech_jobs import preparation_phase_text, preparation_transfer_text


from lingualoop.desktop.continuous_voice_presentation import ContinuousVoicePresentation

class ContinuousVoiceController(QObject, ContinuousVoicePresentation):


    @Property(bool, notify=ContinuousVoicePresentation.componentsChanged)
    def assetsReady(self):
        return prepared_assets(self.root)

    @Property(bool, notify=ContinuousVoicePresentation.componentsChanged)
    def environmentReady(self):
        try:
            return managed_status(self.root, "rtc-cpu").get("prepared", False)
        except (ImportError, ValueError):
            return False

    def __init__(self, voice):
        super().__init__(voice)
        self._presentation_token = None
        self.voice, self.vm, self.worker = voice, voice.vm, voice.worker
        database = self.vm.workbench.storage_path or Path.cwd() / "build" / "voice.sqlite3"
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
        self._tts_error = ""
        self._model_error = False
        self._turn = ""
        self._attribution = ""
        self._sources = {}
        self._retained = None
        self._microphone_busy = False
        self._paused_input = False
        self._pause_id = ""
        self._pause_source = None
        self._sent_revision = None
        self._jobs = set()
        self._reconnects = 0
        self._cancel_prepare = Event()
        self._setup_stage, self._setup_transfer = "", None
        self._setup_sizes = None
        self._setup_storage, self._setup_storage_pending = {}, False
        self._capture_pending = 0
        self._connection_job = ""
        self._permission_pending = self._permission_error = False
        self._connection_stage = ""
        self.timings = {}
        self.faults = deque(maxlen=32)
        self._received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.componentsChanged.connect(self._refresh_setup_sizes)
        self._setupStorageReady.connect(self._set_setup_storage, Qt.ConnectionType.QueuedConnection)
        self.worker.jobCompleted.connect(self._job_done, Qt.ConnectionType.QueuedConnection)

    @property
    def root(self) -> Path:
        return self._root


    @root.setter
    def root(self, value: Path) -> None:
        self._root = Path(value)
        self._setup_storage, self._setup_storage_pending = {}, False
        self.setupStorageChanged.emit()
        self.componentsChanged.emit()

    def notify(self):
        if not self._closed:
            self.changed.emit()
            self.voice.notify()


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
        if self.active or self.voice.pending_job:
            return
        self._id = uuid4().hex
        identity = self._id
        self._cancel_prepare.clear()
        self._connection, self._error, self._notice = "preparing", "", ""
        self._setup_stage, self._setup_transfer = "speech_setup_bootstrap", None
        self.notify()

        async def run():
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                def event(kind, value):
                    self._emit(identity, "setup_" + kind if kind in {"stage", "transfer"} else kind, value)

                await run_blocking(BlockingRequest("runtime", (self.root, "rtc-cpu")),
                                   cancel=self._cancel_prepare, on_event=event)
                self._emit(identity, "setup_stage", "speech_setup_vad")
                await run_blocking(BlockingRequest("continuous_assets", (self.root,)),
                                   cancel=self._cancel_prepare, on_event=event)
                self._emit(identity, "setup_stage", "speech_setup_server")
                await run_blocking(BlockingRequest("server", (self.root / "sfu",), {"download": True}),
                                   cancel=self._cancel_prepare, on_event=event)
                self._emit(identity, "prepared")
            except Exception:
                self._emit(identity, "failed", "prepare_failed")

        self.post(run)

    def _new_bridge(self):
        if self.bridge_factory:
            bridge = self.bridge_factory()
        else:
            from .pcm_audio import PcmAudioBridge

            bridge = PcmAudioBridge(self.vm.audio, self)
        bridge.capture.connect(self._capture)
        bridge.rendered.connect(self._rendered)
        bridge.credit.connect(self._credit)
        bridge.drained.connect(self._drained)
        bridge.fault.connect(self._device_fault)
        return bridge

    @Slot()
    def start(self):
        if self.active or self.voice.pending_job or not self.vm.sessionActive:
            return
        self.voice.preflight.suspendMicrophone()
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
        self._microphone_busy, self._paused_input = False, False
        self._pause_id = ""
        self._pause_source = None
        self._error = self._notice = ""
        self._tts_error = ""
        self._model_error = False
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
        language = self.vm.speech_language()
        speak = self.voice.speak_enabled()
        self.runner = ContinuousConversation(
            self.vm.workbench,
            process,
            lambda kind, generation, value: self._emit(identity, kind, value, generation),
        )
        self.notify()

        async def connect():
            stage = "stt"
            try:
                await asyncio.to_thread(vad_path, self.root, verify=True)
                for route, required in ((stt, True), (tts, False)):
                    if route is tts and not speak:
                        continue
                    try:
                        stage = "stt" if required else "tts"
                        self._emit(identity, "connection_stage", "stt" if required else "tts")
                        bound = await route.bind(language)
                        warm = getattr(bound, "prepare", None)
                        if warm:
                            await warm()
                    except Exception as error:
                        if required:
                            raise
                        self._emit(identity, "tts_unavailable", safe_speech_code(error))
                if identity != self._id or self._closed:
                    return
                self._emit(identity, "connection_stage", "rtc")
                stage = "rtc"
                result = await process.start(config)
                self._emit(identity, "connected", (resume, result))
            except asyncio.CancelledError:
                await process.close()
                raise
            except Exception as error:
                await process.close()
                self._emit(
                    identity,
                    "failed",
                    {"code": safe_speech_code(error), "stage": stage, "language": language},
                )

        self._connection_job = self.post(connect)

    @Slot()
    def muteMicrophone(self):
        self._mute_microphone(preserve=True)

    def _mute_microphone(self, *, preserve: bool = False) -> None:
        if self._connection != "active" or (preserve and (self._muted or self._microphone_busy)):
            return
        # Submit closes before stopping the device or awaiting inference cleanup.
        runner, process, identity = self.runner, self.process, self._id
        runner.input_allowed = False
        flush = getattr(self.bridge, "flush_capture", None)
        if preserve and flush:
            flush()
            if self._muted or self._connection != "active":
                return  # Flushing exposed an input gap/device fault.
        if preserve:
            self._pause_source = self.vm.source_context_provider()
            self._pause_id = uuid4().hex
        pause_id = self._pause_id
        self._muted, self._input = True, "idle"
        self._paused_input, self._microphone_busy = preserve, preserve
        if not preserve:
            self._retained = None
            self._pause_id = ""
        self.bridge.mute()
        self._notice = (
            QCoreApplication.translate("Desktop", "正在暂停麦克风并保留未发送的语音…")
            if preserve else QCoreApplication.translate("Desktop", "麦克风已暂停，可发送文字。")
        )

        async def mute():
            try:
                await runner.cancel_input()
                if preserve:
                    pending = runner.pending_input
                    fields = {k: pending[0][k] for k in ("utterance", "revision")} if pending else {}
                    result = await process.request(
                        "pause", pending[1] if pending else b"", pause_id=pause_id, **fields
                    )
                    self._emit(identity, "pause_device", (pause_id, result))
                else:
                    runner.pending_input = None
                    await process.request("mute")
            except Exception:
                self._emit(identity, "input_control_failed")

        self.post(mute)
        self.notify()

    @Slot()
    def resumeMicrophone(self):
        if self._connection != "active" or not self._muted or self._microphone_busy:
            return
        self._with_microphone_permission(self._resume_permitted)

    def _resume_permitted(self):
        if self._rebuild:
            self._restart(resume=True)
            return
        self._notice = ""
        preserve = self._paused_input
        if not preserve:
            self._retained = None
        self._microphone_busy = True
        identity, process = self._id, self.process

        async def resume():
            try:
                result = await process.request("resume", preserve_input=preserve)
                self._emit(identity, "resume_device", result)
            except Exception:
                self._emit(identity, "failed", "connection_failed")

        self.post(resume)
        self.notify()

    @Slot()
    def discardInput(self) -> None:
        if not self.hasPendingInput:
            return
        runner, process, identity = self.runner, self.process, self._id
        self._microphone_busy = True
        self._pause_id = ""
        self._retained = None
        self._sources.clear()
        self._error = ""
        self.notify()

        async def discard():
            try:
                await runner.cancel_input()
                runner.pending_input = None
                await process.request("discard_input")
                self._emit(identity, "input_discarded")
            except Exception:
                self._emit(identity, "input_control_failed")

        self.post(discard)

    @Slot()
    def sendPausedInput(self) -> None:
        if not self.canSendPausedInput:
            return
        header, data, source = self._retained
        self._paused_input = False
        self._pause_id = ""
        self._input = "recognizing"
        runner, process, identity = self.runner, self.process, self._id

        async def send():
            try:
                await runner.cancel_input()
                await process.request("discard_input")
                self._emit(identity, "submit_paused", (header, data, source))
            except Exception:
                self._emit(identity, "input_control_failed")

        self.post(send)
        self.notify()

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
        self._microphone_busy, self._paused_input = False, False
        self._pause_id = ""
        self._pause_source = None
        self._sources.clear()
        self._presentation_token = self.vm.new_presentation_token(identity + ":stop")
        self.vm.present_conversation(ConversationEvent("begin", self._presentation_token))
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
        speak = self.voice.speak_enabled() or speech_only
        source = self.vm.source_context_provider()
        self._sent_revision = (
            (self.vm.draft_revision, self.vm.draft)
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
        if self._muted:
            self._notice = ""
        runner, speak = self.runner, self.voice.speak_enabled()
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
                self.voice.speech_errors[self._turn] = self._error
            self.notify()
            return
        self._rebuild = code in {"audio_devices_changed", "microphone_failed"}
        self._mute_microphone()
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


    def close(self):
        self._closed = True
        if self.runner:
            self.runner.input_allowed = False
        self._cancel_prepare.set()
        self._id = ""
        self._retained = None
        self._pause_source = None
        self._pause_id = ""
        self._sources.clear()
        if self.bridge:
            self.bridge.close()
