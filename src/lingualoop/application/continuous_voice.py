"""Continuous input arbitration over the existing durable voice coordinator."""

import asyncio
import traceback
from collections.abc import Callable
from typing import Any, Protocol
from time import perf_counter

from .voice_session import VoiceSessionCoordinator
from .learning_workbench import LearningWorkbench
from lingualoop.core.knowledge import TurnSourceSnapshot


class AudioSessionPort(Protocol):
    id: str

    async def request(self, kind: str, payload: bytes = b"", **fields: Any) -> dict[str, Any]: ...


class ContinuousConversation:
    def __init__(
        self,
        workbench: LearningWorkbench,
        audio_process: AudioSessionPort,
        emit: Callable[[str, int, Any], None],
    ) -> None:
        self.workbench, self.process, self.emit = workbench, audio_process, emit
        self.input_task = self.reply_task = None
        self.coordinator = None
        self.turn_id = ""
        self.version = None
        self.generation = 0
        self.audio_started = False
        self.segment_count = 0
        self.speech_stopped = False
        self.closed = False
        self.input_allowed = True
        self.pending_input: tuple[dict[str, Any], bytes, TurnSourceSnapshot | None] | None = None
        self.sources = {}
        self._interrupt_lock = asyncio.Lock()
        self._input_cleanup = None
        self._pending_receive = None
        self.started_at = 0.0
        self.metrics = {}

    def event(self, kind: str, value: Any = None) -> None:
        if not self.closed:
            self.emit(kind, self.generation, value)

    async def input_started(self, utterance: str, revision: int) -> None:
        if not self.input_allowed or self.closed:
            return
        if self.pending_input and self.pending_input[0]["utterance"] != utterance:
            self.pending_input = None
        self.version = (utterance, revision)
        current = asyncio.current_task()
        self._input_cleanup = current
        try:
            if self.input_task and self.input_task is not current:
                self.input_task.cancel()
                await asyncio.gather(self.input_task, return_exceptions=True)
            await self.interrupt("user_interruption")
            self.event("input_started")
        finally:
            if self._input_cleanup is current:
                self._input_cleanup = None

    async def interrupt(self, reason: str) -> None:
        async with self._interrupt_lock:
            task, coordinator, turn = self.reply_task, self.coordinator, self.turn_id
            if not task or task.done():
                if self.audio_started:
                    await self.process.request("cancel_output")
                    if turn:
                        self.workbench.record_speech_delivery(turn, "interrupted")
                    self.audio_started = False
                return
            self.generation += 1  # Close text/IPC presentation before any await.
            self.event("interrupted", reason)
            try:
                await self.process.request("cancel_output")
            finally:
                if coordinator and turn:
                    await coordinator.interrupt_reply(turn, reason)
                if task is not asyncio.current_task() and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.audio_started = False
                self.reply_task = None
                self.event("interruption_completed")

    async def cancel_input(self) -> None:
        self.version = None
        pending = self._pending_receive
        if pending and pending is not asyncio.current_task():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        task = self.input_task
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.input_task = None

    def _coordinator(self, stt, tts):
        def current():
            return (
                self.coordinator is coordinator
                and getattr(coordinator, "_continuous_generation", None) == self.generation
                and not self.closed
            )

        def confirmed(turn):
            if not current():
                return
            self.turn_id = turn.id
            if self.pending_input:
                key = self.pending_input[0]["utterance"]
                if turn.request_id == f"voice:{self.process.id}:{key}":
                    self.pending_input = None
            self.event("confirmed", (turn, self.workbench.session))

        def delta(text):
            if current():
                self.metrics.setdefault(
                    "text_first_delta_from_endpoint_ms", (perf_counter() - self.started_at) * 1000
                )
                self.event("delta", text)

        def completed(result):
            if current():
                self.metrics["text_complete_from_endpoint_ms"] = (
                    perf_counter() - self.started_at
                ) * 1000
                self.event("text_completed", result)

        async def consume(segment):
            if self.speech_stopped or not current():
                return
            if segment.attribution:
                self.event("attribution", segment.attribution)
            generation = str(self.generation)
            if not self.audio_started:
                self.audio_started = True
                self.event("output_begin", generation)
                await self.process.request(
                    "output_begin", generation=generation, turn=segment.turn_id
                )
            await self.process.request(
                "segment", segment.audio, generation=generation, index=segment.index, timeout=150
            )
            self.metrics.setdefault(
                "first_segment_sent_ms", (perf_counter() - self.started_at) * 1000
            )
            self.segment_count = segment.index + 1

        coordinator = VoiceSessionCoordinator(
            self.workbench,
            stt=stt,
            tts=tts,
            on_audio=consume,
            on_text_delta=delta,
            on_turn_confirmed=confirmed,
            on_text_completed=completed,
        )
        return coordinator

    async def receive(
        self,
        header: dict[str, Any],
        audio: bytes,
        source: TurnSourceSnapshot | None,
        stt: Any,
        tts: Any,
        speak: bool,
        *,
        manual_retry: bool = False,
    ) -> None:
        identity = (header["utterance"], header["revision"])
        current = asyncio.current_task()
        pending = self._pending_receive
        self._pending_receive = current
        if pending and pending is not current and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        try:
            if self._input_cleanup and self._input_cleanup is not current:
                await asyncio.shield(self._input_cleanup)
        finally:
            if self._pending_receive is current:
                self._pending_receive = None
        if self.closed or (
            not manual_retry
            and (not self.input_allowed or (self.version is not None and self.version != identity))
        ):
            return
        self.version = identity
        self.pending_input = (dict(header), audio, source)
        self.sources.setdefault(identity[0], source)
        if len(self.sources) > 16:
            self.sources.pop(next(iter(self.sources)))
        self.input_task = current
        coordinator = self._coordinator(stt, tts)
        self.started_at = perf_counter()
        self.metrics = {}
        try:
            await self.interrupt("user_interruption")
            self.event("recognizing")
            draft = await coordinator.recognize(audio, self.sources[identity[0]])
            self.metrics["recognition_ms"] = (perf_counter() - self.started_at) * 1000
            if (
                self.closed
                or self.version != identity
                or (not self.input_allowed and not manual_retry)
            ):
                return
            claim = {"accepted": True}
            if not manual_retry:
                for _ in range(20):
                    claim = await self.process.request(
                        "claim", utterance=identity[0], revision=identity[1]
                    )
                    if (
                        claim["accepted"]
                        or claim.get("reason") != "near_speech"
                        or self.version != identity
                    ):
                        break
                    await asyncio.sleep(0.05)
            if (
                not claim["accepted"]
                or self.version != identity
                or (not self.input_allowed and not manual_retry)
            ):
                self.event("claim_rejected", claim.get("reason", "version_changed"))
                return
            # No await between the successful claim and the synchronous transaction.
            self.input_task = None
            self.reply_task, self.coordinator = current, coordinator
            self.generation += 1
            coordinator._continuous_generation = self.generation
            self.audio_started = self.speech_stopped = False
            self.segment_count = 0
            self.event("generating")
            result = await coordinator.submit_confirmed(
                draft,
                request_id=f"voice:{self.process.id}:{identity[0]}",
                confirmation_kind="automatic_transcript",
                speak=speak,
            )
            self.sources.pop(identity[0], None)
            await self._result(result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._receive_failed(error, identity, manual_retry, current)
        finally:
            await coordinator.aclose()
            if self.input_task is current:
                self.input_task = None
            if self.reply_task is current:
                self.reply_task = None


    def _receive_failed(self, error, identity, manual_retry, current):
        if self.closed or self.version != identity or (not self.input_allowed and not manual_retry):
            return
        code = str(error)
        safe_codes = {
            "conversation_busy",
            "voice_draft_expired",
            "stt_empty_result",
            "stt_requires_16khz_mono_pcm16",
            "voice_session_changed",
            "audio_worker_disconnected",
            "audio_worker_closed",
        }
        self.event(
            "recognition_failed" if self.input_task is current else "reply_failed",
            {
                "error_type": type(error).__name__,
                "error_code": code if code in safe_codes else "speech_operation_failed",
                "frames": [
                    f"{frame.name}:{frame.lineno}"
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            },
        )

    async def send_text(
        self,
        text: str,
        source: TurnSourceSnapshot | None,
        stt: Any,
        tts: Any,
        speak: bool,
        *,
        retry_turn: str | None = None,
        speech_only: bool = False,
    ) -> None:
        await self.interrupt("text_input")
        if self._input_cleanup:
            await asyncio.shield(self._input_cleanup)
        current = asyncio.current_task()
        coordinator = self._coordinator(stt, tts)
        self.reply_task, self.coordinator = current, coordinator
        if retry_turn:
            self.turn_id = retry_turn
        self.generation += 1
        coordinator._continuous_generation = self.generation
        self.audio_started = self.speech_stopped = False
        self.segment_count = 0
        self.started_at, self.metrics = perf_counter(), {}
        try:
            self.event("generating")
            if speech_only:
                result = await coordinator.retry_speech(retry_turn)
            elif retry_turn:
                result = await coordinator.retry_reply(retry_turn, speak=speak)
            else:
                from uuid import uuid4

                result = await coordinator.submit_text(
                    text, request_id="text-" + uuid4().hex, source_context=source, speak=speak
                )
            await self._result(result)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.event("reply_failed")
        finally:
            await coordinator.aclose()
            if self.reply_task is current:
                self.reply_task = None

    async def _result(self, result):
        self.metrics.update(result.timings_ms)
        self.event("result", (result, dict(self.metrics)))
        if self.audio_started and not self.speech_stopped:
            await self.process.request("output_done", timeout=150)

    async def stop_speech(self) -> None:
        self.speech_stopped = True
        await self.process.request("cancel_output")
        if self.coordinator and self.turn_id:
            await self.coordinator.stop_speech(self.turn_id)
            self.workbench.record_speech_delivery(self.turn_id, "interrupted")
        self.audio_started = False
        self.event("speech_stopped")

    async def close(self) -> None:
        await self.cancel_input()
        try:
            await self.interrupt("voice_stopped")
        finally:
            self.closed = True
            self.pending_input = None
            self.sources.clear()
