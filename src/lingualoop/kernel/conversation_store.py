"""In-memory implementation used when a workbench has no durable session store."""

import time

from lingualoop.core.conversation import ConversationTurn
from lingualoop.core.domain import PracticeSession, SessionEvent


class MemoryConversationRepository:
    def __init__(self) -> None:
        self.turns: dict[str, ConversationTurn] = {}
        self.sessions: dict[str, PracticeSession] = {}
        self.events: list[SessionEvent] = []

    def get_turn(self, turn_id: str) -> ConversationTurn | None:
        return self.turns.get(turn_id)

    def find_turn(self, session_id: str, request_id: str) -> ConversationTurn | None:
        return next(
            (
                t
                for t in self.turns.values()
                if t.session_id == session_id and t.request_id == request_id
            ),
            None,
        )

    def confirm_turn(
        self, turn: ConversationTurn, session: PracticeSession, event: SessionEvent
    ) -> ConversationTurn:
        existing = self.find_turn(turn.session_id, turn.request_id)
        if existing:
            return existing
        if any(
            t.session_id == turn.session_id
            and t.state == "generating"
            and t.lease_until > time.time()
            for t in self.turns.values()
        ):
            raise RuntimeError("conversation_busy")
        previous = self.sessions.get(session.id)
        if previous and [message.id for message in previous.messages] != turn.history_ids:
            raise RuntimeError("stale_session_snapshot")
        self.turns[turn.id] = turn
        self.sessions[session.id] = session
        self.events.append(event)
        return turn

    def claim_turn(self, turn_id: str) -> ConversationTurn:
        turn = self.turns[turn_id]
        if turn.state == "completed" or (
            turn.state == "generating" and turn.lease_until > time.time()
        ):
            raise RuntimeError("conversation_turn_not_claimable")
        turn = turn.model_copy(
            update={
                "state": "generating",
                "attempt": turn.attempt + 1,
                "lease_until": time.time() + 180,
                "error_code": None,
            }
        )
        self.turns[turn_id] = turn
        return turn

    def finish_turn(
        self, turn: ConversationTurn, session: PracticeSession, events: list[SessionEvent]
    ) -> None:
        current = self.turns[turn.id]
        if current.state != "generating" or current.attempt != turn.attempt:
            raise RuntimeError("conversation_attempt_expired")
        previous = self.sessions.get(session.id)
        if previous and [message.id for message in previous.messages] != [
            message.id for message in session.messages[:-1]
        ]:
            raise RuntimeError("stale_session_snapshot")
        self.turns[turn.id] = turn.model_copy(
            update={
                "state": "completed",
                "lease_until": 0,
                "assistant_message_id": session.messages[-1].id,
            }
        )
        self.sessions[session.id] = session
        self.events.extend(events)

    def fail_turn(self, turn: ConversationTurn, error_code: str) -> None:
        current = self.turns[turn.id]
        if current.state == "generating" and current.attempt == turn.attempt:
            self.turns[turn.id] = current.model_copy(
                update={"state": "failed", "lease_until": 0, "error_code": error_code}
            )
