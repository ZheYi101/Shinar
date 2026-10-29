"""Durable confirmation and reply attempts, independent of speech and storage."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .domain import DialoguePreparation, PracticeSession, SessionEvent, new_id, utc_now
from .knowledge import TurnContext
from datetime import datetime


class ConversationTurn(BaseModel):
    id: str = Field(default_factory=lambda: new_id("turn"))
    session_id: str
    request_id: str
    user_message_id: str
    history_ids: list[str]
    source_hash: str
    scope_end: int
    context: TurnContext | None = None
    preparation: DialoguePreparation | None = None
    state: Literal["pending", "generating", "completed", "failed"] = "pending"
    attempt: int = 0
    lease_until: float = 0
    assistant_message_id: str | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ConversationRepository(Protocol):
    def get_turn(self, turn_id: str) -> ConversationTurn | None: ...

    def find_turn(self, session_id: str, request_id: str) -> ConversationTurn | None: ...

    def confirm_turn(
        self, turn: ConversationTurn, session: PracticeSession, event: SessionEvent
    ) -> ConversationTurn: ...

    def claim_turn(self, turn_id: str) -> ConversationTurn: ...

    def finish_turn(
        self, turn: ConversationTurn, session: PracticeSession, events: list[SessionEvent]
    ) -> None: ...

    def fail_turn(self, turn: ConversationTurn, error_code: str) -> None: ...
