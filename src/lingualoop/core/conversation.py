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
    state: Literal["pending", "generating", "completed", "failed", "cancelled"] = "pending"
    cancel_reason: str | None = None
    speech_delivery: Literal["completed", "interrupted", "failed"] | None = None
    last_played_segment: int = -1
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

    def cancel_turn(self, turn_id: str, reason: str) -> ConversationTurn: ...

    def record_delivery(self, turn_id: str, state: str, segment: int = -1) -> None: ...


def with_interruption_notice(session: PracticeSession, turn: ConversationTurn) -> PracticeSession:
    key = "speech_interrupted" if turn.state == "completed" else "reply_interrupted"
    return session.model_copy(
        update={
            "messages": [
                message.model_copy(update={"metadata": {**message.metadata, key: True}})
                if message.id == turn.user_message_id
                else message
                for message in session.messages
            ]
        }
    )


def with_delivery_notice(
    session: PracticeSession, turn: ConversationTurn, state: str
) -> PracticeSession:
    messages = []
    for message in session.messages:
        if message.id == turn.user_message_id:
            metadata = {**message.metadata}
            if state == "interrupted":
                metadata["speech_interrupted"] = True
            elif state == "completed":
                metadata.pop("speech_interrupted", None)
            message = message.model_copy(update={"metadata": metadata})
        messages.append(message)
    return session.model_copy(update={"messages": messages})
