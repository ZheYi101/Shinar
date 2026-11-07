"""Call-state projections and generation-guarded event reduction."""

import asyncio
import sys

from PySide6.QtCore import (
    Property,
    Signal,
    Slot,
    QCoreApplication,
    QUrl,
)
from PySide6.QtGui import QDesktopServices

from lingualoop.desktop.conversation_presentation import ConversationEvent
from lingualoop.realtime.continuous_assets import (
    VAD_PACKAGE,
    server_package,
)
from lingualoop.local_speech.installation import runtime_plan
from lingualoop.local_speech.usage import storage_usage
from .speech_errors import speech_error_text
from .speech_jobs import preparation_phase_text, preparation_transfer_text


class ContinuousVoicePresentation:
    changed = Signal()

    componentsChanged = Signal()

    setupSizesChanged = Signal()

    setupStorageChanged = Signal()

    _setupStorageReady = Signal(str, object)

    _received = Signal(str, str, int, object)

    @Property(bool, notify=changed)
    def canOpenModelSettings(self):
        return self._model_error

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
        if self._connection == "active" and self._tts_error and not self._notice:
            return QCoreApplication.translate(
                "Desktop", "本次语音未启用朗读；识别与文字回复可继续。"
            )
        return self._notice or (
            QCoreApplication.translate("Desktop", "未启用自动朗读；识别后的发言仍会发送。")
            if self._connection == "active" and not self.voice.speak_enabled()
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
            and not self._microphone_busy
            and not self.vm.operationBusy
        )

    @Property(bool, notify=changed)
    def canRetryInput(self):
        return self.hasPendingInput and not self._paused_input

    @Property(bool, notify=changed)
    def microphoneBusy(self) -> bool:
        return self._microphone_busy

    @Property(bool, notify=changed)
    def hasPendingInput(self) -> bool:
        return (
            self._retained is not None and self._connection == "active" and self._muted
            and not self._microphone_busy and self._input == "idle"
        )

    @Property(bool, notify=changed)
    def canSendPausedInput(self) -> bool:
        return self.hasPendingInput and self._paused_input



    @Property(str, notify=setupSizesChanged)
    def setupSizeText(self):
        sizes = self.setupSizes
        return QCoreApplication.translate(
            "Desktop", "预计下载 %1 MiB · 安装需可用空间 %2 MiB（含临时文件和余量，不是最终占用或运行内存）。"
        ).replace("%1", f"{sizes['downloadMiB']:.1f}").replace("%2", f"{sizes['requiredFreeMiB']:.1f}")

    @Property("QVariantMap", notify=setupSizesChanged)
    def setupSizes(self):
        if self._setup_sizes is not None:
            return self._setup_sizes
        plan = runtime_plan(self.root, "rtc-cpu")
        assets = [*VAD_PACKAGE.files, *server_package().files]
        pending = sum(a.size for a in assets if not (self.root / "downloads" / a.sha256).is_file())
        self._setup_sizes = {
            "downloadMiB": (plan.download_bytes + pending) / 1024**2,
            "requiredFreeMiB": (plan.disk_bytes + sum(a.size * 3 for a in assets)) / 1024**2,
        }
        return self._setup_sizes

    def _refresh_setup_sizes(self):
        self._setup_sizes = None
        self._setup_sizes = self.setupSizes
        self.setupSizesChanged.emit()

    @Property("QVariantMap", notify=setupStorageChanged)
    def setupStorage(self):
        return self._setup_storage

    @Slot()
    def refreshSetupStorage(self) -> None:
        if self._closed or self._setup_storage_pending:
            return
        self._setup_storage_pending = True
        root = self.root

        async def collect():
            try:
                usage = await asyncio.to_thread(storage_usage, root)
            except OSError:
                usage = {"incomplete": True}
            self._setupStorageReady.emit(str(root), usage)

        self.post(collect)

    @Slot(str, object)
    def _set_setup_storage(self, root, usage):
        if self._closed or str(self.root) != root:
            return
        self._setup_storage_pending = False
        self._setup_storage = usage
        self.setupStorageChanged.emit()

    @Property("QVariantMap", notify=changed)
    def setupProgress(self):
        event = self._setup_transfer
        phase = preparation_phase_text(self._setup_stage)
        if event:
            phase += " · " + preparation_phase_text(event.phase)
        return {
            "phaseText": phase, "component": event.component if event else "",
            "transferText": preparation_transfer_text(event.completed, event.total) if event else "",
            "indeterminate": not event or event.total <= 0,
            "progress": min(1.0, event.completed / event.total) if event and event.total else 0.0,
        }

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
            return QCoreApplication.translate("Desktop", "麦克风已暂停，可发送文字")
        if self._input == "recognizing":
            return QCoreApplication.translate("Desktop", "正在识别 · 可以继续说")
        if self._input == "speaking":
            return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")
        if self._output == "playing":
            return QCoreApplication.translate("Desktop", "正在朗读 · 可以插话")
        if self._reply == "generating":
            return QCoreApplication.translate("Desktop", "正在回复 · 可以继续说")
        return QCoreApplication.translate("Desktop", "正在听 · 停顿后自动发送")

    @Slot(str, str, int, object)
    def _event(self, identity, kind, generation, value):
        if self._closed or identity != self._id:
            return
        if kind == 'transport':
            if not self._call_transport(identity, kind, generation, value):
                return
        elif kind == 'connection_stage':
            if not self._call_connection_stage(identity, kind, generation, value):
                return
        elif kind == 'connected':
            if not self._call_connected(identity, kind, generation, value):
                return
        elif kind == 'resume_device':
            if not self._call_resume_device(identity, kind, generation, value):
                return
        elif kind == 'pause_device':
            if not self._call_pause_device(identity, kind, generation, value):
                return
        elif kind == 'input_discarded':
            if not self._call_input_discarded(identity, kind, generation, value):
                return
        elif kind == 'input_control_failed':
            if not self._call_input_control_failed(identity, kind, generation, value):
                return
        elif kind == 'submit_paused':
            if not self._call_submit_paused(identity, kind, generation, value):
                return
        elif kind == 'restart':
            if not self._call_restart(identity, kind, generation, value):
                return
        elif kind == 'prepared':
            if not self._call_prepared(identity, kind, generation, value):
                return
        elif kind == 'preparing_server':
            if not self._call_preparing_server(identity, kind, generation, value):
                return
        elif kind == 'setup_stage':
            if not self._call_setup_stage(identity, kind, generation, value):
                return
        elif kind == 'setup_transfer':
            if not self._call_setup_transfer(identity, kind, generation, value):
                return
        elif kind == 'progress':
            if not self._call_progress(identity, kind, generation, value):
                return
        elif kind == 'failed':
            if not self._call_failed(identity, kind, generation, value):
                return
        elif kind == 'tts_unavailable':
            if not self._call_tts_unavailable(identity, kind, generation, value):
                return
        elif kind == 'stopped':
            if not self._call_stopped(identity, kind, generation, value):
                return
        elif generation >= self._generation:
            if not self._apply_turn_event(identity, kind, generation, value):
                return
        self.notify()

    def _call_transport(self, identity, kind, generation, value):
        header, data = value
        event = header["kind"]
        if (
            event in {"near_speech", "input_started", "utterance"}
            and header.get("mic_generation", self._mic_generation) != self._mic_generation
        ):
            return False
        if self._muted and event in {"near_speech", "input_started", "utterance"}:
            return False
        if event == "playback":
            if not self._audio_generation or header["generation"] != self._audio_generation:
                return False
            self.bridge.enqueue(header["generation"], data)
            # Device faults may synchronously invalidate the output generation.
            if header["generation"] == self._audio_generation and self._output != "playing":
                self._output = "playing"
                self.notify()
            # PCM frames are not UI changes. In particular, do not reevaluate
            # hidden settings, device lists and installation plans at 50 Hz.
            return False
        elif event == "input_paused":
            if self._muted and header.get("pause_id") == self._pause_id:
                key = header["utterance"]
                source = self._sources.setdefault(key, self._pause_source)
                self._retained = (header, data, source)
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
        return True

    def _call_connection_stage(self, identity, kind, generation, value):
        self._connection_stage = value
        return True

    def _call_connected(self, identity, kind, generation, value):
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
        return True

    def _call_resume_device(self, identity, kind, generation, value):
        try:
            self._mic_generation = value.get("mic_generation", self._mic_generation + 1)
            self.runner.input_allowed = True
            self.bridge.resume()
            self._muted, self._notice = False, ""
            self._microphone_busy, self._paused_input = False, False
            self._pause_id = ""
            self._permission_error = False
            self._error = ""
        except Exception:
            self._device_fault("microphone_failed")
        return True

    def _call_pause_device(self, identity, kind, generation, value):
        pause_id, result = value
        if pause_id == self._pause_id:
            self._microphone_busy = False
            self._input = "idle"
            if not result.get("has_input"):
                self._retained = None
            self._notice = (
                QCoreApplication.translate("Desktop", "麦克风已暂停；未发送的语音已保留，可继续说或发送已说内容。")
                if self._retained else QCoreApplication.translate("Desktop", "麦克风已暂停，可发送文字；恢复后继续监听。")
            )
        return True

    def _call_input_discarded(self, identity, kind, generation, value):
        self._microphone_busy = False
        self._notice = QCoreApplication.translate("Desktop", "已丢弃未发送的语音；麦克风仍暂停。")
        return True

    def _call_input_control_failed(self, identity, kind, generation, value):
        self._microphone_busy = False
        self._pause_id = ""
        self._input = "idle"
        self._error = QCoreApplication.translate("Desktop", "麦克风暂停或恢复未完成，请停止语音后重新连接。")
        return True

    def _call_submit_paused(self, identity, kind, generation, value):
        self._submit_input(*value, retry=True)
        return True

    def _call_restart(self, identity, kind, generation, value):
        self._connect(resume=value, reconnect=True)
        return True

    def _call_prepared(self, identity, kind, generation, value):
        self.componentsChanged.emit()
        self.refreshSetupStorage()
        self._connection, self._notice = (
            "off",
            QCoreApplication.translate("Desktop", "连续语音组件已准备。"),
        )
        return True

    def _call_preparing_server(self, identity, kind, generation, value):
        self._notice = QCoreApplication.translate("Desktop", "正在准备本机语音连接组件…")
        return True

    def _call_setup_stage(self, identity, kind, generation, value):
        self._setup_stage, self._setup_transfer = value, None
        return True

    def _call_setup_transfer(self, identity, kind, generation, value):
        self._setup_transfer = value
        return True

    def _call_progress(self, identity, kind, generation, value):
        done, total = value
        self._notice = (
            QCoreApplication.translate("Desktop", "当前文件：%1 / %2 MiB；整项准备尚未完成。")
            .replace("%1", f"{done / 1048576:.1f}")
            .replace("%2", f"{total / 1048576:.1f}")
        )
        return True

    def _call_failed(self, identity, kind, generation, value):
        self.componentsChanged.emit()
        self.refreshSetupStorage()
        code = value.get("code") if isinstance(value, dict) else value
        stage = value.get("stage") if isinstance(value, dict) else self._connection_stage
        self._record_fault(code, stage=stage)
        self._connection = "failed"
        if isinstance(value, dict) and stage in {"stt", "tts"}:
            self._model_error = True
            self._error = speech_error_text(code, stage, value["language"])
        else:
            self._error = QCoreApplication.translate(
                "Desktop", "本机语音连接未建立，请在音频设备中检查连续语音组件后重试。"
            )
        return True

    def _call_tts_unavailable(self, identity, kind, generation, value):
        self._tts_error = value
        self._model_error = True
        self._notice = QCoreApplication.translate(
            "Desktop", "本次语音未启用朗读；识别与文字回复可继续。"
        )
        return True

    def _call_stopped(self, identity, kind, generation, value):
        self.componentsChanged.emit()
        self.refreshSetupStorage()
        self._connection = "off"
        self.vm.present_conversation(ConversationEvent("refresh", self._presentation_token))
        return True

    def _turn_recognizing(self, identity, kind, generation, value):
        self._input = "recognizing"
        return True

    def _turn_input_started(self, identity, kind, generation, value):
        self._input = "speaking"
        return True

    def _turn_generating(self, identity, kind, generation, value):
        self.timings = {}
        self._attribution = ""
        self._input, self._reply = "idle", "generating"
        self._output = "synthesizing" if self.voice.speak_enabled() else "idle"
        self._presentation_token = self.vm.new_presentation_token(f"{identity}:{generation}")
        self.vm.present_conversation(ConversationEvent("begin", self._presentation_token))
        return True

    def _turn_confirmed(self, identity, kind, generation, value):
        turn, session = value
        self._turn = turn.id
        self._presentation_token = self.vm.confirm_presentation(
            self._presentation_token, turn.id, session, self._sent_revision,
        )
        self._input = "idle"
        if self._retained:
            key = self._retained[0]["utterance"]
            if turn.request_id == f"voice:{self.process.id}:{key}":
                self._retained = None
                self._sources.pop(key, None)
        self._sent_revision = None
        return True

    def _turn_delta(self, identity, kind, generation, value):
        self.vm.present_conversation(ConversationEvent("delta", self._presentation_token, text=value))
        return True

    def _turn_attribution(self, identity, kind, generation, value):
        self._attribution = value
        return True

    def _turn_output_begin(self, identity, kind, generation, value):
        self._audio_generation = value
        try:
            self.bridge.begin_output(value)
        except Exception:
            self.stop_speech()
            self._error = QCoreApplication.translate(
                "Desktop", "朗读未能播放，文字回复继续生成。"
            )
        return True

    def _turn_text_completed(self, identity, kind, generation, value):
        self._reply = "idle"
        self.vm.present_conversation(ConversationEvent("complete", self._presentation_token, value.session))
        return True

    def _turn_result(self, identity, kind, generation, value):
        self._reply = "idle"
        result, metrics = value
        self.timings.update(metrics)
        self._output = "draining" if self._audio_generation else "idle"
        if result.text_status == "failed":
            self.voice.turn_errors[result.turn_id] = QCoreApplication.translate(
                "Desktop", "回复未完成，已发送的发言已保留。"
            )
        elif result.speech_status == "failed":
            self._record_fault(result.error_code, stage=result.error_stage)
            self.voice.speech_error_codes[result.turn_id] = result.error_code
            self.voice.speech_errors[result.turn_id] = (
                speech_error_text(
                    result.error_code or "speech_synthesis_failed",
                    "tts",
                    self.vm.speech_language(),
                )
                if result.error_stage == "tts"
                else QCoreApplication.translate(
                    "Desktop", "朗读音频未能送达播放设备，文字回复已保留；可重试朗读。"
                )
            )
        self.vm.present_conversation(ConversationEvent("settled", self._presentation_token, history_changed=True))
        return True

    def _turn_recognition_failed(self, identity, kind, generation, value):
        self._input = "idle"
        # Retain only this bounded failed utterance. Do not mix it with later audio.
        retained = self._retained
        self._mute_microphone()
        self._retained = retained
        self._error = QCoreApplication.translate(
            "Desktop", "识别未完成，发言未发送。可重试识别或丢弃后继续。"
        )
        return True

    def _turn_interrupted(self, identity, kind, generation, value):
        self._output = "idle"
        if kind == "interrupted":
            self._reply = "idle"
            self.vm.present_conversation(ConversationEvent("interrupt", self._presentation_token))
        return True

    def _turn_reply_failed(self, identity, kind, generation, value):
        self.vm.present_conversation(ConversationEvent("fail", self._presentation_token))
        self._reply = "idle"
        self._output = "idle"
        self._error = QCoreApplication.translate(
            "Desktop", "回复未完成，已发送的发言已保留。"
        )
        return True

    def _turn_interruption_completed(self, identity, kind, generation, value):
        self.vm.present_conversation(ConversationEvent("refresh", self._presentation_token))
        return True

    def _apply_turn_event(self, identity, kind, generation, value):
        if self._muted and self._paused_input and kind in {
            "recognizing", "input_started", "recognition_failed"
        }:
            return False
        self._generation = generation
        if kind == 'recognizing':
            return self._turn_recognizing(identity, kind, generation, value)
        elif kind == 'input_started':
            return self._turn_input_started(identity, kind, generation, value)
        elif kind == 'generating':
            return self._turn_generating(identity, kind, generation, value)
        elif kind == 'confirmed':
            return self._turn_confirmed(identity, kind, generation, value)
        elif kind == 'delta':
            return self._turn_delta(identity, kind, generation, value)
        elif kind == 'attribution':
            return self._turn_attribution(identity, kind, generation, value)
        elif kind == 'output_begin':
            return self._turn_output_begin(identity, kind, generation, value)
        elif kind == 'text_completed':
            return self._turn_text_completed(identity, kind, generation, value)
        elif kind == 'result':
            return self._turn_result(identity, kind, generation, value)
        elif kind == 'recognition_failed':
            return self._turn_recognition_failed(identity, kind, generation, value)
        elif kind in {'interrupted', 'speech_stopped'}:
            return self._turn_interrupted(identity, kind, generation, value)
        elif kind == 'reply_failed':
            return self._turn_reply_failed(identity, kind, generation, value)
        elif kind == 'interruption_completed':
            return self._turn_interruption_completed(identity, kind, generation, value)
        return True
