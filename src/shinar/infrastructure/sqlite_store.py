from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shinar.core.domain import (
    LearningMaterial,
    MaterialAnalysis,
    PracticeSession,
    ReviewItem,
    ReviewStatus,
    SessionEvent,
    SessionSummary,
)
from shinar.core.ports import EventStore
from shinar.core.knowledge import ModelBudgetExceeded
from shinar.core.conversation import ConversationTurn, with_interruption_notice, with_delivery_notice

from shinar.configuration import data_directory, database_file


def default_database_path() -> Path:
    root = data_directory()
    root.mkdir(parents=True, exist_ok=True)
    return database_file(root)


class SQLiteStore(EventStore):
    """Small JSON-payload SQLite store.

    Domain objects remain independent of sqlite3. The payload tables make the
    MVP easy to migrate while keeping events and queue records queryable.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preparation_cache (
                    cache_key TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_preparation_source ON preparation_cache(source_hash);
                CREATE TABLE IF NOT EXISTS knowledge_artifacts (
                    cache_key TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge_artifacts(source_hash, kind);
                CREATE TABLE IF NOT EXISTS knowledge_cache_hits (
                    cache_key TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    workload TEXT NOT NULL,
                    hit_count INTEGER NOT NULL,
                    last_hit TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_budgets (
                    owner TEXT PRIMARY KEY,
                    input_limit INTEGER NOT NULL,
                    output_limit INTEGER NOT NULL,
                    request_limit INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    workload TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    reserved_input INTEGER NOT NULL,
                    reserved_output INTEGER NOT NULL,
                    actual_input INTEGER,
                    actual_output INTEGER,
                    status TEXT NOT NULL,
                    lease_until REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_call_owner ON model_calls(owner);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    material_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(session_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS review_items (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    due_at TEXT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '1');
                UPDATE schema_meta SET value='2' WHERE key='version' AND CAST(value AS INTEGER)<2;
                CREATE INDEX IF NOT EXISTS idx_sessions_material_updated ON sessions(material_id, updated_at DESC);
                """
            )

    def close(self) -> None:
        # Connections are scoped to each operation; retained for API compatibility.
        pass

    def save_material(self, material: LearningMaterial) -> None:
        with self._connect() as connection:
            payload = _dump(material)
            connection.execute(
                """
                INSERT INTO materials(id, created_at, payload) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET created_at=excluded.created_at, payload=excluded.payload
                """,
                (material.id, material.created_at.isoformat(), payload),
            )

    def list_materials(self, limit: int | None = None) -> list[LearningMaterial]:
        with self._connect() as connection:
            query = "SELECT payload FROM materials ORDER BY created_at DESC"
            params: tuple[Any, ...] = ()
            if limit is not None:
                query += " LIMIT ?"
                params = (limit,)
            rows = connection.execute(query, params).fetchall()
            return [LearningMaterial.model_validate(json.loads(row["payload"])) for row in rows]

    def get_material(self, material_id: str) -> LearningMaterial | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM materials WHERE id = ?", (material_id,)
            ).fetchone()
            return (
                LearningMaterial.model_validate(json.loads(row["payload"])) if row else None
            )

    def save_session(self, session: PracticeSession) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (session.id,)).fetchone()
            if row:
                previous = PracticeSession.model_validate_json(row[0])
                before = [message.id for message in previous.messages]
                after = [message.id for message in session.messages]
                if len(before) > len(after) and before[:len(after)] == after:
                    raise RuntimeError("stale_session_snapshot")
            payload = _dump(session)
            connection.execute(
                """
                INSERT INTO sessions(id, material_id, status, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET material_id=excluded.material_id,
                  status=excluded.status, updated_at=excluded.updated_at, payload=excluded.payload
                """,
                (
                    session.id,
                    session.material_id,
                    session.status.value,
                    session.updated_at.isoformat(),
                    payload,
                ),
            )
            for item in session.review_items:
                _save_review_item(connection, item)

    def list_sessions(self, limit: int | None = None, *, material_id: str | None = None) -> list[PracticeSession]:
        with self._connect() as connection:
            query = "SELECT payload FROM sessions"
            params: tuple[Any, ...] = ()
            if material_id is not None:
                query += ' WHERE material_id = ?'
                params = (material_id,)
            query += ' ORDER BY updated_at DESC'
            if limit is not None:
                query += " LIMIT ?"
                params += (limit,)
            rows = connection.execute(query, params).fetchall()
            return [PracticeSession.model_validate(json.loads(row["payload"])) for row in rows]

    def list_session_summaries(self, material_id: str | None = None) -> list[SessionSummary]:
        """Project navigation fields in SQLite without deserializing learning history."""
        query = """
            SELECT id, material_id, status, updated_at,
                COALESCE(json_extract(payload, '$.topic.title'),
                    (SELECT json_extract(value, '$.content') FROM json_each(payload, '$.messages')
                     WHERE json_extract(value, '$.role') = 'user' ORDER BY key LIMIT 1),
                    '') AS title,
                COALESCE((SELECT substr(json_extract(value, '$.content'), 1, 140)
                    FROM json_each(payload, '$.messages')
                    WHERE json_extract(value, '$.role') = 'assistant'
                    ORDER BY key DESC LIMIT 1), '') AS preview,
                (SELECT count(*) FROM json_each(payload, '$.messages')
                 WHERE json_extract(value, '$.role') = 'user') AS turns
            FROM sessions
        """
        params = ()
        if material_id is not None:
            query += " WHERE material_id = ?"
            params = (material_id,)
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            return [SessionSummary.model_validate(dict(row))
                    for row in connection.execute(query, params).fetchall()]

    def get_session(self, session_id: str) -> PracticeSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return PracticeSession.model_validate(json.loads(row["payload"])) if row else None

    def get_preparation_cache(self, cache_key: str) -> MaterialAnalysis | None:
        with self._connect() as connection:
            row = connection.execute('SELECT payload FROM preparation_cache WHERE cache_key = ?', (cache_key,)).fetchone()
            if row is None:
                return None
            try:
                return MaterialAnalysis.model_validate(json.loads(row['payload']))
            except (ValueError, TypeError):
                return None

    def save_preparation_cache(self, cache_key: str, source_hash: str, analysis: MaterialAnalysis) -> None:
        with self._connect() as connection:
            # Serialize read/merge/write across imports sharing a cache identity.
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT payload FROM preparation_cache WHERE cache_key = ?', (cache_key,)).fetchone()
            if row:
                try:
                    previous = MaterialAnalysis.model_validate(json.loads(row['payload']))
                except (ValueError, TypeError):
                    previous = None
                if previous:
                    if previous.preparation_complete and not analysis.preparation_complete:
                        return
                    if not analysis.preparation_complete:
                        chunks = {(c.start_char, c.end_char, c.content_hash): c for c in previous.chunks}
                        chunks.update({(c.start_char, c.end_char, c.content_hash): c for c in analysis.chunks})
                        analysis = analysis.model_copy(update={'chunks': sorted(chunks.values(), key=lambda c: c.start_char)})
            connection.execute('INSERT INTO preparation_cache(cache_key,source_hash,updated_at,payload) VALUES(?,?,?,?) '
                'ON CONFLICT(cache_key) DO UPDATE SET source_hash=excluded.source_hash, updated_at=excluded.updated_at, payload=excluded.payload',
                (cache_key, source_hash, datetime.now(timezone.utc).isoformat(), _dump(analysis)))

    def get_knowledge_artifact(self, cache_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM knowledge_artifacts WHERE cache_key = ?", (cache_key,)).fetchone()
            if row is None:
                return None
            try:
                return json.loads(row["payload"])
            except (TypeError, ValueError):
                return None

    def save_knowledge_artifact(self, cache_key: str, source_hash: str, kind: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_artifacts(cache_key,source_hash,kind,updated_at,payload) VALUES(?,?,?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
                (cache_key, source_hash, kind, datetime.now(timezone.utc).isoformat(), json.dumps(payload, ensure_ascii=False)),
            )

    def ensure_model_budget(self, owner: str, *, input_limit: int, output_limit: int, request_limit: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_budgets(owner,input_limit,output_limit,request_limit) VALUES(?,?,?,?) "
                "ON CONFLICT(owner) DO UPDATE SET input_limit=max(input_limit,excluded.input_limit),"
                "output_limit=max(output_limit,excluded.output_limit),request_limit=max(request_limit,excluded.request_limit)",
                (owner, input_limit, output_limit, request_limit),
            )

    def record_knowledge_cache_hit(self, cache_key: str, source_hash: str, workload: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_cache_hits VALUES(?,?,?,1,?) ON CONFLICT(cache_key) DO UPDATE SET "
                "hit_count=hit_count+1,last_hit=excluded.last_hit",
                (cache_key, source_hash, workload, datetime.now(timezone.utc).isoformat()),
            )

    def list_knowledge_cache_hits(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM knowledge_cache_hits")]

    def reserve_model_call(self, call_id: str, owner: str, workload: str, fingerprint: str,
                           input_tokens: int, output_tokens: int, *, lease_seconds: float = 150,
                           metadata: dict[str, Any] | None = None) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            budget = connection.execute("SELECT * FROM model_budgets WHERE owner=?", (owner,)).fetchone()
            totals = connection.execute(
                "SELECT count(*) AS requests,coalesce(sum(coalesce(actual_input,reserved_input)),0) AS inputs,"
                "coalesce(sum(coalesce(actual_output,reserved_output)),0) AS outputs FROM model_calls WHERE owner=?",
                (owner,),
            ).fetchone()
            if budget is None or totals["requests"] >= budget["request_limit"] or totals["inputs"] + input_tokens > budget["input_limit"] or totals["outputs"] + output_tokens > budget["output_limit"]:
                raise ModelBudgetExceeded("模型调用预算不足；已完成资料保留，可继续使用现有依据。")
            duplicate = connection.execute(
                "SELECT id FROM model_calls WHERE owner=? AND workload=? AND fingerprint=? AND status='reserved' AND lease_until>?",
                (owner, workload, fingerprint, time.time()),
            ).fetchone()
            if duplicate:
                raise ModelBudgetExceeded("相同资料仍在准备，请等待现有任务完成。")
            connection.execute(
                "INSERT INTO model_calls(id,owner,workload,fingerprint,reserved_input,reserved_output,status,lease_until,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (call_id, owner, workload, fingerprint, input_tokens, output_tokens, "reserved", time.time() + lease_seconds,
                 datetime.now(timezone.utc).isoformat(), json.dumps(metadata or {})),
            )

    def settle_model_call(self, call_id: str, usage: dict[str, Any], status: str, *, elapsed_ms: float = 0) -> None:
        safe = {key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "finish_reason") if key in usage}
        safe["elapsed_ms"] = round(elapsed_ms, 2)
        with self._connect() as connection:
            row = connection.execute("SELECT metadata FROM model_calls WHERE id=?", (call_id,)).fetchone()
            safe = {**(json.loads(row["metadata"]) if row else {}), **safe}
            connection.execute(
                "UPDATE model_calls SET actual_input=?,actual_output=?,status=?,metadata=?,lease_until=0 WHERE id=?",
                (safe.get("input_tokens"), safe.get("output_tokens"), status, json.dumps(safe), call_id),
            )

    def list_model_calls(self, owner: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM model_calls" + (" WHERE owner=?" if owner else "") + " ORDER BY created_at", (owner,) if owner else ()).fetchall()
            return [dict(row) for row in rows]

    def latest_model_call(self, owner: str, workload: str, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM model_calls WHERE owner=? AND workload=? AND fingerprint IN (?,?) ORDER BY created_at DESC LIMIT 1",
                (owner, workload, fingerprint + ":0", fingerprint + ":1")).fetchone()
            return dict(row) if row else None

    def save_review_item(self, item: ReviewItem, *, commit: bool = True) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_items(id, status, due_at, payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                  due_at=excluded.due_at, payload=excluded.payload
                """,
                (item.id, item.status.value, _iso(item.due_at), _dump(item)),
            )

    def list_review_items(
        self, *, due_only: bool = False, limit: int | None = None
    ) -> list[ReviewItem]:
        with self._connect() as connection:
            now = datetime.now(timezone.utc).isoformat()
            query = "SELECT payload FROM review_items WHERE status = ?"
            params: list[Any] = [ReviewStatus.ACTIVE.value]
            if due_only:
                query += " AND (due_at IS NULL OR due_at <= ?)"
                params.append(now)
            query += " ORDER BY due_at ASC, id ASC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            rows = connection.execute(query, tuple(params)).fetchall()
            return [ReviewItem.model_validate(json.loads(row["payload"])) for row in rows]

    async def append(self, event: SessionEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO events(id, session_id, occurred_at, payload) VALUES (?, ?, ?, ?)",
                (event.id, event.session_id, event.occurred_at.isoformat(), _dump(event)),
            )

    async def append_many(self, events: list[SessionEvent]) -> None:
        with self._connect() as connection:
            for event in events:
                connection.execute(
                    "INSERT OR REPLACE INTO events(id, session_id, occurred_at, payload) VALUES (?, ?, ?, ?)",
                    (event.id, event.session_id, event.occurred_at.isoformat(), _dump(event)),
                )

    async def list_session_events(self, session_id: str) -> list[SessionEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM events WHERE session_id = ? ORDER BY occurred_at ASC",
                (session_id,),
            ).fetchall()
            return [SessionEvent.model_validate(json.loads(row["payload"])) for row in rows]

    def get_turn(self, turn_id: str) -> ConversationTurn | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            return ConversationTurn.model_validate_json(row[0]) if row else None

    def find_turn(self, session_id: str, request_id: str) -> ConversationTurn | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM conversation_turns WHERE session_id=? AND request_id=?",
                                     (session_id, request_id)).fetchone()
            return ConversationTurn.model_validate_json(row[0]) if row else None

    def confirm_turn(self, turn: ConversationTurn, session: PracticeSession,
                     event: SessionEvent) -> ConversationTurn:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE session_id=? AND request_id=?",
                                     (turn.session_id, turn.request_id)).fetchone()
            if row:
                return ConversationTurn.model_validate_json(row[0])
            for row in connection.execute("SELECT payload FROM conversation_turns WHERE session_id=?", (session.id,)):
                active = ConversationTurn.model_validate_json(row[0])
                if active.state == "generating" and active.lease_until > time.time():
                    raise RuntimeError("conversation_busy")
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (session.id,)).fetchone()
            if row and [m.id for m in PracticeSession.model_validate_json(row[0]).messages] != turn.history_ids:
                raise RuntimeError("stale_session_snapshot")
            connection.execute("INSERT INTO conversation_turns VALUES (?,?,?,?)",
                               (turn.id, turn.session_id, turn.request_id, _dump(turn)))
            _commit_conversation(connection, session, [event])
            return turn

    def claim_turn(self, turn_id: str) -> ConversationTurn:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if not row:
                raise ValueError("conversation_turn_missing")
            turn = ConversationTurn.model_validate_json(row[0])
            if turn.state == "completed" or (turn.state == "generating" and turn.lease_until > time.time()):
                raise RuntimeError("conversation_turn_not_claimable")
            turn = turn.model_copy(update={"state": "generating", "attempt": turn.attempt + 1,
                                          "lease_until": time.time() + 180, "error_code": None,
                                          "cancel_reason": None})
            connection.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (_dump(turn), turn.id))
            return turn

    def finish_turn(self, turn: ConversationTurn, session: PracticeSession,
                    events: list[SessionEvent]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn.id,)).fetchone()
            current = ConversationTurn.model_validate_json(row[0]) if row else None
            if not current or current.state != "generating" or current.attempt != turn.attempt:
                raise RuntimeError("conversation_attempt_expired")
            stored = connection.execute("SELECT payload FROM sessions WHERE id=?", (session.id,)).fetchone()
            if stored and [m.id for m in PracticeSession.model_validate_json(stored[0]).messages] != [m.id for m in session.messages[:-1]]:
                raise RuntimeError("stale_session_snapshot")
            completed = turn.model_copy(update={"state": "completed", "lease_until": 0,
                                                "assistant_message_id": session.messages[-1].id})
            connection.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (_dump(completed), turn.id))
            _commit_conversation(connection, session, events)

    def fail_turn(self, turn: ConversationTurn, error_code: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn.id,)).fetchone()
            if not row:
                return
            current = ConversationTurn.model_validate_json(row[0])
            if current.state == "generating" and current.attempt == turn.attempt:
                current = current.model_copy(update={"state": "failed", "lease_until": 0, "error_code": error_code})
                connection.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (_dump(current), turn.id))

    def cancel_turn(self, turn_id: str, reason: str) -> ConversationTurn:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if not row:
                raise ValueError("conversation_turn_missing")
            current = ConversationTurn.model_validate_json(row[0])
            changes = {"speech_delivery": "interrupted", "cancel_reason": reason}
            if current.state != "completed":
                changes.update(state="cancelled", lease_until=0, error_code=None)
            current = current.model_copy(update=changes)
            connection.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (_dump(current), turn_id))
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (current.session_id,)).fetchone()
            if row:
                session = PracticeSession.model_validate_json(row[0])
                session = with_interruption_notice(session, current)
                connection.execute("UPDATE sessions SET payload=? WHERE id=?", (_dump(session), session.id))
            return current

    def record_delivery(self, turn_id: str, state: str, segment: int = -1) -> None:
        if state not in {"completed", "interrupted", "failed"}:
            raise ValueError("invalid_speech_delivery")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if not row:
                raise ValueError("conversation_turn_missing")
            current = ConversationTurn.model_validate_json(row[0]).model_copy(
                update={"speech_delivery": state, "last_played_segment": segment})
            connection.execute("UPDATE conversation_turns SET payload=? WHERE id=?", (_dump(current), turn_id))
            row = connection.execute("SELECT payload FROM sessions WHERE id=?", (current.session_id,)).fetchone()
            if row:
                session = with_delivery_notice(PracticeSession.model_validate_json(row[0]), current, state)
                connection.execute("UPDATE sessions SET payload=? WHERE id=?", (_dump(session), session.id))


def _commit_conversation(connection: sqlite3.Connection, session: PracticeSession,
                         events: list[SessionEvent]) -> None:
    # Session projection and its events must commit together, including confirmation.
    connection.execute("INSERT INTO sessions(id,material_id,status,updated_at,payload) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at,payload=excluded.payload",
                       (session.id, session.material_id, session.status.value, session.updated_at.isoformat(), _dump(session)))
    for event in events:
        connection.execute("INSERT INTO events(id,session_id,occurred_at,payload) VALUES (?,?,?,?)",
                           (event.id, event.session_id, event.occurred_at.isoformat(), _dump(event)))


def _dump(value: Any) -> str:
    return json.dumps(value.model_dump(mode="json"), ensure_ascii=False)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _save_review_item(connection: sqlite3.Connection, item: ReviewItem) -> None:
    connection.execute(
        "INSERT INTO review_items(id, status, due_at, payload) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
        "due_at=excluded.due_at, payload=excluded.payload",
        (item.id, item.status.value, _iso(item.due_at), _dump(item)),
    )
