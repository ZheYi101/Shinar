"""Single owner of call state and generation-checked event reduction."""

from functools import partial
from uuid import uuid4
from PySide6.QtCore import QCoreApplication
from shinar.application.continuous_voice import ContinuousConversation
from shinar.desktop.presentation.conversation_presentation import ConversationEvent
from shinar.desktop.tasks.speech_errors import speech_error_text, call_device_error
from shinar.desktop.voice.continuous.state import CallEvent, CallSnapshot
from shinar.desktop.voice.continuous.ports import CallRuntimePort
from shinar.desktop.voice.continuous.preparation import CallPreparation
from shinar.desktop.voice.continuous.work import connect_call, pause_call, resume_call, discard_call, send_paused_call, restart_call

CONNECTION_EVENTS = {
    "transport": "_call_transport",
    "connection_stage": "_call_connection_stage",
    "connected": "_call_connected",
    "resume_device": "_call_resume_device",
    "pause_device": "_call_pause_device",
    "input_discarded": "_call_input_discarded",
    "input_control_failed": "_call_input_control_failed",
    "submit_paused": "_call_submit_paused",
    "restart": "_call_restart",
    "failed": "_call_failed",
    "tts_unavailable": "_call_tts_unavailable",
    "stopped": "_call_stopped",
}


