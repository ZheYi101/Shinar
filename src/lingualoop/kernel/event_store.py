from __future__ import annotations

from collections import defaultdict

from lingualoop.core.domain import SessionEvent
from .conversation_store import MemoryConversationRepository


class InMemoryEventStore(MemoryConversationRepository):
    """Small development event store for replayable session facts"""

    def __init__(self) -> None:
        super().__init__()
        """Create a specific property _events_by_session to store data"""
        self._events_by_session: dict[str, list[SessionEvent]] = defaultdict(list)

    async def append(self, event: SessionEvent) -> None:
        self._events_by_session[event.session_id].append(event)

    async def append_many(self, events: list[SessionEvent]) -> None:
        for event in events:
            await self.append(event)

    async def list_session_events(self, session_id: str) -> list[SessionEvent]:
        events = [*self._events_by_session.get(session_id, []),
                  *(event for event in self.events if event.session_id == session_id)]
        return sorted({event.id: event for event in events}.values(), key=lambda event: event.occurred_at)
