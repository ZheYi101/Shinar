"""Transient conversation projection shared by all desktop input modes."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PresentationToken:
    session_id: str
    turn_id: str
    generation: int
    draft_revision: int


@dataclass
class ConversationPresentation:
    messages: list = field(default_factory=list)
    streaming_text: str = ""
    pending_user_text: str = ""
    response_timing: str = ""
    recording_seconds: int = 0
    error: str = ""
    token: PresentationToken | None = None

    def activate(self, token: PresentationToken) -> None:
        self.token = token
        self.streaming_text = ""

    def append(self, token: PresentationToken, text: str) -> bool:
        if token is None or token != self.token:
            return False
        self.streaming_text += text
        return True

    def invalidate(self) -> None:
        self.token = None
        self.streaming_text = ""


def presentation_field(name: str) -> property:
    """Private facade aliases keep one owner while existing adapters migrate."""
    return property(
        lambda facade: getattr(facade.presentation, name),
        lambda facade, value: setattr(facade.presentation, name, value),
    )