class CallCoordinator:
    def __init__(self, runtime: CallRuntimePort, preparation: CallPreparation):
        self.runtime, self.preparation = runtime, preparation
        self._presentation_token = None
        self._connection, self._input, self._output = "off", "idle", "idle"
        self._reply = "idle"
        self._muted, self._closed, self._rebuild = True, False, False
        self._id, self._generation, self._audio_generation = "", 0, ""
        self._mic_generation = 0
        self._error = self._notice = self._tts_error = ""
        self._model_error = False
        self._turn = self._attribution = ""
        self._sources = {}
        self._retained = None
        self._microphone_busy = self._paused_input = False
        self._pause_id = ""
        self._pause_source = self._sent_revision = None
        self._reconnects = 0
        self._connection_job = self._connection_stage = ""
        self._permission_pending = self._permission_error = False

    @property
    def snapshot(self) -> CallSnapshot:
        return CallSnapshot(
            identity=self._id,
            connection=self._connection,
            input=self._input,
            output=self._output,
            reply=self._reply,
            muted=self._muted,
            closed=self._closed,
            generation=self._generation,
            audio_generation=self._audio_generation,
            mic_generation=self._mic_generation,
            error=self._error,
            notice=self._notice,
            tts_error=self._tts_error,
            model_error=self._model_error,
            attribution=self._attribution,
            microphone_busy=self._microphone_busy,
            paused_input=self._paused_input,
            pause_id=self._pause_id,
            permission_pending=self._permission_pending,
            permission_error=self._permission_error,
            connection_stage=self._connection_stage,
            has_pending_input=self.hasPendingInput,
            retained_utterance=self._retained[0]["utterance"] if self._retained else "",
        )

    def current(self, identity: str) -> bool:
        return not self._closed and identity == self._id

    def permission_requested(self, starting: bool) -> None:
        self._permission_pending = True
        if starting:
            self._connection = "permission"
        self.runtime.notify()

    def permission_result(self, allowed: bool, starting: bool) -> None:
        self._permission_pending = False
        self._permission_error = not allowed
        if not allowed:
            if starting:
                self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "麦克风权限未开启，请允许此应用使用麦克风，再重新开始语音。"
            )
            self.runtime.notify()

    @property
    def active(self):
        return not self._closed and self._connection not in {"off", "failed"}

    @property
    def canSendText(self):
        return (
            self._connection == "active"
            and self._muted
            and self._input == "idle"
            and not self._microphone_busy
            and not self.runtime.operation_busy
        )

    @property
    def canRetryInput(self):
        return self.hasPendingInput and not self._paused_input

    @property
    def hasPendingInput(self) -> bool:
        return (
            self._retained is not None
            and self._connection == "active"
            and self._muted
            and not self._microphone_busy
            and self._input == "idle"
        )

    @property
    def canSendPausedInput(self) -> bool:
        return self.hasPendingInput and self._paused_input

    def start(self):
        if (
            self._closed
            or self.active
            or self.preparation.snapshot.active
            or self.runtime.voice_pending
            or not self.runtime.session_active
        ):
            return
        self.preparation.clear_status()
        self.runtime.suspend_preflight()
        self._id = uuid4().hex
        self.runtime.request_permission(self._start_permitted, starting=True)

    def _start_permitted(self):
        if not self.preparation.environment_ready or not self.preparation.assets_ready:
            self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "连续语音组件尚未准备，请前往设置 → 音频设备。"
            )
            self.runtime.notify()
            return
        self._reconnects = 0
        self._connect()

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
            if self.runtime.bridge:
                self.runtime.bridge.close()
                self.runtime.bridge.deleteLater()
            self.runtime.bridge = self.runtime.new_bridge()
            config = self.runtime.bridge.formats()
            config.update(
                cache=str(self.runtime.root / "sfu"),
                vad=str(self.runtime.vad()),
                pause_ms=int(self.runtime.pause_ms),
            )
        except Exception:
            self._connection = "failed"
            self._error = QCoreApplication.translate(
                "Desktop", "音频设备不可用，请选择麦克风和播放设备后重试。"
            )
            self.runtime.notify()
            return
        self.runtime.process = self.runtime.create_process(identity)
        process = self.runtime.process
        stt, tts = self.runtime.route("stt"), self.runtime.route("tts")
        language = self.runtime.language()
        speak = self.runtime.speak_enabled()
        self.runtime.runner = ContinuousConversation(
            self.runtime.workbench,
            process,
            lambda kind, generation, value: self.runtime.emit(identity, kind, value, generation),
        )
        self.runtime.notify()

        self._connection_job = self.runtime.post(
            partial(
                connect_call,
                identity,
                process,
                stt,
                tts,
                language,
                speak,
                resume,
                config,
                self.runtime.root,
                self.runtime.emit,
                self.current,
            )
        )

    def muteMicrophone(self):
        self._mute_microphone(preserve=True)

    def _mute_microphone(self, *, preserve: bool = False) -> None:
        if self._connection != "active" or (preserve and (self._muted or self._microphone_busy)):
            return
        # Submit closes before stopping the device or awaiting inference cleanup.
        runner, process, identity = self.runtime.runner, self.runtime.process, self._id
        runner.input_allowed = False
        flush = getattr(self.runtime.bridge, "flush_capture", None)
        if preserve and flush:
            flush()
            if self._muted or self._connection != "active":
                return  # Flushing exposed an input gap/device fault.
        if preserve:
            self._pause_source = self.runtime.source()
            self._pause_id = uuid4().hex
        pause_id = self._pause_id
        self._muted, self._input = True, "idle"
        self._paused_input, self._microphone_busy = preserve, preserve
        if not preserve:
            self._retained = None
            self._pause_id = ""
        self.runtime.bridge.mute()
        self._notice = (
            QCoreApplication.translate("Desktop", "正在暂停麦克风并保留未发送的语音…")
            if preserve
            else QCoreApplication.translate("Desktop", "麦克风已暂停，可发送文字。")
        )

        self.runtime.post(
            partial(pause_call, runner, process, identity, preserve, pause_id, self.runtime.emit)
        )
        self.runtime.notify()

    def resumeMicrophone(self):
        if self._connection != "active" or not self._muted or self._microphone_busy:
            return
        self.runtime.request_permission(self._resume_permitted)

    def _resume_permitted(self):
        if self._rebuild:
            self._restart(resume=True)
            return
        self._notice = ""
        preserve = self._paused_input
        if not preserve:
            self._retained = None
        self._microphone_busy = True
        identity, process = self._id, self.runtime.process

        self.runtime.post(partial(resume_call, process, identity, preserve, self.runtime.emit))
        self.runtime.notify()

    def discardInput(self) -> None:
        if not self.hasPendingInput:
            return
        runner, process, identity = self.runtime.runner, self.runtime.process, self._id
        self._microphone_busy = True
        self._pause_id = ""
        self._retained = None
        self._sources.clear()
        self._error = ""
        self.runtime.notify()

        self.runtime.post(partial(discard_call, runner, process, identity, self.runtime.emit))

    def sendPausedInput(self) -> None:
        if not self.canSendPausedInput:
            return
        header, data, source = self._retained
        self._paused_input = False
        self._pause_id = ""
        self._input = "recognizing"
        runner, process, identity = self.runtime.runner, self.runtime.process, self._id

        self.runtime.post(
            partial(
                send_paused_call, runner, process, identity, header, data, source, self.runtime.emit
            )
        )
        self.runtime.notify()

    def stop(self):
        if not self.active or self._connection == "stopping":
            return
        if self.runtime.runner:
            self.runtime.runner.input_allowed = False
        self.preparation.cancel()
        self._permission_pending = False
        self.runtime.worker.cancel_job(self._connection_job)
        self._id = uuid4().hex
        identity = self._id
        self._connection, self._muted = "stopping", True
        self._input = self._output = "idle"
        self._reply = "idle"
        self._audio_generation = ""
        if self.runtime.bridge:
            self.runtime.bridge.close()
        self._retained = None
        self._microphone_busy, self._paused_input = False, False
        self._pause_id = ""
        self._pause_source = None
        self._sources.clear()
        self._presentation_token = self.runtime.new_token(identity + ":stop")
        self.runtime.present(ConversationEvent("begin", self._presentation_token))
        self.runtime.notify()

        async def stop():
            await self.aclose()
            self.runtime.emit(identity, "stopped")

        self.runtime.post(stop)

    async def aclose(self):
        await self.runtime.aclose()

    def stopReply(self):
        if not self.runtime.runner:
            return
        self.runtime.bridge.stop_output()
        self._audio_generation = ""
        self._output = "idle"
        runner = self.runtime.runner
        self.runtime.post(lambda: runner.interrupt("user_stopped"))
        self.runtime.notify()

    def stop_speech(self):
        if self.runtime.runner:
            self.runtime.bridge.stop_output()
            self._audio_generation = ""
            self._output = "idle"
            runner = self.runtime.runner
            self.runtime.post(runner.stop_speech)
            self.runtime.notify()

    def send_text(self, text, *, retry_turn=None, speech_only=False):
        if not self.canSendText or not (text.strip() or retry_turn):
            return

        stt, tts = self.runtime.route("stt"), self.runtime.route("tts")
        speak = self.runtime.speak_enabled() or speech_only
        source = self.runtime.source()
        self._sent_revision = (
            (self.runtime.draft_revision, self.runtime.draft)
            if not retry_turn and text == self.runtime.draft
            else None
        )
        runner = self.runtime.runner
        self.runtime.post(
            lambda: runner.send_text(
                text, source, stt, tts, speak, retry_turn=retry_turn, speech_only=speech_only
            )
        )

    def retryInput(self):
        if self.canRetryInput:
            header, data, source = self._retained
            self._submit_input(header, data, source, retry=True)

    def _submit_input(self, header, data, source, *, retry=False):

        stt, tts = self.runtime.route("stt"), self.runtime.route("tts")
        self._retained = (header, data, source)
        self._input, self._error = "recognizing", ""
        if self._muted:
            self._notice = ""
        runner, speak = self.runtime.runner, self.runtime.speak_enabled()
        self.runtime.post(
            lambda: runner.receive(header, data, source, stt, tts, speak, manual_retry=retry)
        )
        self.runtime.notify()

    def output_drained(self, generation):
        if generation != self._audio_generation or not self.runtime.runner:
            return
        self._audio_generation = ""
        self.runtime.bridge.stop_output()
        self._output = "idle"
        runner = self.runtime.runner
        turn = self._turn
        if turn:
            self.runtime.post(lambda: self._delivery(runner, turn))
        self.runtime.notify()

    async def _delivery(self, runner, turn):
        runner.workbench.record_speech_delivery(turn, "completed", runner.segment_count - 1)
        runner.audio_started = False

    def device_fault(self, code):
        if self._connection != "active":
            return
        self.runtime.record_fault(code)
        output_fault = code in {"audio_output_failed", "output_overflow"}
        if output_fault:
            self.stop_speech()
        else:
            self._rebuild = code in {"audio_devices_changed", "microphone_failed"}
            self._mute_microphone()
            self.stopReply()
        self._error = call_device_error(code)
        if output_fault and self._turn:
            self.runtime.speech_errors[self._turn] = self._error
        if code == "microphone_failed":
            self._permission_error = True
        self.runtime.notify()

    def device_changed(self):
        if self.active and self._connection != "active":
            self._rebuild = True
        self.device_fault("audio_devices_changed")

    def _restart(self, *, resume=False):
        old_runner, old_process = self.runtime.runner, self.runtime.process
        if old_runner:
            old_runner.input_allowed = False
        self._id = uuid4().hex
        identity = self._id
        self._muted, self._connection = True, "reconnecting"
        self.runtime.bridge.close()
        self._rebuild = False
        self.runtime.notify()

        self.runtime.post(
            partial(restart_call, old_runner, old_process, identity, resume, self.runtime.emit)
        )

    def close(self):
        self._closed = True
        self._connection, self._input, self._output, self._reply = "off", "idle", "idle", "idle"
        self._muted, self._audio_generation = True, ""
        if self.runtime.runner:
            self.runtime.runner.input_allowed = False
        self.preparation.cancel()
        self._id = ""
        self._retained = None
        self._pause_source = None
        self._pause_id = ""
        self._sources.clear()
        if self.runtime.bridge:
            self.runtime.bridge.close()

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
            self.runtime.bridge.enqueue(header["generation"], data)
            # Device faults may synchronously invalidate the output generation.
            if header["generation"] == self._audio_generation and self._output != "playing":
                self._output = "playing"
                self.runtime.notify()
            # PCM frames are not UI changes. In particular, do not reevaluate
            # hidden settings, device lists and installation plans at 50 Hz.
            return False
        elif event == "input_paused":
            if self._muted and header.get("pause_id") == self._pause_id:
                key = header["utterance"]
                source = self._sources.setdefault(key, self._pause_source)
                self._retained = (header, data, source)
        elif event == "output_drained":
            self.runtime.bridge.finish_output(header["generation"])
        elif event in {"near_speech", "input_started"}:
            self.runtime.bridge.stop_output()
            self._audio_generation = ""
            runner = self.runtime.runner
            if event == "input_started":
                self._input = "speaking"
                self.runtime.post(
                    lambda: runner.input_started(header["utterance"], header["revision"])
                )
            else:
                self.runtime.post(lambda: runner.interrupt("user_interruption"))
        elif event == "utterance" and not self._muted:
            key = header["utterance"]
            self._sources.setdefault(key, self.runtime.source())
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
            self.device_fault(event)
        return True

    def _call_connection_stage(self, identity, kind, generation, value):
        self._connection_stage = value
        return True

    def _call_connected(self, identity, kind, generation, value):
        resume, metrics = value
        self.runtime.timings.update(metrics)
        self._connection = "active"
        try:
            self.runtime.bridge.open()
            if resume and not self._rebuild:
                self.resumeMicrophone()
            else:
                self._notice = QCoreApplication.translate("Desktop", "语音已连接，请点击恢复监听。")
        except Exception:
            self.device_fault("microphone_failed")
        return True

    def _call_resume_device(self, identity, kind, generation, value):
        try:
            self._mic_generation = value.get("mic_generation", self._mic_generation + 1)
            self.runtime.runner.input_allowed = True
            self.runtime.bridge.resume()
            self._muted, self._notice = False, ""
            self._microphone_busy, self._paused_input = False, False
            self._pause_id = ""
            self._permission_error = False
            self._error = ""
        except Exception:
            self.device_fault("microphone_failed")
        return True

    def _call_pause_device(self, identity, kind, generation, value):
        pause_id, result = value
        if pause_id == self._pause_id:
            self._microphone_busy = False
            self._input = "idle"
            if not result.get("has_input"):
                self._retained = None
            self._notice = (
                QCoreApplication.translate(
                    "Desktop", "麦克风已暂停；未发送的语音已保留，可继续说或发送已说内容。"
                )
                if self._retained
                else QCoreApplication.translate(
                    "Desktop", "麦克风已暂停，可发送文字；恢复后继续监听。"
                )
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
        self._error = QCoreApplication.translate(
            "Desktop", "麦克风暂停或恢复未完成，请停止语音后重新连接。"
        )
        return True

    def _call_submit_paused(self, identity, kind, generation, value):
        self._submit_input(*value, retry=True)
        return True

    def _call_restart(self, identity, kind, generation, value):
        self._connect(resume=value, reconnect=True)
        return True

    def _call_failed(self, identity, kind, generation, value):
        self.runtime.components_changed()
        self.preparation.refresh_storage()
        code = value.get("code") if isinstance(value, dict) else value
        stage = value.get("stage") if isinstance(value, dict) else self._connection_stage
        self.runtime.record_fault(code, stage=stage)
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
        self.runtime.components_changed()
        self.preparation.refresh_storage()
        self._connection = "off"
        self.runtime.present(ConversationEvent("refresh", self._presentation_token))
        return True

    def _turn_recognizing(self, identity, kind, generation, value):
        self._input = "recognizing"
        return True

    def _turn_input_started(self, identity, kind, generation, value):
        self._input = "speaking"
        return True

    def _turn_generating(self, identity, kind, generation, value):
        self.runtime.timings = {}
        self._attribution = ""
        self._input, self._reply = "idle", "generating"
        self._output = "synthesizing" if self.runtime.speak_enabled() else "idle"
        self._presentation_token = self.runtime.new_token(f"{identity}:{generation}")
        self.runtime.present(ConversationEvent("begin", self._presentation_token))
        return True

    def _turn_confirmed(self, identity, kind, generation, value):
        turn, session = value
        self._turn = turn.id
        self._presentation_token = self.runtime.confirm(
            self._presentation_token,
            turn.id,
            session,
            self._sent_revision,
        )
        self._input = "idle"
        if self._retained:
            key = self._retained[0]["utterance"]
            if turn.request_id == f"voice:{self.runtime.process.id}:{key}":
                self._retained = None
                self._sources.pop(key, None)
        self._sent_revision = None
        return True

    def _turn_delta(self, identity, kind, generation, value):
        self.runtime.present(ConversationEvent("delta", self._presentation_token, text=value))
        return True

    def _turn_attribution(self, identity, kind, generation, value):
        self._attribution = value
        return True

    def _turn_output_begin(self, identity, kind, generation, value):
        self._audio_generation = value
        try:
            self.runtime.bridge.begin_output(value)
        except Exception:
            self.stop_speech()
            self._error = QCoreApplication.translate("Desktop", "朗读未能播放，文字回复继续生成。")
        return True

    def _turn_text_completed(self, identity, kind, generation, value):
        self._reply = "idle"
        self.runtime.present(ConversationEvent("complete", self._presentation_token, value.session))
        return True

    def _turn_result(self, identity, kind, generation, value):
        self._reply = "idle"
        result, metrics = value
        self.runtime.timings.update(metrics)
        self._output = "draining" if self._audio_generation else "idle"
        if result.text_status == "failed":
            self.runtime.turn_errors[result.turn_id] = QCoreApplication.translate(
                "Desktop", "回复未完成，已发送的发言已保留。"
            )
        elif result.speech_status == "failed":
            self.runtime.record_fault(result.error_code, stage=result.error_stage)
            self.runtime.speech_error_codes[result.turn_id] = result.error_code
            self.runtime.speech_errors[result.turn_id] = (
                speech_error_text(
                    result.error_code or "speech_synthesis_failed",
                    "tts",
                    self.runtime.language(),
                )
                if result.error_stage == "tts"
                else QCoreApplication.translate(
                    "Desktop", "朗读音频未能送达播放设备，文字回复已保留；可重试朗读。"
                )
            )
        self.runtime.present(
            ConversationEvent("settled", self._presentation_token, history_changed=True)
        )
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
            self.runtime.present(ConversationEvent("interrupt", self._presentation_token))
        return True

    def _turn_reply_failed(self, identity, kind, generation, value):
        self.runtime.present(ConversationEvent("fail", self._presentation_token))
        self._reply = "idle"
        self._output = "idle"
        self._error = QCoreApplication.translate("Desktop", "回复未完成，已发送的发言已保留。")
        return True

    def _turn_interruption_completed(self, identity, kind, generation, value):
        self.runtime.present(ConversationEvent("refresh", self._presentation_token))
        return True

    def _apply_turn_event(self, identity, kind, generation, value):
        if (
            self._muted
            and self._paused_input
            and kind in {"recognizing", "input_started", "recognition_failed"}
        ):
            return False
        self._generation = generation
        if kind == "recognizing":
            return self._turn_recognizing(identity, kind, generation, value)
        elif kind == "input_started":
            return self._turn_input_started(identity, kind, generation, value)
        elif kind == "generating":
            return self._turn_generating(identity, kind, generation, value)
        elif kind == "confirmed":
            return self._turn_confirmed(identity, kind, generation, value)
        elif kind == "delta":
            return self._turn_delta(identity, kind, generation, value)
        elif kind == "attribution":
            return self._turn_attribution(identity, kind, generation, value)
        elif kind == "output_begin":
            return self._turn_output_begin(identity, kind, generation, value)
        elif kind == "text_completed":
            return self._turn_text_completed(identity, kind, generation, value)
        elif kind == "result":
            return self._turn_result(identity, kind, generation, value)
        elif kind == "recognition_failed":
            return self._turn_recognition_failed(identity, kind, generation, value)
        elif kind in {"interrupted", "speech_stopped"}:
            return self._turn_interrupted(identity, kind, generation, value)
        elif kind == "reply_failed":
            return self._turn_reply_failed(identity, kind, generation, value)
        elif kind == "interruption_completed":
            return self._turn_interruption_completed(identity, kind, generation, value)
        return True

    def handle(self, event: CallEvent) -> None:
        identity, kind, generation, value = (
            event.identity,
            event.kind,
            event.generation,
            event.value,
        )
        if not self.current(identity):
            return
        handler = CONNECTION_EVENTS.get(kind)
        if handler is not None:
            if not getattr(self, handler)(identity, kind, generation, value):
                return
        elif generation < self._generation or not self._apply_turn_event(
            identity, kind, generation, value
        ):
            return
        self.runtime.notify()
