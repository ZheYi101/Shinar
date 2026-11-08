"""Identity-checked, Qt-free owner of transient conversation display state."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Literal

from shinar.core import PracticeSession


@dataclass(frozen=True)
class PresentationToken:
    session_id: str
    turn_id: str
    generation: int
    draft_revision: int
    task_id: str

    def same_operation(self, other: "PresentationToken") -> bool:
        return (self.session_id, self.task_id, self.generation) == (
            other.session_id,
            other.task_id,
            other.generation,
        )


EventKind = Literal[
    "begin",
    "confirm",
    "delta",
    "complete",
    "fail",
    "interrupt",
    "settled",
    "refresh",
    "invalidate",
    "preview",
    "recording",
    "timing",
    "error",
    "status",
]


@dataclass(frozen=True)
class ConversationEvent:
    kind: EventKind
    token: PresentationToken | None = None
    session: PracticeSession | None = None
    text: str = ""
    seconds: int = 0
    sent_draft: tuple[int, str] | None = None
    history_changed: bool = False
    message_sent: bool = False


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def display_value(value: Any) -> Any:
    """Return detached Qt-compatible values; callers cannot mutate the owner."""
    if isinstance(value, Mapping):
        return {key: display_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [display_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ConversationSnapshot:
    messages: tuple[Mapping[str, Any], ...] = ()
    streaming_text: str = ""
    pending_user_text: str = ""
    response_timing: str = ""
    recording_seconds: int = 0
    error: str = ""
    token: PresentationToken | None = None


class ConversationPresentation:
    def __init__(self) -> None:
        self._snapshot = ConversationSnapshot()
        self._generation = 0
        self._text_done = False
        self._settled = False
        self._confirmed = False

    @property
    def snapshot(self) -> ConversationSnapshot:
        return self._snapshot

    def accepts(self, event: ConversationEvent) -> bool:
        current, token = self._snapshot.token, event.token
        if event.kind == "begin":
            return token is not None and token.generation > self._generation
        if token is None:
            return event.kind in {"refresh", "invalidate", "error", "status"}
        if current is None:
            return False
        if event.kind == "confirm":
            return (
                not self._text_done
                and not self._confirmed
                and current.same_operation(token)
                and (not current.turn_id or current.turn_id == token.turn_id)
            )
        if token != current:
            return False
        if event.kind in {"delta", "preview", "complete", "fail", "interrupt"}:
            return not self._text_done
        return event.kind != "settled" or not self._settled

    def apply(self, event: ConversationEvent, messages: list[dict] | None = None) -> bool:
        if not self.accepts(event):
            return False
        changes = {}
        if event.kind == "begin":
            self._generation = event.token.generation
            self._text_done = self._settled = False
            self._confirmed = False
            changes.update(
                token=event.token,
                streaming_text="",
                pending_user_text="",
                response_timing="",
                recording_seconds=0,
                error="",
            )
        elif event.kind == "confirm":
            self._confirmed = True
            changes.update(token=event.token, streaming_text="", pending_user_text="")
        elif event.kind == "delta":
            changes["streaming_text"] = self._snapshot.streaming_text + event.text
        elif event.kind in {"complete", "fail", "interrupt", "settled", "invalidate"}:
            self._text_done = True
            changes.update(streaming_text="", pending_user_text="")
            if event.kind == "settled":
                self._settled = True
            if event.kind == "invalidate":
                changes.update(token=None, recording_seconds=0)
        elif event.kind == "preview":
            changes["pending_user_text"] = event.text
        elif event.kind == "recording":
            changes["recording_seconds"] = event.seconds
        elif event.kind == "timing":
            changes["response_timing"] = event.text
        elif event.kind == "error":
            changes["error"] = event.text
        if messages is not None:
            changes["messages"] = freeze(messages)
        self._snapshot = replace(self._snapshot, **changes)
        return True
