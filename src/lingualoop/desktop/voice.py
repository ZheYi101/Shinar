"""Qt bridge for automatic turn-based speech; inference stays on the shared worker."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from time import perf_counter, time
from uuid import uuid4
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Property, QCoreApplication, Signal, Slot, Qt, QTimer

from lingualoop.application.voice_session import VoiceSessionCoordinator
from lingualoop.core.voice import SpeechSegment, VoiceTurnResult
from lingualoop.core.domain import Message

if TYPE_CHECKING:
    from lingualoop.desktop.viewmodel import LearningViewModel


class _SpeechRoute:
    """Capture routing once on the GUI thread, bind the model on the worker."""

    def __init__(self, vm, task: str) -> None:
        local = vm._local_speech
        self.backend = (
            local.provider(task) if local and local.enabled(task) else getattr(vm, "_" + task)
        )
        self._bound = None
        self._error = None

    async def bind(self, language: str):
        if self._error:
            raise self._error
        if self._bound is not None:
            return self._bound
        if self.backend is None:
            raise ValueError("speech_service_unavailable")
        bind = getattr(self.backend, "bind", None)
        self._bound = await bind(language) if bind else self.backend
        return self._bound

    async def prepare(self, language: str) -> None:
        try:
            await self.bind(language)
        except Exception as exc:
            self._error = exc


class DesktopVoiceController(QObject):
    changed = Signal()
    _eventReceived = Signal(str, str, str, object)

    def __init__(self, vm: LearningViewModel) -> None:
        super().__init__(vm)
        self.vm, self.worker, self.audio = vm, vm._worker, vm._audio
        self._closed = False
        self._job = ""
        self._session = ""
        self._turn = ""
        self._kind = ""
        self._done = False
        self._muted = False
        self._coordinator = None
        self._recognition = "idle"
        self._reply = "idle"
        self._speech = "idle"
        self._recording = b""
        self._recording_id = ""
        self._source = None
        self._transcript = None
        self._transcription_error = ""
        self._turn_errors = {}
        self._speech_errors = {}
        self._pending_audio = []
        self._cache = []
        self._cache_turn = ""
        self._cache_complete = False
        self._cache_bytes = 0
        self._cache_overflow = False
        self._replaying = False
        self._started = 0.0
        self.timings: dict[str, float] = {}
        self._sent_revision = None
        from .continuous_voice import ContinuousVoiceController
        self.call = ContinuousVoiceController(self)
        self._eventReceived.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.worker.jobCompleted.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self._lease_timer = QTimer(self)
        self._lease_timer.setInterval(1000)
        self._lease_timer.timeout.connect(self._refresh_recovery)
        vm.sessionChanged.connect(self.restore)
        if self.audio:
            self.audio.recorded.connect(self._recorded)
            self.audio.errorOccurred.connect(self._forward_audio_error)
            self.audio.durationChanged.connect(self._duration)
            self.audio.devicesChanged.connect(vm.uiChanged)
            self.audio.queueChanged.connect(self._queue_changed, Qt.ConnectionType.QueuedConnection)
            self.audio.segmentStarted.connect(
                self._segment_started, Qt.ConnectionType.QueuedConnection
            )

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return bool(self._job or self._recognition == "recording" or self.call.active)

    @Property(QObject, constant=True)
    def continuous(self):
        return self.call

    @Property(bool, notify=changed)
    def canSendText(self):
        return self.call.canSendText if self.call.active else not self.active and not self.vm._busy

    @Property(str, notify=changed)
    def recognitionState(self) -> str:
        return self.call.inputState if self.call.active else self._recognition

    @Property(str, notify=changed)
    def replyState(self) -> str:
        if self.call.active:
            return self.call.replyState
        return self._reply

    @Property(str, notify=changed)
    def speechState(self) -> str:
        return self.call.outputState if self.call.active else self._speech

    @Property(bool, notify=changed)
    def canStopSpeech(self) -> bool:
        if self.call.active:
            return self.call.outputState in {"synthesizing", "playing", "draining"}
        return self._speech in {"synthesizing", "playing", "draining"} and not self._muted

    @Property(str, notify=changed)
    def transcriptionError(self) -> str:
        return self._transcription_error

    @Property(str, notify=changed)
    def unsentTranscript(self) -> str:
        return self._transcript.text if self._transcript and self._transcription_error else ""

    @Property(bool, notify=changed)
    def canRetryTranscription(self) -> bool:
        return bool(self._transcription_error and (self._recording or self._transcript))

    @Property(str, notify=changed)
    def statusText(self) -> str:
        if self.call.active:
            return self.call.statusText
        if self._recognition == "recording":
            return QCoreApplication.translate("Desktop", "正在录音 · 结束后自动发送")
        if self._recognition == "transcribing":
            return QCoreApplication.translate("Desktop", "正在识别发言…")
        if self._reply == "generating" and self._speech in {"playing", "draining"}:
            return QCoreApplication.translate("Desktop", "正在回复并朗读…")
        if self._reply == "generating":
            return QCoreApplication.translate("Desktop", "正在回复…")
        if self._speech in {"playing", "draining"}:
            return QCoreApplication.translate("Desktop", "正在朗读…")
        if self._speech == "synthesizing":
            return QCoreApplication.translate("Desktop", "正在生成语音…")
        return ""

    @property
    def legacy_state(self) -> str:
        if self._recognition != "idle":
            return self._recognition
        if self._reply == "generating":
            return "generating"
        if self._speech in {"playing", "draining"}:
            return "playing"
        return "synthesizing" if self._speech == "synthesizing" else "idle"

    def _notify(self) -> None:
        if self._closed:
            return
        self.changed.emit()
        self.vm.uiChanged.emit()
        self.vm.busyChanged.emit()

    def _session_id(self) -> str:
        session = self.vm._workbench.session
        return session.id if session else ""

    def _can_start(self) -> bool:
        return not self._closed and not self.active and not self.vm._busy

    def _speak_enabled(self) -> bool:
        return bool(
            self.audio and self.vm.preferences.autoReadReplies and self.vm._speech_available("tts")
        )

    @Slot()
    def startRecording(self) -> None:
        if not self._can_start() or not self.vm.sessionActive:
            return
        if not self.audio or not self.vm._speech_available("stt"):
            self._transcription_error = QCoreApplication.translate(
                "Desktop", "语音识别尚未配置，请查看设置；文字输入仍可使用。"
            )
            self._notify()
            return
        self.discardRecording()
        self._session = self._session_id()
        self._recording_id = "recording-" + uuid4().hex
        self.vm._recording_seconds = 0
        self._recognition = "recording"
        self.audio.start_recording()
        self._notify()

    @Slot()
    def stopRecording(self) -> None:
        if self._recognition == "recording" and self.audio:
            # Also captured in _recorded for the recorder's automatic 60s stop.
            self._source = self.vm.source_context_provider()
            self.audio.stop_recording()

    @Slot()
    def cancelRecording(self) -> None:
        if self._recognition != "recording":
            return
        self._recognition = "idle"
        if self.audio:
            self.audio.cancel_recording()
        self.discardRecording()

    @Slot()
    def discardRecording(self) -> None:
        if self._job:
            return
        self._recording = b""
        self._transcript = None
        self._recording_id = ""
        self._source = None
        self._transcription_error = ""
        self._notify()

    @Slot()
    def copyTranscript(self) -> None:
        if self._transcript:
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(self._transcript.text)

    @Slot(bytes)
    def _recorded(self, audio: bytes) -> None:
        if self._closed or self._recognition != "recording" or self._session != self._session_id():
            return
        self._recording = audio
        self._source = self.vm.source_context_provider()
        self._recognition = "idle"
        self.retryTranscription()

    @Slot()
    def retryTranscription(self) -> None:
        if not self._can_start() or not (self._recording or self._transcript):
            return
        self._recognition = "transcribing"
        self._transcription_error = ""
        audio, source, transcript, request_id = (
            self._recording,
            self._source,
            self._transcript,
            self._recording_id,
        )

        async def submit(coordinator):
            draft = transcript or await coordinator.recognize(audio, source)
            # A retained draft belongs to the previous short-lived coordinator.
            if transcript:
                return await coordinator.submit_text(
                    draft.text,
                    request_id=request_id,
                    source_context=draft.source_context,
                    confirmation_kind="automatic_transcript",
                    speak=self._job_speak and not self._muted,
                )
            self._emit("recognized", draft)
            return await coordinator.submit_confirmed(
                draft,
                request_id=request_id,
                confirmation_kind="automatic_transcript",
                speak=self._job_speak and not self._muted,
            )

        self._launch("recording", submit)

    def send_text(self, text: str) -> None:
        if self.call.active:
            self.call.send_text(text)
            return
        if not self._can_start() or not self.vm.sessionActive or not text.strip():
            return
        source = self.vm.source_context_provider()
        request_id = "text-" + uuid4().hex
        self._sent_revision = (
            (self.vm._draft_revision, self.vm.draft) if text == self.vm.draft else None
        )

        async def submit(coordinator):
            return await coordinator.submit_text(
                text,
                request_id=request_id,
                source_context=source,
                speak=self._job_speak and not self._muted,
            )

        self._launch("text", submit)

    @Slot(str)
    def retryReply(self, turn_id: str) -> None:
        if self.call.active:
            self.call.send_text("", retry_turn=turn_id)
            return
        if not self._can_start():
            return
        self._turn_errors.pop(turn_id, None)
        self._turn = turn_id
        self._launch(
            "retry", lambda c: c.retry_reply(turn_id, speak=self._job_speak and not self._muted)
        )

    @Slot(str)
    def speakTurn(self, turn_id: str) -> None:
        if self.call.active:
            self.call.send_text("", retry_turn=turn_id, speech_only=True)
            return
        if not self._can_start() or not self.vm._speech_available("tts"):
            return
        self._turn = turn_id
        self._speech_errors.pop(turn_id, None)
        cached = list(self._cache) if self._cache_complete and self._cache_turn == turn_id else None

        async def speak(coordinator):
            if cached:
                for segment in cached:
                    await coordinator.on_audio(segment)
                return VoiceTurnResult(turn_id, None, "completed", "completed", len(cached))
            if not turn_id.startswith("legacy:"):
                return await coordinator.retry_speech(turn_id)
            message = next(m for m in self.vm._workbench.session.messages if m.id == turn_id[7:])
            backend = await coordinator._bind(coordinator.tts, coordinator._language())
            audio = await backend.synthesize(message.content)
            await coordinator.on_audio(SpeechSegment.from_wav(turn_id, 0, message.content, audio))
            return VoiceTurnResult(turn_id, None, "completed", "completed", 1)

        self._launch("speech", speak, speak=True)

    def speak_latest(self) -> None:
        message = next((m for m in reversed(self.vm._messages) if m["role"] == "assistant"), None)
        if message:
            self.speakTurn(message.get("turnId") or "legacy:" + message["id"])

    def _launch(self, kind, operation, *, speak=None) -> None:
        self._job = "voice-" + uuid4().hex
        self._session = self._session_id()
        self._kind, self._done, self._muted = kind, False, False
        self._started = perf_counter()
        self.timings = {}
        if kind in {"text", "recording"}:
            self._turn = ""
        self._job_speak = self._speak_enabled() if speak is None else speak
        self._reply = "idle" if kind in {"recording", "speech"} else "generating"
        self._speech = "synthesizing" if self._job_speak else "idle"
        self.vm._streaming_text = ""
        self.vm._pending_user_text = ""
        self.vm._response_timing = ""
        self.vm._error = ""
        self._replaying = (
            kind == "speech" and self._cache_complete and self._cache_turn == self._turn
        )
        if not self._replaying:
            self._cache, self._cache_bytes, self._cache_complete, self._cache_overflow = (
                [],
                0,
                False,
                False,
            )
            self._cache_turn = self._turn
        job_id, session_id = self._job, self._session
        stt, tts = _SpeechRoute(self.vm, "stt"), _SpeechRoute(self.vm, "tts")
        language = self.vm._speech_language()
        should_speak = self._job_speak
        if self.audio:
            self.audio.begin_playback(job_id)

        def emit(kind, payload):
            self._eventReceived.emit(job_id, session_id, kind, payload)

        async def consume(segment):
            accepted = Future()
            emit("audio", (segment, accepted))
            await asyncio.wrap_future(accepted)

        def confirmed(turn):
            emit("confirmed", (turn, self.vm._workbench.session))

        coordinator = VoiceSessionCoordinator(
            self.vm._workbench,
            stt=stt,
            tts=tts,
            on_audio=consume,
            on_text_delta=lambda delta: emit("delta", delta),
            on_turn_confirmed=confirmed,
            on_text_completed=lambda result: emit("textCompleted", result),
        )
        self._coordinator = coordinator

        async def run():
            try:
                if should_speak:
                    await tts.prepare(language)
                if kind == "recording":
                    await stt.prepare(language)
                if kind == "speech" and self._muted:
                    return VoiceTurnResult(self._turn, None, "completed", "stopped")
                return await operation(coordinator)
            finally:
                await coordinator.aclose()

        self.worker.submit_job(job_id, run)
        self._notify()

    def _emit(self, kind, payload) -> None:
        self._eventReceived.emit(self._job, self._session, kind, payload)

    @Slot(str, str, str, object)
    def _event(self, job_id, session_id, kind, payload) -> None:
        if kind == "audioError":
            if (
                not self._closed
                and job_id == (self._job or self._recording_id)
                and session_id == self._session_id()
            ):
                self._audio_error(payload)
            return
        if self._closed or job_id != self._job or session_id != self._session_id():
            if kind == "audio" and not payload[1].done():
                payload[1].cancel()
            return
        if kind == "recognized":
            self._transcript = payload
            self.timings["recognition_completed"] = (perf_counter() - self._started) * 1000
        elif kind == "confirmed":
            turn, session = payload
            self._turn = turn.id
            self._cache_turn = turn.id
            self._recognition, self._reply = "idle", "generating"
            self._transcript, self._recording = None, b""
            if self._kind == "text" and self._sent_revision == (
                self.vm._draft_revision,
                self.vm.draft,
            ):
                self.vm.draft = ""
            self.vm._refresh_session_state(session)
            self.vm.messagesChanged.emit()
            self.vm.historyChanged.emit()
        elif kind == "delta":
            if self._kind != "speech":
                self.vm._streaming_text += payload
                self.timings.setdefault("ui_first_delta", (perf_counter() - self._started) * 1000)
        elif kind == "textCompleted":
            self._reply = "idle"
            self.vm._streaming_text = ""
            self.timings["ui_text_completed"] = (perf_counter() - self._started) * 1000
            self.vm._refresh_session_state(payload.session)
            self.vm.messagesChanged.emit()
        elif kind == "audio":
            self._pending_audio.append(payload)
            self._queue_changed()
        self._notify()

    @Slot()
    def _queue_changed(self) -> None:
        if self._closed or not self._job:
            return
        while self._pending_audio:
            segment, accepted = self._pending_audio[0]
            if accepted.done():
                self._pending_audio.pop(0)
                continue
            if self._muted or not self.audio:
                accepted.set_exception(RuntimeError("audio_output_stopped"))
                self._pending_audio.pop(0)
                continue
            try:
                if not self.audio.enqueue(segment, self._job):
                    break
            except Exception:
                accepted.set_exception(RuntimeError("audio_output_failed"))
                self._pending_audio.pop(0)
                self._speech_errors[self._turn] = QCoreApplication.translate(
                    "Desktop", "播放失败，文字回复已保留。"
                )
                self._stop_speech(user=False)
                break
            self._pending_audio.pop(0)
            if self._replaying:
                pass
            elif self._cache_bytes + len(segment.audio) <= 24 * 1024**2:
                self._cache.append(segment)
                self._cache_bytes += len(segment.audio)
            else:
                self._cache_overflow = True
            accepted.set_result(None)
        if self._done and self.audio and not self.audio.queued_count:
            self._finish()

    @Slot(object)
    def _segment_started(self, segment) -> None:
        if self._closed or self._muted or segment.turn_id != self._turn:
            return
        self._speech = "playing"
        self.timings.setdefault("player_started", (perf_counter() - self._started) * 1000)
        self._notify()

    @Slot(str, object, str)
    def _completed(self, job_id, result, error) -> None:
        self.worker.forget_job(job_id)
        if self._closed or job_id != self._job or self._session != self._session_id():
            return
        self._done = True
        self._reply = self._recognition = "idle"
        self.vm._streaming_text = ""
        if error:
            if self._kind == "recording" and not self._turn:
                self._transcription_error = QCoreApplication.translate(
                    "Desktop", "发言未发送，请重试识别或改用文字补充。"
                )
                if "4000" in error:
                    self._transcription_error = QCoreApplication.translate(
                        "Desktop", "识别文字过长，未发送。请分段用文字补充或重新录音。"
                    )
            elif self._kind == "speech":
                self._speech_errors[self._turn] = QCoreApplication.translate(
                    "Desktop", "朗读未完成，文字回复已保留。"
                )
            elif not self._turn:
                self.vm._on_operation_failed(
                    QCoreApplication.translate("Desktop", "发言未发送，请检查长度后重试。")
                )
            else:
                self._turn_errors[self._turn] = QCoreApplication.translate(
                    "Desktop", "回复未完成，已发送的发言已保留。"
                )
            self._stop_speech(user=False)
        else:
            self.timings.update(result.timings_ms)
            if result.text_status == "failed":
                self._turn_errors[result.turn_id] = {
                    "reply_http_402": QCoreApplication.translate(
                        "Desktop",
                        "模型服务余额不足（HTTP 402）。已发送的发言已保留，补充余额后可重试。",
                    ),
                    "reply_http_401": QCoreApplication.translate(
                        "Desktop", "模型服务认证失败（HTTP 401）。请检查本地 API Key 后重试。"
                    ),
                    "reply_http_429": QCoreApplication.translate(
                        "Desktop", "模型服务暂时限流（HTTP 429）。已发送的发言已保留，请稍后重试。"
                    ),
                }.get(
                    result.error_code,
                    QCoreApplication.translate("Desktop", "回复未完成，已发送的发言已保留。"),
                )
                self._stop_speech(user=False)
            else:
                self._turn_errors.pop(result.turn_id, None)
                if result.speech_status == "failed" and not self._muted:
                    self._speech_errors[result.turn_id] = QCoreApplication.translate(
                        "Desktop", "朗读未完成，文字回复已保留。"
                    )
                if not self._replaying:
                    self._cache_complete = (
                        result.speech_status == "completed" and not self._cache_overflow
                    )
            parts = []
            first = self.timings.get("provider_ttft_ms", self.timings.get("text_first_delta"))
            full = self.timings.get("provider_total_ms", self.timings.get("text_completed"))
            if first is not None:
                parts.append(
                    QCoreApplication.translate("Desktop", "首字 {value0:.2f} 秒").format(
                        value0=first / 1000
                    )
                )
            if full is not None:
                parts.append(
                    QCoreApplication.translate("Desktop", "完整回复 {value0:.2f} 秒").format(
                        value0=full / 1000
                    )
                )
            self.vm._response_timing = " · ".join(parts)
        self.vm._refresh_session_state()
        self.vm._restore_last_reply()
        self.vm.messagesChanged.emit()
        self.vm.historyChanged.emit()
        self.vm.messageSent.emit()
        if not self.audio or not self.audio.queued_count:
            self._finish()
        else:
            self._speech = "draining"
            self._notify()

    def _finish(self) -> None:
        self._job = ""
        self._coordinator = None
        self._speech = "idle"
        self.vm._refresh_session_state()
        self.vm.messagesChanged.emit()
        self._notify()

    @Slot()
    def stopPlayback(self) -> None:
        if self.call.active:
            self.call.stop_speech()
            return
        self._stop_speech(user=True)

    def _stop_speech(self, *, user: bool) -> None:
        self._muted = True
        self._speech = "idle"
        pending, self._pending_audio = self._pending_audio, []
        for _, accepted in pending:
            if not accepted.done():
                accepted.cancel()
        coordinator, turn_id = self._coordinator, self._turn
        if coordinator and turn_id and not self._done and not self._closed:
            self.worker.submit_job(
                "speech-stop-" + uuid4().hex, lambda: coordinator.stop_speech(turn_id)
            )
        if self.audio:
            self.audio.stop_playback()
        if user:
            self._speech_errors.pop(turn_id, None)
        self._notify()

    @Slot(str)
    def _forward_audio_error(self, message: str) -> None:
        self._eventReceived.emit(
            self._job or self._recording_id, self._session, "audioError", message
        )

    @Slot(int)
    def _duration(self, seconds: int) -> None:
        self.vm._recording_seconds = seconds
        self._notify()

    @Slot(str)
    def _audio_error(self, message: str) -> None:
        if self._recognition == "recording":
            self._recognition = "idle"
            self._transcription_error = message
        else:
            self._speech_errors[self._turn] = message
            self._stop_speech(user=False)
            self.vm._refresh_session_state()
            self.vm.messagesChanged.emit()
        self._notify()

    def turn_details(self, message: Message, turn_id: str = "") -> dict[str, object]:
        turn_id = message.metadata.get("turn_id", turn_id)
        details = {"turnId": turn_id, "replyError": "", "speechError": "", "canRetryReply": False}
        details["replyNotice"] = (QCoreApplication.translate("Desktop", "这轮回复已停止。")
                                  if message.metadata.get("reply_interrupted") else "")
        if message.metadata.get("speech_interrupted") and not details["replyNotice"]:
            details["replyNotice"] = QCoreApplication.translate("Desktop", "这条回复的朗读已停止。")
        details["speechError"] = (
            self._speech_errors.get(turn_id or "legacy:" + message.id, "")
            if message.role.value == "assistant"
            else ""
        )
        if not turn_id:
            return details
        session = self.vm._workbench.session
        # Only a trailing user message can be resumed. Completed history needs
        # no repository round trip for every bubble on every UI refresh.
        if message.role.value != "user" or session.messages[-1].id != message.id:
            return details
        try:
            turn = self.vm._workbench.get_turn(turn_id)
        except ValueError:
            return details
        pending = turn.state != "completed" and session.messages[-1].id == turn.user_message_id
        if turn.state == "cancelled":
            details["replyNotice"] = QCoreApplication.translate("Desktop", "这轮回复已停止。")
        if pending and (not self.active or self.call.canSendText):
            details["replyError"] = "" if turn.state == "cancelled" else self._turn_errors.get(turn_id) or QCoreApplication.translate(
                "Desktop", "这轮回复尚未完成。"
            )
            details["canRetryReply"] = (
                session.status.value == "active" and turn.lease_until <= time()
            )
            if not details["canRetryReply"] and turn.lease_until > time():
                details["replyError"] = QCoreApplication.translate(
                    "Desktop", "这轮回复仍被占用，稍后可重试。"
                )
                self._lease_timer.start()
        return details

    @Slot()
    def _refresh_recovery(self) -> None:
        if self.active or self._closed:
            return
        self.vm._refresh_session_state()
        self.vm.messagesChanged.emit()
        if any(m.get("canRetryReply") for m in self.vm._messages):
            self._lease_timer.stop()

    @Slot()
    def restore(self) -> None:
        if self._session != self._session_id() and not self.active:
            self.reset()
            self._session = self._session_id()

    def reset(self) -> None:
        self._stop_speech(user=False)
        self.discardRecording()
        self._cache, self._cache_complete, self._cache_bytes = [], False, 0
        self._lease_timer.stop()

    def invalidate_cache(self) -> None:
        self._cache, self._cache_complete, self._cache_bytes = [], False, 0
        self._cache_overflow = True

    def close(self) -> None:
        self.call.close()
        self._closed = True
        self._lease_timer.stop()
        self.worker.cancel_job(self._job)
        self._job = ""
        self._coordinator = None
        for _, accepted in self._pending_audio:
            accepted.cancel()
        self._pending_audio = []
