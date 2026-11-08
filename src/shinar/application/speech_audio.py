"""Bounded speech look-ahead and conservative PCM padding removal, without Qt."""

from array import array
import asyncio
from collections import deque
from dataclasses import replace
import io
import sys
import wave

from shinar.core.voice import SpeechSegment


class SpeechPlayoutBuffer:
    """Budget includes the segment currently being handed to the audio transport."""

    def __init__(self, segments: int = 3, byte_limit: int = 24 * 1024**2) -> None:
        self.segments, self.byte_limit = segments, byte_limit
        self._pending = deque()
        self._count = self._bytes = 0
        self._done = False
        self._changed = asyncio.Condition()

    async def put(self, segment: SpeechSegment) -> None:
        size = len(segment.audio)
        if size > self.byte_limit:
            raise ValueError("speech_audio_too_large")
        async with self._changed:
            await self._changed.wait_for(
                lambda: self._count < self.segments and self._bytes + size <= self.byte_limit
            )
            self._count += 1
            self._bytes += size
            self._pending.append(segment)
            self._changed.notify_all()

    async def get(self) -> SpeechSegment | None:
        async with self._changed:
            await self._changed.wait_for(lambda: self._pending or self._done)
            return self._pending.popleft() if self._pending else None

    async def release(self, segment: SpeechSegment) -> None:
        async with self._changed:
            self._count -= 1
            self._bytes -= len(segment.audio)
            self._changed.notify_all()

    async def finish(self) -> None:
        async with self._changed:
            self._done = True
            self._changed.notify_all()


def trim_speech_padding(segment: SpeechSegment) -> tuple[SpeechSegment, float]:
    """Trim only near-digital-silence at edges, retaining 20/80 ms breathing room.

    Internal pauses, consonants, pitch, sample rate and speaking speed are unchanged.
    At most 500 ms per edge is inspected; all-silent output is left untouched.
    """
    with wave.open(io.BytesIO(segment.audio), "rb") as wav:
        pcm, frames = wav.readframes(wav.getnframes()), wav.getnframes()
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    channels, rate = segment.channels, segment.sample_rate
    scan = min(frames, rate // 2)
    leading = trailing = 0
    for i in range(scan):
        if any(abs(samples[i * channels + c]) > 8 for c in range(channels)):
            break
        leading += 1
    for i in range(scan):
        if any(abs(samples[(frames - i - 1) * channels + c]) > 8 for c in range(channels)):
            break
        trailing += 1
    if leading + trailing >= frames or (leading == scan and trailing == scan):
        return segment, 0.0
    start = max(0, leading - rate * 20 // 1000) if leading >= rate * 60 // 1000 else 0
    end = frames - (max(0, trailing - rate * 80 // 1000) if trailing >= rate * 100 // 1000 else 0)
    if start == 0 and end == frames:
        return segment, 0.0
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm[start * channels * 2 : end * channels * 2])
    return replace(segment, audio=output.getvalue()), (frames - end + start) * 1000 / rate
