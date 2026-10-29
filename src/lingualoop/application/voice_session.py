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
        own_backends: bool = False,
    ) -> None:
        self.workbench = workbench
        self.stt, self.tts = stt, tts
        self.on_audio, self.on_text_delta = on_audio, on_text_delta
        self.own_backends = own_backends
        self._drafts: dict[str, TranscriptDraft] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

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
        self, draft: TranscriptDraft, edited_text: str | None = None, request_id: str | None = None
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
            confirmation_kind="manual_transcript",
        )

    async def submit_text(
        self,
        text: str,
        *,
        request_id: str,
        source_context: TurnSourceSnapshot | None = None,
        confirmation_kind: str = "manual_text",
    ) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.confirm_user_input(
                text,
                request_id=request_id,
                source_context=source_context,
                confirmation_kind=confirmation_kind,
            )
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
            return await self._generate(turn.id, language)

    async def retry_reply(self, turn_id: str) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.get_turn(turn_id)
            if turn.state == "completed":
                result = await self.workbench.generate_reply(turn.id)
                return VoiceTurnResult(turn.id, result.assistant_message, "completed", "skipped")
            return await self._generate(turn_id, language)

    async def retry_speech(self, turn_id: str) -> VoiceTurnResult:
        language = self._language()
        with self.workbench.conversation_operation():
            turn = self.workbench.get_turn(turn_id)
            if turn.state != "completed":
                raise ValueError("voice_requires_complete_reply")
            result = await self.workbench.generate_reply(turn_id)
            return await self._generate(turn_id, language, replay=result.assistant_message)

    async def _generate(self, turn_id: str, language: str, *, replay=None) -> VoiceTurnResult:
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
            if failed:
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
            consumer = asyncio.create_task(synthesize(), name=f"tts-{turn_id}")
            # Keep speech synthesis off the LLM stream reader.
            if replay is None:
                producer = asyncio.create_task(
                    self.workbench.generate_reply(turn_id, on_delta=delta), name=f"reply-{turn_id}"
                )
                try:
                    step = await producer
                    assistant = step.assistant_message
                except Exception:
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)
                    return VoiceTurnResult(
                        turn_id,
                        None,
                        "failed",
                        "failed",
                        count,
                        "dialogue",
                        "reply_failed",
                        timings,
                    )
            else:
                assistant = replay
                delta(replay.content)
            timings["text_completed"] = (perf_counter() - started) * 1000
            buffer.done = True
            changed.set()
            await consumer
            timings["total"] = (perf_counter() - started) * 1000
            return VoiceTurnResult(
                turn_id,
                assistant,
                "completed",
                "failed" if failed else "completed",
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
