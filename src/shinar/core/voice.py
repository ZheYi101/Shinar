"""Provider-neutral speech ports. Audio is transient, outside learning history."""

from typing import Protocol
from dataclasses import dataclass, field
from typing import Literal
import io
import wave

from .domain import Message, new_id
from .knowledge import TurnSourceSnapshot


class SpeechToTextProvider(Protocol):
    async def transcribe(self, audio: bytes) -> str: ...


class TextToSpeechProvider(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


@dataclass(frozen=True)
class TranscriptDraft:
    session_id: str
    text: str
    language: str
    source_context: TurnSourceSnapshot | None = None
    id: str = field(default_factory=lambda: new_id("utterance"))


@dataclass(frozen=True)
class SpeechSegment:
    turn_id: str
    index: int
    text: str
    audio: bytes
    sample_rate: int
    channels: int
    sample_width: int
    attribution: str = ""

    @classmethod
    def from_wav(
        cls, turn_id: str, index: int, text: str, audio: bytes, attribution: str = ""
    ) -> "SpeechSegment":
        if len(audio) > 24 * 1024**2:
            raise ValueError("speech_audio_too_large")
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getcomptype() != "NONE" or not wav.getnframes() or wav.getsampwidth() != 2:
                    raise ValueError("speech_requires_pcm16_wav")
                pcm = wav.readframes(wav.getnframes())
                if len(pcm) != wav.getnframes() * wav.getnchannels() * 2:
                    raise ValueError("speech_audio_truncated")
                return cls(
                    turn_id,
                    index,
                    text,
                    audio,
                    wav.getframerate(),
                    wav.getnchannels(),
                    2,
                    attribution,
                )
        except (wave.Error, EOFError) as exc:
            raise ValueError("speech_requires_pcm16_wav") from exc


@dataclass(frozen=True)
class VoiceTurnResult:
    turn_id: str
    assistant_message: Message | None
    text_status: Literal["completed", "failed"]
    speech_status: Literal["completed", "failed", "skipped", "stopped"]
    segment_count: int = 0
    error_stage: str | None = None
    error_code: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
