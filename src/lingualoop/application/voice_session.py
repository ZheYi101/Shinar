"""Headless, single-flight speech orchestration over the existing workbench."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter

from lingualoop.core.voice import (
    SpeechSegment,
    SpeechToTextProvider,
    TextToSpeechProvider,
    TranscriptDraft,
    VoiceTurnResult,
)
from lingualoop.core.knowledge import TurnSourceSnapshot
from lingualoop.core.conversation import ConversationTurn
from lingualoop.kernel import SessionStepResult
from .learning_workbench import LearningWorkbench
from .speech_text import SpeechTextBuffer, SpokenTextProjection

AudioConsumer = Callable[[SpeechSegment], Awaitable[None]]
LANGUAGES = {"chinese": "zh", "english": "en", "japanese": "ja"}


class VoiceSessionCoordinator:
    def __init__(
        self,
        workbench: LearningWorkbench,
        *,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        on_audio: AudioConsumer | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_turn_confirmed: Callable[[ConversationTurn], None] | None = None,
        on_text_completed: Callable[[SessionStepResult], None] | None = None,
        own_backends: bool = False,
    ) -> None:
        self.workbench = workbench
        self.stt, self.tts = stt, tts
        self.on_audio, self.on_text_delta = on_audio, on_text_delta
        self.on_turn_confirmed = on_turn_confirmed
        self.on_text_completed = on_text_completed
        self.own_backends = own_backends
        self._drafts: dict[str, TranscriptDraft] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        self._speech_tasks: dict[str, asyncio.Task] = {}
        self._stopped_speech: set[str] = set()

    async def stop_speech(self, turn_id: str) -> None:
        """Stop this turn's speech without cancelling its dialogue producer."""
        self._stopped_speech.add(turn_id)
        task = self._speech_tasks.get(turn_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _language(self) -> str:
        if self._closed:
            raise RuntimeError("voice_session_closed")
        if not self.workbench.session:
            raise RuntimeError("voice_requires_learning_session")
        value = self.workbench.session.profile.target_language.value
        return LANGUAGES.get(value, value)

    async def _bind(self, backend, language: str):
        bind = getattr(backend, "bind", None)
        return await bind(language) if bind else backend

    async def recognize(
        self, audio: bytes, source_context: TurnSourceSnapshot | None = None
    ) -> TranscriptDraft:
        language = self._language()
        session_id = self.workbench.session.id
        header = SpeechSegment.from_wav("input", 0, "", audio)
        if header.sample_rate != 16000 or header.channels != 1:
            raise ValueError("stt_requires_16khz_mono_pcm16")
        if len(audio) > 16000 * 2 * 60 + 4096:
            raise ValueError("stt_audio_too_long")
        if source_context is not None:
            source_context = self.workbench.freeze_turn_source(source_context)
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            # A transcription also owns the session snapshot while awaiting inference.
            with self.workbench.conversation_operation():
                backend = await self._bind(self.stt, language)
                text = (await backend.transcribe(audio)).strip()
                if not text:
                    raise ValueError("stt_empty_result")
                if (
                    self._closed
                    or not self.workbench.session
                    or self.workbench.session.id != session_id
                    or self._language() != language
                ):
                    raise RuntimeError("voice_session_changed")
                draft = TranscriptDraft(session_id, text, language, source_context)
                if len(self._drafts) >= 16:
                    self._drafts.pop(next(iter(self._drafts)))
                self._drafts[draft.id] = draft
                return draft
        finally:
            self._tasks.discard(task)

    async def submit_confirmed(
        self,
        draft: TranscriptDraft,
        edited_text: str | None = None,
        request_id: str | None = None,
        *,
        speak: bool = True,
        confirmation_kind: str = "manual_transcript",
    ) -> VoiceTurnResult:
        language = self._language()
        if (
            self._drafts.get(draft.id) != draft
            or draft.session_id != self.workbench.session.id
            or draft.language != language
        ):
            raise ValueError("voice_draft_expired")
        return await self.submit_text(
            edited_text if edited_text is not None else draft.text,
            request_id=request_id or draft.id,
            source_context=draft.source_context,
            confirmation_kind=confirmation_kind,
            speak=speak,
        )

    async def submit_text(
        self,
        text: str,
        *,
        request_id: str,
        source_context: TurnSourceSnapshot | None = None,
        confirmation_kind: str = "manual_text",
        speak: bool = True,
    ) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.confirm_user_input(
                text,
                request_id=request_id,
                source_context=source_context,
                confirmation_kind=confirmation_kind,
            )
            if self.on_turn_confirmed:
                self.on_turn_confirmed(turn)
            if turn.state == "completed":
                result = await self.workbench.generate_reply(turn.id)
                return VoiceTurnResult(turn.id, result.assistant_message, "completed", "skipped")
            if turn.state != "pending":
                return VoiceTurnResult(
                    turn.id,
                    None,
                    "failed",
                    "skipped",
                    error_stage="dialogue",
                    error_code="reply_retry_required",
                )
            return await self._generate(turn.id, language, speak=speak)

    async def retry_reply(self, turn_id: str, *, speak: bool = True) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.get_turn(turn_id)
            if turn.state == "completed":
                result = await self.workbench.generate_reply(turn.id)
                return VoiceTurnResult(turn.id, result.assistant_message, "completed", "skipped")
            return await self._generate(turn_id, language, speak=speak)

    async def retry_speech(self, turn_id: str) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.get_turn(turn_id)
            if turn.state != "completed":
                raise ValueError("voice_requires_complete_reply")
            result = await self.workbench.generate_reply(turn_id)
            return await self._generate(turn_id, language, replay=result.assistant_message)

    async def _generate(
        self, turn_id: str, language: str, *, replay=None, speak: bool = True
    ) -> VoiceTurnResult:
        self._stopped_speech.discard(turn_id)
        started = perf_counter()
        buffer, projection, changed = SpeechTextBuffer(), SpokenTextProjection(), asyncio.Event()
        failed: tuple[str, str] | None = None
        count = 0
        timings: dict[str, float] = {}
        current = asyncio.current_task()
        self._tasks.add(current)
        consumer: asyncio.Task | None = None
        producer: asyncio.Task | None = None

        def delta(text: str) -> None:
            nonlocal failed
            if self.on_text_delta:
                try:
                    self.on_text_delta(text)
                except Exception:
                    failed = ("output", "text_consumer_failed")
            timings.setdefault("text_first_delta", (perf_counter() - started) * 1000)
            if failed or not speak or turn_id in self._stopped_speech:
                return
            try:
                buffer.append(text)
            except ValueError:
                failed = ("tts", "speech_text_buffer_full")
            changed.set()

        async def synthesize() -> None:
            nonlocal count, failed
            try:
                backend = await self._bind(self.tts, language)
                while not failed:
                    changed.clear()
                    sentence = buffer.pop_sentence()
                    if sentence is None:
                        if buffer.done:
                            return
                        await changed.wait()
                        continue
                    spoken = projection.project(sentence, final=buffer.done and not buffer.text)
                    if not spoken:
                        continue
                    audio = await backend.synthesize(spoken)
                    if failed:
                        return
                    segment = SpeechSegment.from_wav(
                        turn_id,
                        count,
                        spoken,
                        audio,
                        attribution=getattr(backend, "attribution", ""),
                    )
                    timings.setdefault(
                        "first_audio_segment_ready", (perf_counter() - started) * 1000
                    )
                    if self.on_audio:
                        try:
                            await self.on_audio(segment)
                        except Exception:
                            failed = ("output", "audio_consumer_failed")
                            return
                    count += 1
                    timings.setdefault(
                        "first_audio_segment_delivered", (perf_counter() - started) * 1000
                    )
            except Exception:
                failed = ("tts", "speech_synthesis_failed")

        try:
            if speak:
                consumer = asyncio.create_task(synthesize(), name=f"tts-{turn_id}")
                self._speech_tasks[turn_id] = consumer
            # Keep speech synthesis off the LLM stream reader.
            if replay is None:
                producer = asyncio.create_task(
                    self.workbench.generate_reply(turn_id, on_delta=delta), name=f"reply-{turn_id}"
                )
                try:
                    step = await producer
                    assistant = step.assistant_message
                    timing = getattr(step, "timing", None)
                    if timing:
                        values = timing if isinstance(timing, dict) else timing.model_dump()
                        for key in ("ttft_ms", "total_ms"):
                            if values.get(key) is not None:
                                timings["provider_" + key] = values[key]
                except Exception as exc:
                    if consumer:
                        consumer.cancel()
                        await asyncio.gather(consumer, return_exceptions=True)
                    return VoiceTurnResult(
                        turn_id,
                        None,
                        "failed",
                        "failed" if speak else "skipped",
                        count,
                        "dialogue",
                        f"reply_http_{exc.status_code}"
                        if getattr(exc, "status_code", None) in {401, 402, 429}
                        else "reply_failed",
                        timings,
                    )
                if self.on_text_completed:
                    try:
                        self.on_text_completed(step)
                    except Exception:
                        failed = ("output", "text_consumer_failed")
            else:
                assistant = replay
                delta(replay.content)
            timings["text_completed"] = (perf_counter() - started) * 1000
            buffer.done = True
            changed.set()
            if consumer:
                # A speech-only stop is expected. Cancellation of the foreground
                # operation still propagates through the producer/finally path.
                await asyncio.gather(consumer, return_exceptions=True)
            timings["total"] = (perf_counter() - started) * 1000
            return VoiceTurnResult(
                turn_id,
                assistant,
                "completed",
                "stopped"
                if turn_id in self._stopped_speech
                else "skipped"
                if not speak
                else "failed"
                if failed
                else "completed",
                count,
                failed[0] if failed else None,
                failed[1] if failed else None,
                timings,
            )
        finally:
            for task in (producer, consumer):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (producer, consumer) if t), return_exceptions=True)
            self._tasks.discard(current)
            self._speech_tasks.pop(turn_id, None)
            self._stopped_speech.discard(turn_id)

    async def aclose(self) -> None:
        self._closed = True
        self._drafts.clear()
        tasks = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.own_backends:
            for backend in {id(self.stt): self.stt, id(self.tts): self.tts}.values():
                close = getattr(backend, "aclose", None)
                if close:
                    await close()
