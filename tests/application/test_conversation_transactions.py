import asyncio
import sqlite3

import pytest

from shinar.infrastructure import SQLiteStore
from shinar.core.domain import SessionEvent, SessionEventType
from test_voice_session import make_work


def test_schema_one_upgrades_idempotently_without_user_data(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('version','1')")
    SQLiteStore(path)
    SQLiteStore(path)
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0]
            == "2"
        )
        assert connection.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 0


def test_confirmation_rollback_is_atomic_and_stale_projection_cannot_erase_it(tmp_path):
    async def run():
        work, _ = await make_work(tmp_path / "db")
        old = work.session
        turn = work.confirm_user_input("She waited.", request_id="one")
        store = work._event_store
        with pytest.raises(RuntimeError, match="stale_session_snapshot"):
            store.save_session(old)
        assert store.get_session(old.id).messages[-1].id == turn.user_message_id
        # Reusing an event primary key must roll back both the turn and projection.
        committed = store.get_turn(turn.id)
        other = committed.model_copy(
            update={
                "id": "rollback",
                "request_id": "two",
                "history_ids": [m.id for m in work.session.messages],
            }
        )
        event = (await store.list_session_events(old.id))[-1]
        with pytest.raises(Exception):
            store.confirm_turn(other, work.session, event)
        assert store.get_turn("rollback") is None
        assert store.get_session(old.id).messages[-1].id == turn.user_message_id
        await work.aclose()

    asyncio.run(run())


def test_attempt_compare_and_swap_rejects_late_completion(tmp_path):
    async def run():
        work, _ = await make_work(tmp_path / "db")
        turn = work.confirm_user_input("She waited.", request_id="one")
        store = work._event_store
        first = store.claim_turn(turn.id)
        with pytest.raises(RuntimeError):
            store.claim_turn(turn.id)
        store.fail_turn(first, "reply_failed")
        second = store.claim_turn(turn.id)
        store.fail_turn(first, "late_failure")
        assert store.get_turn(turn.id).state == "generating"
        assert second.attempt == 2
        with pytest.raises(RuntimeError, match="conversation_attempt_expired"):
            store.finish_turn(first, work.session, [])
        store.fail_turn(second, "cancelled")
        await work.aclose()

    asyncio.run(run())
