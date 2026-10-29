"""A process-safe attempt ceiling shared by explicit real validation runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class ModelRequestGuard:
    def __init__(self, path: Path, limit: int = 100) -> None:
        if limit < 1:
            raise ValueError("Request limit must be positive")
        self.path = path
        self.limit = limit
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,role TEXT NOT NULL,started_at TEXT NOT NULL)"
            )

    def reserve(self, role: str) -> None:
        with sqlite3.connect(self.path, timeout=10) as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
            if count >= self.limit:
                raise RuntimeError("真实验证请求已达到共享上限，后续请求已阻止。")
            connection.execute(
                "INSERT INTO attempts(role,started_at) VALUES(?,?)",
                (role, datetime.now(timezone.utc).isoformat()),
            )

    def count(self) -> int:
        with sqlite3.connect(self.path) as connection:
            return connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
