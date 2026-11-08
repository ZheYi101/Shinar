"""Per-turn text buffering and bounded speech lookahead; no conversation writes."""

from __future__ import annotations

import asyncio
import re
from time import perf_counter
from shinar.core.voice import SpeechSegment
from .speech_text import SpeechTextBuffer, SpokenTextProjection
from .speech_audio import SpeechPlayoutBuffer, trim_speech_padding


class SpeechGeneration:
    def __init__(self, coordinator, turn_id: str, language: str, speak: bool):
        self.coordinator = coordinator
        self.turn_id, self.language, self.speak = turn_id, language, speak
        self.started = perf_counter()
        self.buffer, self.projection = SpeechTextBuffer(), SpokenTextProjection()
        self.changed = asyncio.Event()
        self.failed = None
        self.count = 0
        self.timings = {}

    def delta(self, text: str) -> None:
        if self.coordinator.on_text_delta:
            try:
                self.coordinator.on_text_delta(text)
            except Exception:
                self.failed = ("output", "text_consumer_failed")
        self.timings.setdefault("text_first_delta", (perf_counter() - self.started) * 1000)
        if self.failed or not self.speak or self.turn_id in self.coordinator._stopped_speech:
            return
        try:
            self.buffer.append(text)
        except ValueError:
            self.failed = ("tts", "speech_text_buffer_full")
        self.changed.set()


    async def synthesize(self) -> None:
        pending = SpeechPlayoutBuffer()
        preparation = None

        async def prepare_audio() -> None:
            index = 0
            try:
                backend = await self.coordinator._bind(self.coordinator.tts, self.language)
                while not self.failed:
                    self.changed.clear()
                    sentence = self.buffer.pop_chunk(combine=index > 0)
                    if sentence is None:
                        if self.buffer.done:
                            return
                        await self.changed.wait()
                        continue
                    spoken = self.projection.project(sentence, final=self.buffer.done and not self.buffer.text)
                    if not spoken:
                        continue
                    compute_started = perf_counter()
                    audio = await backend.synthesize(spoken)
                    self.timings["tts_compute"] = self.timings.get("tts_compute", 0) + (
                        perf_counter() - compute_started
                    ) * 1000
                    if self.failed:
                        return
                    segment = SpeechSegment.from_wav(
                        self.turn_id, index, spoken, audio,
                        attribution=getattr(backend, "attribution", ""),
                    )
                    segment, removed = trim_speech_padding(segment)
                    self.timings["padding_removed"] = self.timings.get("padding_removed", 0) + removed
                    self.timings.setdefault(
                        "first_audio_segment_ready", (perf_counter() - self.started) * 1000
                    )
                    await pending.put(segment)
                    index += 1
            except Exception as error:
                code = str(error)
                self.failed = (
                    "tts", code if re.fullmatch(r"speech_[a-z_]+", code)
                    else "speech_synthesis_failed"
                )
            finally:
                await pending.finish()

        try:
            preparation = asyncio.create_task(prepare_audio(), name=f"tts-ahead-{self.turn_id}")
            while not self.failed:
                segment = await pending.get()
                if segment is None or self.failed:
                    return
                try:
                    if self.coordinator.on_audio:
                        await self.coordinator.on_audio(segment)
                except Exception:
                    self.failed = ("output", "audio_consumer_failed")
                    return
                finally:
                    await pending.release(segment)
                self.count += 1
                self.timings.setdefault(
                    "first_audio_segment_delivered", (perf_counter() - self.started) * 1000
                )
        finally:
            if preparation:
                preparation.cancel()
                await asyncio.gather(preparation, return_exceptions=True)

