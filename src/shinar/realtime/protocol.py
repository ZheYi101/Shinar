"""Vendor-independent, bounded presentation state for streamed assistant turns.

This layer owns drafts, never DialoguePreparation or persisted conversation history.
The application alone decides whether a completed turn should be saved.
"""

from dataclasses import asdict, dataclass
import json
from typing import Literal, Protocol

EventKind = Literal["start", "text_delta", "text_done", "audio_bind", "cancel", "cancel_ack"]
KINDS = {"start", "text_delta", "text_done", "audio_bind", "cancel", "cancel_ack"}


@dataclass(frozen=True)
class TurnRef:
    session_id: str
    turn_id: str
    generation: int

    def __post_init__(self) -> None:
        if not self.session_id or not self.turn_id or self.generation < 1:
            raise ValueError("invalid_turn_ref")


@dataclass(frozen=True)
class TurnEvent:
    ref: TurnRef
    kind: EventKind
    seq: int
    text: str = ""
    track_sid: str = ""

    def encode(self) -> bytes:
        payload = json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")
        if len(payload) > 12000:
            raise ValueError("realtime_event_too_large")
        return payload

    @classmethod
    def decode(cls, payload: bytes) -> "TurnEvent":
        if len(payload) > 12000:
            raise ValueError("realtime_event_too_large")
        data = json.loads(payload)
        if not isinstance(data, dict) or not isinstance(data.get("ref"), dict):
            raise ValueError("invalid_realtime_event")
        ref = data["ref"]
        if (
            set(data) != {"ref", "kind", "seq", "text", "track_sid"}
            or set(ref) != {"session_id", "turn_id", "generation"}
            or data["kind"] not in KINDS
            or type(data["seq"]) is not int or data["seq"] < 0
            or type(ref["generation"]) is not int
            or not all(isinstance(value, str) for value in
                       (ref["session_id"], ref["turn_id"], data["text"], data["track_sid"]))
        ):
            raise ValueError("invalid_realtime_event")
        return cls(TurnRef(**ref), data["kind"], data["seq"], data["text"], data["track_sid"])


@dataclass(frozen=True)
class PcmFrame:
    """Signed 16-bit little-endian interleaved PCM; no microphone ownership."""

    data: bytes
    sample_rate: int = 48000
    channels: int = 1

    def __post_init__(self) -> None:
        if self.sample_rate != 48000 or self.channels != 1:
            raise ValueError("probe_requires_48khz_mono")
        if not self.data or len(self.data) % 2 or len(self.data) > 9600:
            raise ValueError("invalid_pcm_frame")


class RealtimeTransport(Protocol):
    async def connect(self, url: str, token: str) -> None: ...
    async def start_turn(self, ref: TurnRef) -> None: ...
    async def send_delta(self, ref: TurnRef, text: str) -> bool: ...
    async def complete_text(self, ref: TurnRef) -> bool: ...
    async def send_audio(self, ref: TurnRef, frame: PcmFrame) -> bool: ...
    async def request_cancel(self, ref: TurnRef) -> None: ...
    async def close(self) -> None: ...


class TurnReceiver:
    """Strict sequence + generation gate, shared by every transport implementation."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.current: TurnRef | None = None
        self.last_seq = -1
        self.cancelled_generation = 0
        self.draft = ""
        self.completed_text: str | None = None
        self.track_sid = ""
        self.rejected_events = 0
        self.rejected_frames = 0

    def cancel(self, ref: TurnRef) -> None:
        if ref.session_id != self.session_id:
            return
        self.cancelled_generation = max(self.cancelled_generation, ref.generation)
        if self.current == ref:
            self.draft = ""
            self.completed_text = None
            self.track_sid = ""

    def accept(self, event: TurnEvent) -> bool:
        ref = event.ref
        if ref.session_id != self.session_id:
            return self._reject()
        if event.kind == "cancel_ack":
            return self.current == ref and ref.generation <= self.cancelled_generation
        if event.kind == "cancel":
            if self.current != ref:
                return self._reject()
            self.cancel(ref)
            return True
        if ref.generation <= self.cancelled_generation:
            return self._reject()
        if event.kind == "start":
            if event.seq != 0 or (self.current and ref.generation <= self.current.generation):
                return self._reject()
            self.current, self.last_seq = ref, 0
            self.draft, self.completed_text, self.track_sid = "", None, ""
            return True
        if ref != self.current or event.seq != self.last_seq + 1:
            return self._reject()
        if event.kind == "text_delta":
            if self.completed_text is not None or len(self.draft) + len(event.text) > 64000:
                return self._reject()
            self.draft += event.text
        elif event.kind == "text_done":
            if self.completed_text is not None:
                return self._reject()
            self.completed_text = self.draft
        elif event.kind == "audio_bind":
            if not event.track_sid or self.track_sid:
                return self._reject()
            self.track_sid = event.track_sid
        self.last_seq = event.seq
        return True

    def accept_audio(self, track_sid: str) -> bool:
        if (self.current and self.current.generation > self.cancelled_generation
                and track_sid and track_sid == self.track_sid):
            return True
        self.rejected_frames += 1
        return False

    def _reject(self) -> bool:
        self.rejected_events += 1
        return False
