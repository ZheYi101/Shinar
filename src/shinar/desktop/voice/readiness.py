"""Conversation-page preflight, independent of recording and business operations."""

from shinar.local_speech.installation import managed_status
from shinar.realtime.continuous_assets import prepared_assets

from shinar.desktop.voice.routing import SpeechRoute

import asyncio
from time import perf_counter
from uuid import uuid4
import sys

from PySide6.QtCore import (
    QObject, Property, QCoreApplication, QMicrophonePermission, Qt, QTimer, Signal, Slot, QUrl,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioSource, QMediaDevices, QtAudio

from shinar.local_speech.profiles import LocalSpeechProvider
from shinar.desktop.voice.pcm_audio import PcmAudioBridge
from shinar.desktop.tasks.speech_errors import safe_speech_code, speech_error_text


class MicrophoneProbe(QObject):
    """Read and immediately discard a few device frames; never publish or save PCM."""

    finished = Signal(str)

    def __init__(self, audio, parent=None):
        super().__init__(parent)
        self.audio = audio
        self.source = self.io = None
        self._finished = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(lambda: self._finish("microphone_no_frames"))

    def start(self) -> None:
        try:
            device = next(
                d for d in QMediaDevices.audioInputs()
                if bytes(d.id()).hex() == self.audio.selected_input_id
            )
            fmt, _ = PcmAudioBridge._format(device)
            self.source = QAudioSource(device, fmt, self)
            self.source.setBufferSize(fmt.bytesForDuration(80000))
            self.source.stateChanged.connect(self._state)
            self._timer.start()
            source = self.source
            io = source.start()
            if self._finished:
                return
            self.io = io
            if self.io is None or source.error() != QtAudio.Error.NoError:
                self._finish("microphone_open_failed")
                return
            self.io.readyRead.connect(self._read)
            self._read()
        except (StopIteration, ValueError, RuntimeError, AttributeError):
            self._finish("audio_device_missing")

    @Slot()
    def _read(self) -> None:
        if self.io and self.io.bytesAvailable():
            self.io.readAll()  # No buffer, waveform, transcription or model request.
            self._finish("")

    @Slot()
    def _state(self) -> None:
        if self.source and self.source.error() != QtAudio.Error.NoError:
            self._finish("microphone_open_failed")

    def _finish(self, error: str) -> None:
        if self._finished:
            return
        self._finished = True
        self.close()
        self.finished.emit(error)

    def close(self) -> None:
        self._timer.stop()
        source, self.source, self.io = self.source, None, None
        self._finished = True
        if source:
            source.stop()
            source.deleteLater()


class VoiceReadinessController(QObject):
    """Warm only already-selected local models; page entry never installs resources."""

    changed = Signal()
    _progress = Signal(str, str, object)

    def __init__(self, voice):
        super().__init__(voice)
        self.voice, self.vm, self.worker = voice, voice.vm, voice.worker
        self.probe_factory = lambda: MicrophoneProbe(self.vm.audio, self)
        self._visible = self._closed = False
        self._revision = 0
        self._key = None
        self._job = ""
        self._probe = None
        self._probe_id = ""
        self._permission_pending = False
        self._permission_callback = None
        self._states = dict.fromkeys(("microphone", "stt", "tts", "components"), "idle")
        self._errors = {}
        self._local = set()
        self.timings = {}
        self._progress.connect(self._update, Qt.ConnectionType.QueuedConnection)
        self.worker.jobCompleted.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self.vm.sessionChanged.connect(self.refresh)
        self.vm.preferences.changed.connect(self.refresh)
        self.voice.changed.connect(self._voice_changed)
        self.voice.call.componentsChanged.connect(self.invalidate)
        if self.vm.audio:
            self.vm.audio.devicesChanged.connect(self.invalidate)
        self._residency = QTimer(self)
        self._residency.setInterval(2000)
        self._residency.timeout.connect(self.refreshResidency)

    @Property(list, notify=changed)
    def checks(self) -> list[dict]:
        labels = {
            "microphone": QCoreApplication.translate("Desktop", "麦克风"),
            "stt": QCoreApplication.translate("Desktop", "识别 STT"),
            "tts": QCoreApplication.translate("Desktop", "朗读 TTS"),
            "components": QCoreApplication.translate("Desktop", "语音连接组件"),
        }
        states = {
            "idle": QCoreApplication.translate("Desktop", "待检查"),
            "checking": QCoreApplication.translate("Desktop", "检查中…"),
            "loading": QCoreApplication.translate("Desktop", "加载中…"),
            "ready": QCoreApplication.translate("Desktop", "已就绪"),
            "configured": QCoreApplication.translate("Desktop", "已配置，连接待验证"),
            "on_demand": QCoreApplication.translate("Desktop", "已验证，按需加载"),
            "released": QCoreApplication.translate("Desktop", "已释放，下次使用重新加载"),
            "disabled": QCoreApplication.translate("Desktop", "自动朗读已关闭"),
            "error": QCoreApplication.translate("Desktop", "需处理"),
        }
        return [
            {"id": task, "label": labels[task], "state": state,
             "text": states[state], "error": self._errors.get(task, "")}
            for task, state in self._states.items()
        ]

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return any(s in {"checking", "loading"} for s in self._states.values())

    @Property(bool, notify=changed)
    def canCheck(self) -> bool:
        return not self.voice.active and not self.busy

    @Property(bool, notify=changed)
    def needsModelSettings(self) -> bool:
        return any(self._states[t] == "error" for t in ("stt", "tts"))

    @Property(bool, notify=changed)
    def needsAudioSettings(self) -> bool:
        return any(self._states[t] == "error" for t in ("microphone", "components"))

    @Property(bool, notify=changed)
    def canOpenMicrophoneSettings(self) -> bool:
        return self._states["microphone"] == "error" and sys.platform == "win32"

    @Slot()
    def openMicrophoneSettings(self) -> None:
        if self.canOpenMicrophoneSettings:
            QDesktopServices.openUrl(QUrl("ms-settings:privacy-microphone"))

    @Slot(bool)
    def setPageVisible(self, visible: bool) -> None:
        if self._visible == visible or self._closed:
            return
        self._visible = visible
        if visible:
            self._key = None
            self._residency.start()
            self.refresh()
        else:
            self._residency.stop()
            self._cancel()

    def _context(self):
        session = self.vm.workbench.session
        return (
            session.id if session else "", self.vm.speech_language(), self._revision,
            id(self.vm.speech_provider("stt")), id(self.vm.speech_provider("tts")), id(self.vm.local_speech),
            self.vm.preferences.autoReadReplies,
        )

    @Slot()
    def invalidate(self) -> None:
        self._revision += 1
        self.refresh()

    @Slot()
    def retry(self) -> None:
        if self.canCheck:
            self._key = None
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        if self._closed or not self._visible or self.voice.active:
            return
        if not self.vm.sessionActive:
            self._key = None
            self._cancel()
            return
        key = self._context()
        if key == self._key:
            if self._states["microphone"] == "idle":
                self._states["microphone"] = "checking"
                self._check_microphone()
                self.changed.emit()
            return
        self._cancel()
        self._key = key
        self._states = dict.fromkeys(self._states, "checking")
        self._errors.clear()
        self._local.clear()
        self.timings = {}
        self._job = "voice-preflight-" + uuid4().hex
        job, language, root = self._job, key[1], self.voice.call.root

        routes = {task: SpeechRoute(self.vm, task) for task in ("stt", "tts")}
        speak = self.vm.preferences.autoReadReplies

        async def check() -> None:
            try:
                ready = await asyncio.to_thread(
                    lambda: managed_status(root, "rtc-cpu").get("prepared", False)
                    and prepared_assets(root)
                )
            except Exception:
                ready = False
            self._progress.emit(job, "components", ("ready" if ready else "error", "", 0))
            for task, route in routes.items():
                if task == "tts" and not speak:
                    self._progress.emit(job, task, ("disabled", "", 0))
                    continue
                self._progress.emit(job, task, ("loading", "", 0))
                started = perf_counter()
                measured = {}
                try:
                    async with asyncio.timeout(130):
                        bound = await route.bind(language)
                        # Remote services are not billed on page entry. Their
                        # configuration alone cannot be labelled as verified.
                        local = isinstance(bound, LocalSpeechProvider)
                        if local:
                            await bound.prepare()
                            measured[task + "_load_ms"] = (perf_counter() - started) * 1000
                            self._progress.emit(job, task, ("checking", "", 0))
                            testing = perf_counter()
                            await bound.verify()
                            measured[task + "_self_test_ms"] = (perf_counter() - testing) * 1000
                    state = (
                        "on_demand" if local and bound.profile.idle_seconds == 0
                        else "ready" if local else "configured"
                    )
                    code = ""
                except Exception as exc:
                    state, code = "error", safe_speech_code(exc)
                    local = False
                self._progress.emit(
                    job, task, (state, code, (perf_counter() - started) * 1000, local, measured)
                )

        self.worker.submit_job(job, check)
        self._check_microphone()
        self.changed.emit()

    def _check_microphone(self) -> None:
        identity = self._probe_id = uuid4().hex
        started = perf_counter()
        app, permission = QCoreApplication.instance(), QMicrophonePermission()

        def allowed(status):
            if identity != self._probe_id or self._closed or self.voice.active:
                return
            if status != Qt.PermissionStatus.Granted:
                finished("microphone_permission_denied")
                return
            self._probe = self.probe_factory()
            self._probe.finished.connect(finished)
            self._probe.start()

        def finished(error):
            if identity != self._probe_id or self._closed:
                return
            self.timings["microphone_ms"] = (perf_counter() - started) * 1000
            self._stop_probe()
            self._states["microphone"] = "error" if error else "ready"
            if error:
                self._errors["microphone"] = QCoreApplication.translate(
                    "Desktop", "麦克风未能采集音频，请检查系统权限及所选输入设备。"
                )
            self.changed.emit()

        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Undetermined:
            self._permission_callback = allowed
            if not self._permission_pending:
                self._permission_pending = True

                def permission_result(result):
                    self._permission_pending = False
                    callback, self._permission_callback = self._permission_callback, None
                    if callback:
                        callback(result.status())

                app.requestPermission(permission, self, permission_result)
        else:
            allowed(status)

    @Slot(str, str, object)
    def _update(self, job, task, result) -> None:
        if job != self._job or self._closed or not self._visible:
            return
        state, code, ms, *local = result
        self._states[task] = state
        if ms:
            self.timings[task + "_ms"] = ms
        if local and local[0]:
            self._local.add(task)
        if len(local) > 1:
            self.timings.update(local[1])
        if state == "error":
            self._errors[task] = (
                speech_error_text(code, task, self._key[1])
                if task in {"stt", "tts"} else QCoreApplication.translate(
                    "Desktop", "连续语音组件尚未准备，请前往设置 → 音频设备。"
                )
            )
        self.changed.emit()

    @Slot(str, object, str)
    def _completed(self, job, result, error) -> None:
        if not job.startswith("voice-preflight-"):
            return
        self.worker.forget_job(job)
        if job != self._job or self._closed:
            return
        self._job = ""
        if error:
            for task in ("stt", "tts", "components"):
                if self._states[task] in {"checking", "loading"}:
                    self._states[task] = "error"
        self.changed.emit()

    @Slot()
    def refreshResidency(self) -> None:
        service = self.vm.local_speech
        if self._closed or self.voice.active or not service:
            return
        changed = False
        for task in self._local:
            if self._states[task] == "ready" and service.worker_pid(task) is None:
                self._states[task] = "released"
                changed = True
        if changed:
            self.changed.emit()

    @Slot()
    def _voice_changed(self) -> None:
        if self.voice.active:
            # Preparation may finish under the inference service's existing
            # lock. Never cancel/kill a model adopted by an active turn/call.
            self.suspendMicrophone()
        elif self._visible:
            self.refresh()

    def _stop_probe(self) -> None:
        self._probe_id = ""
        self._permission_callback = None
        if self._probe:
            self._probe.close()
            self._probe.deleteLater()
            self._probe = None

    def suspendMicrophone(self) -> None:
        self._stop_probe()
        if self._states["microphone"] == "checking":
            self._states["microphone"] = "idle"
        self.changed.emit()

    def _cancel(self) -> None:
        self._stop_probe()
        job, self._job = self._job, ""
        if job and not self.voice.active:
            self.worker.cancel_job(job)

    def close(self) -> None:
        self._closed = True
        self._residency.stop()
        self._cancel()
