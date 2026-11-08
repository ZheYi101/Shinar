"""Immutable call events and read-only state at the Qt boundary."""

from dataclasses import dataclass
from typing import Any, Literal

CallEventKind = Literal[
    "transport", "connection_stage", "connected", "resume_device", "pause_device",
    "input_discarded", "input_control_failed", "submit_paused", "restart", "failed",
    "tts_unavailable", "stopped", "recognizing", "input_started", "generating", "confirmed",
    "delta", "attribution", "output_begin", "text_completed", "result", "recognition_failed",
    "interrupted", "speech_stopped", "reply_failed", "interruption_completed",
    "setup_stage", "setup_transfer", "setup_progress", "setup_prepared", "setup_failed", "setup_storage",
]


@dataclass(frozen=True)
class CallEvent:
    identity: str
    kind: CallEventKind
    generation: int = 0
    value: Any = None


@dataclass(frozen=True)
class CallSnapshot:
    identity: str
    connection: str
    input: str
    output: str
    reply: str
    muted: bool
    closed: bool
    generation: int
    audio_generation: str
    mic_generation: int
    error: str
    notice: str
    tts_error: str
    model_error: bool
    attribution: str
    microphone_busy: bool
    paused_input: bool
    pause_id: str
    permission_pending: bool
    permission_error: bool
    connection_stage: str
    has_pending_input: bool
    retained_utterance: str


@dataclass(frozen=True)
class PreparationSnapshot:
    identity: str = ""
    active: bool = False
    failed: bool = False
    stage: str = ""
    transfer: Any = None
    notice: str = ""
    error: str = ""
