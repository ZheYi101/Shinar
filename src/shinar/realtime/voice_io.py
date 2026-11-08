"""Finite WAV upload and sentence audio output, without Qt or voice turn detection."""

import asyncio
from dataclasses import dataclass
import io
import wave

from shinar.core.voice import SpeechSegment
from .protocol import PcmFrame, TurnRef

WAV_TOPIC = "shinar.voice.wav.v1"
MAX_WAV_BYTES = 24 * 1024**2


@dataclass(frozen=True)
class WavUpload:
    request_id: str
    audio: bytes


class RtcWavInput:
    def __init__(self, room, peer_identity: str) -> None:
        self.room, self.peer_identity = room, peer_identity
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._tasks: set[asyncio.Task] = set()
        self._closed = False
        room.register_byte_stream_handler(WAV_TOPIC, self._incoming)

    def _incoming(self, reader, identity: str) -> None:
        if self._closed or identity != self.peer_identity or self._tasks or not self._queue.empty():
            reader.close()
            return
        task = asyncio.create_task(self._read(reader))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(self, reader) -> None:
        try:
            async with asyncio.timeout(30):
                info = reader.info
                request_id = (info.attributes or {}).get("request_id", "")
                if not request_id or len(request_id) > 200 or info.mime_type != "audio/wav":
                    raise ValueError("invalid_wav_upload")
                if info.size is not None and info.size > MAX_WAV_BYTES:
                    raise ValueError("wav_upload_too_large")
                data = bytearray()
                async for chunk in reader:
                    if len(data) + len(chunk) > MAX_WAV_BYTES:
                        raise ValueError("wav_upload_too_large")
                    data.extend(chunk)
                if info.size is not None and len(data) != info.size:
                    raise ValueError("wav_upload_incomplete")
                self._queue.put_nowait(WavUpload(request_id, bytes(data)))
        except Exception:
            self._queue.put_nowait(ValueError("wav_upload_failed"))
        finally:
            reader.close()

    async def receive(self, timeout: float = 35) -> WavUpload:
        if self._closed:
            raise RuntimeError("wav_input_closed")
        async with asyncio.timeout(timeout):
            result = await self._queue.get()
        if isinstance(result, Exception):
            raise result
        return result

    async def aclose(self) -> None:
        self._closed = True
        self.room.unregister_byte_stream_handler(WAV_TOPIC)
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._queue.empty():
            self._queue.put_nowait(RuntimeError("wav_input_closed"))


async def send_wav(room, identity: str, audio: bytes, request_id: str) -> None:
    if not audio or len(audio) > MAX_WAV_BYTES or not request_id or len(request_id) > 200:
        raise ValueError("invalid_wav_upload")
    await room.local_participant.send_bytes(
        audio,
        topic=WAV_TOPIC,
        name="utterance.wav",
        mime_type="audio/wav",
        destination_identities=[identity],
        attributes={"request_id": request_id},
        compress=False,
    )


class RtcSpeechOutput:
    def __init__(self, transport, ref: TurnRef) -> None:
        self.transport, self.ref = transport, ref
        self._pending_text = ""
        self._changed = asyncio.Event()
        self._done = False
        self._task: asyncio.Task | None = None
        self.sent_samples = 0

    async def start(self) -> None:
        await self.transport.wait_for_peer()
        await self.transport.start_turn(self.ref)
        self._task = asyncio.create_task(self._forward_text())

    def on_text_delta(self, text: str) -> None:
        if self._done or len(self._pending_text) + len(text) > 16000:
            raise RuntimeError("rtc_text_output_unavailable")
        self._pending_text += text
        self._changed.set()

    async def _forward_text(self) -> None:
        while True:
            self._changed.clear()
            value, self._pending_text = self._pending_text, ""
            if value and not await self.transport.send_delta(self.ref, value):
                raise RuntimeError("rtc_text_rejected")
            if self._done and not self._pending_text:
                return
            await self._changed.wait()

    async def on_audio(self, segment: SpeechSegment) -> None:
        if self._done or segment.channels != 1 or segment.sample_width != 2:
            raise ValueError("rtc_requires_mono_pcm16")
        with wave.open(io.BytesIO(segment.audio), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
        if segment.sample_rate != 48000:
            rtc = self.transport.rtc
            resampler = rtc.AudioResampler(segment.sample_rate, 48000, num_channels=1)
            frames = resampler.push(bytearray(pcm)) + resampler.flush()
            pcm = b"".join(bytes(frame.data) for frame in frames)
        # Each independently synthesized sentence is flushed, never relabelled.
        for offset in range(0, len(pcm), 1920):
            data = pcm[offset : offset + 1920]
            if not await self.transport.send_audio(self.ref, PcmFrame(data)):
                raise RuntimeError("rtc_audio_rejected")
            self.sent_samples += len(data) // 2

    async def finish(self, *, text_completed: bool) -> None:
        self._done = True
        self._changed.set()
        if self._task:
            await self._task
        if text_completed:
            await self.transport.complete_text(self.ref)
        await self.transport.drain_audio(self.ref)

    async def aclose(self) -> None:
        self._done = True
        if self._task:
            if not self._task.done():
                self._task.cancel()
            # A failed sender still needs its exception retrieved during cleanup.
            await asyncio.gather(self._task, return_exceptions=True)
