import asyncio

from shinar.core import SessionEvent, SessionEventType
from shinar.kernel import InMemoryEventStore


def test_event_store_returns_empty_list_for_unknown_session() -> None:
    async def run_case() -> None:
        store = InMemoryEventStore()

        assert await store.list_session_events("missing_session") == []

    asyncio.run(run_case())


def test_event_store_appends_events_in_order() -> None:
    async def run_case() -> None:
        store = InMemoryEventStore()
        first = SessionEvent(
            session_id="session_1",
            event_type=SessionEventType.SESSION_STARTED,
        )
        second = SessionEvent(
            session_id="session_1",
            event_type=SessionEventType.USER_MESSAGE_ADDED,
        )

        await store.append_many([first, second])

        assert await store.list_session_events("session_1") == [first, second]

    asyncio.run(run_case())
