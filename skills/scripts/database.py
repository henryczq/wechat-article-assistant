#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite database wrapper."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from config import get_paths
from schema import SCHEMA_SQL
from utils import ensure_dir, now_ts


class Database:
    """Thin wrapper around sqlite3 with dict-like row access."""

    def __init__(self, db_path: Path | None = None):
        paths = get_paths()
        self.db_path = db_path or paths.db_path
        ensure_dir(self.db_path.parent)
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(SCHEMA_SQL)
            now = now_ts()
            conn.execute(
                """
                INSERT OR IGNORE INTO proxy_config
                (name, enabled, proxy_url, apply_article_fetch, apply_sync, created_at, updated_at)
                VALUES ('default', 0, '', 1, 0, ?, ?)
                """,
                (now, now),
            )
            conn.commit()
            self._connection = conn
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        cursor = self.connection.executemany(sql, seq_of_params)
        self.connection.commit()
        return cursor

    def row(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        cursor = self.connection.execute(sql, tuple(params))
        result = cursor.fetchone()
        return dict(result) if result else None

    def rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.connection.execute(sql, tuple(params))
        return [dict(item) for item in cursor.fetchall()]

    @contextmanager
    def transaction(self):
        conn = self.connection
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
