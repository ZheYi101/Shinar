"""Stable QML facade; call state and preparation have explicit, separate owners."""

from pathlib import Path
import sys
from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QCoreApplication
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from .call_coordinator import CallCoordinator
from .call_preparation import CallPreparation
from .call_runtime import CallRuntime
from .call_state import CallEvent, CallSnapshot
from .speech_jobs import preparation_phase_text, preparation_transfer_text


class ContinuousVoiceController(QObject):
    changed = Signal()
    componentsChanged = Signal()
    setupSizesChanged = Signal()
    setupStorageChanged = Signal()
    eventReceived = Signal(object)

    def __init__(self, voice):
        super().__init__(voice)
        self._runtime = CallRuntime(self, voice)
        self._preparation = CallPreparation(self._runtime)
        self._coordinator = CallCoordinator(self._runtime, self._preparation)
        self._runtime.coordinator, self._runtime.preparation = self._coordinator, self._preparation
        self.eventReceived.connect(self.receive_event, Qt.ConnectionType.QueuedConnection)
        self.componentsChanged.connect(self.refresh_setup_sizes)
        self._runtime.worker.jobCompleted.connect(
            self._runtime.job_done, Qt.ConnectionType.QueuedConnection
        )

    @property
    def snapshot(self) -> CallSnapshot:
        return self._coordinator.snapshot

    @property
    def tts_available(self) -> bool:
        return not self.snapshot.tts_error

    @property
    def root(self) -> Path:
        return self._runtime.root

    @root.setter
    def root(self, value: Path) -> None:
        if self._coordinator.active:
            self._coordinator.stop()
        self._runtime.root = Path(value)
        self._preparation.root_changed(Path(value))

    @Slot(object)
    def receive_event(self, event: CallEvent) -> None:
        if event.kind.startswith("setup_"):
            self._preparation.handle(event)
        else:
            self._coordinator.handle(event)

    @Property(bool, notify=componentsChanged)
    def assetsReady(self):
        return self._preparation.assets_ready

    @Property(bool, notify=componentsChanged)
    def environmentReady(self):
        return self._preparation.environment_ready

    @Slot()
    def prepare(self):
        if not self.active and not self._runtime.voice_pending:
            self._preparation.start()

    @Slot()
    def stop(self):
        if self._preparation.snapshot.active:
            self._preparation.cancel()
            self._runtime.notify()
        self._coordinator.stop()

    @Slot()
    def refreshSetupStorage(self):
        self._preparation.refresh_storage()

    def refresh_setup_sizes(self):
        self._preparation.invalidate_sizes()
        self._preparation.sizes()
        self.setupSizesChanged.emit()

    def close(self):
        self._preparation.close()
        self._coordinator.close()

    async def aclose(self):
        await self._coordinator.aclose()

    def device_changed(self):
        self._coordinator.device_changed()

    def post(self, operation):
        return self._runtime.post(operation)

    def send_text(self, text, *, retry_turn=None, speech_only=False):
        self._coordinator.send_text(text, retry_turn=retry_turn, speech_only=speech_only)

    def stop_speech(self):
        self._coordinator.stop_speech()

    @Slot()
    def start(self):
        self._coordinator.start()

    @Slot()
    def muteMicrophone(self):
        self._coordinator.muteMicrophone()

    @Slot()
    def resumeMicrophone(self):
        self._coordinator.resumeMicrophone()

    @Slot()
    def discardInput(self):
        self._coordinator.discardInput()

    @Slot()
    def sendPausedInput(self):
        self._coordinator.sendPausedInput()

    @Slot()
    def stopReply(self):
        self._coordinator.stopReply()

    @Slot()
    def retryInput(self):
        self._coordinator.retryInput()

    @property
    def process_factory(self):
        return self._runtime.process_factory

    @process_factory.setter
    def process_factory(self, value):
        self._runtime.process_factory = value

    @property
    def bridge_factory(self):
        return self._runtime.bridge_factory

    @bridge_factory.setter
    def bridge_factory(self, value):
        self._runtime.bridge_factory = value

    @property
    def bridge(self):
        return self._runtime.bridge

    @bridge.setter
    def bridge(self, value):
        self._runtime.bridge = value

    @property
    def process(self):
        return self._runtime.process

    @process.setter
    def process(self, value):
        self._runtime.process = value

    @property
    def runner(self):
        return self._runtime.runner

    @runner.setter
    def runner(self, value):
        self._runtime.runner = value

    @property
    def timings(self):
        return dict(self._runtime.timings)

    @property
    def faults(self):
        return tuple(dict(value) for value in self._runtime.faults)

    @Property(bool, notify=changed)
    def canOpenModelSettings(self):
        return self.snapshot.model_error

    @Property(bool, notify=changed)
    def active(self):
        return self._coordinator.active or self._preparation.snapshot.active

    @Property(str, notify=changed)
    def connectionState(self):
        return (
            "preparing"
            if self._preparation.snapshot.active
            else "failed"
            if self._preparation.snapshot.failed
            else self.snapshot.connection
        )

    @Property(str, notify=changed)
    def inputState(self):
        return self.snapshot.input

    @Property(str, notify=changed)
    def outputState(self):
        return self.snapshot.output

    @Property(str, notify=changed)
    def replyState(self):
        return self.snapshot.reply

    @Property(bool, notify=changed)
    def muted(self):
        return self.snapshot.muted

    @Property(str, notify=changed)
    def errorText(self):
        return self._preparation.snapshot.error or self.snapshot.error

    @Property(bool, notify=changed)
    def canOpenMicrophoneSettings(self) -> bool:
        return self.snapshot.permission_error and sys.platform == "win32"

    @Slot()
    def openMicrophoneSettings(self) -> None:
        if self.canOpenMicrophoneSettings:
            QDesktopServices.openUrl(QUrl("ms-settings:privacy-microphone"))

    @Property(str, notify=changed)
    def noticeText(self):
        if self._preparation.snapshot.notice:
            return self._preparation.snapshot.notice
        if (
            self.snapshot.connection == "active"
            and self.snapshot.tts_error
            and not self.snapshot.notice
        ):
            return QCoreApplication.translate(
                "Desktop", "本次语音未启用朗读；识别与文字回复可继续。"
            )
        return self.snapshot.notice or (
            QCoreApplication.translate("Desktop", "未启用自动朗读；识别后的发言仍会发送。")
            if self.snapshot.connection == "active" and not self._runtime.speak_enabled()
            else ""
        )

    @Property(str, notify=changed)
    def attributionText(self):
        return self.snapshot.attribution

    @Property(bool, notify=changed)
    def canSendText(self):
        return self._coordinator.canSendText

    @Property(bool, notify=changed)
    def canRetryInput(self):
        return self._coordinator.canRetryInput

    @Property(bool, notify=changed)
    def microphoneBusy(self) -> bool:
        return self.snapshot.microphone_busy

    @Property(bool, notify=changed)
    def hasPendingInput(self):
        return self.snapshot.has_pending_input

    @Property(bool, notify=changed)
    def canSendPausedInput(self):
        return self._coordinator.canSendPausedInput

    @Property(str, notify=changed)
    def setupSizeText(self):
        sizes = self.setupSizes
        return (
            QCoreApplication.translate(
                "Desktop",
                "预计下载 %1 MiB · 安装需可用空间 %2 MiB（含临时文件和余量，不是最终占用或运行内存）。",
            )
            .replace("%1", f"{sizes['downloadMiB']:.1f}")
            .replace("%2", f"{sizes['requiredFreeMiB']:.1f}")
        )

    @Property("QVariantMap", notify=setupSizesChanged)
    def setupSizes(self):
        return self._preparation.sizes()

    @Property("QVariantMap", notify=setupStorageChanged)
    def setupStorage(self):
        return self._preparation.storage

    @Property("QVariantMap", notify=changed)
    def setupProgress(self):
        event = self._preparation.snapshot.transfer
        phase = preparation_phase_text(self._preparation.snapshot.stage)
        if event:
            phase += " · " + preparation_phase_text(event.phase)
        return {
            "phaseText": phase,
            "component": event.component if event else "",
            "transferText": preparation_transfer_text(event.completed, event.total)
            if event
            else "",
            "indeterminate": not event or event.total <= 0,
            "progress": min(1.0, event.completed / event.total) if event and event.total else 0.0,
        }

    @Property(str, notify=changed)
    def statusText(self):
        if self.snapshot.permission_pending:
            return QCoreApplication.translate("Desktop", "正在请求麦克风权限…")
        if self._preparation.snapshot.active:
            return QCoreApplication.translate("Desktop", "正在准备连续语音，麦克风尚未开启…")
        if self.snapshot.connection == "connecting":
            if self.snapshot.connection_stage == "stt":
                return QCoreApplication.translate("Desktop", "正在加载识别模型，麦克风尚未开启…")
            if self.snapshot.connection_stage == "tts":
                return QCoreApplication.translate("Desktop", "正在加载朗读模型，麦克风尚未开启…")
            return QCoreApplication.translate("Desktop", "正在连接语音，麦克风尚未开启…")
        if self.snapshot.connection == "reconnecting":
            return QCoreApplication.translate("Desktop", "语音连接中断，正在重新连接…")
        if self.snapshot.connection == "stopping":
            return QCoreApplication.translate("Desktop", "正在停止语音…")
        if self.snapshot.connection != "active":
            return ""
        if self.snapshot.muted:
            return QCoreApplication.translate("Desktop", "麦克风已暂停，可发送文字")
        if self.snapshot.input == "recognizing":
            return QCoreApplication.translate("Desktop", "正在识别 · 可以继续说")
        if self.snapshot.input == "speaking":
            return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")
        if self.snapshot.output == "playing":
            return QCoreApplication.translate("Desktop", "正在朗读 · 可以插话")
        if self.snapshot.reply == "generating":
            return QCoreApplication.translate("Desktop", "正在回复 · 可以继续说")
        return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")
