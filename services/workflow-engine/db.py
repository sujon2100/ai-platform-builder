import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("RESULTS_DB_PATH", "/data/results.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    request_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT,
    response TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(_SCHEMA)
        conn.commit()


def create_pending(request_id: str, tenant_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results "
            "(request_id, tenant_id, status, provider, response, error, created_at, updated_at) "
            "VALUES (?, ?, 'pending', NULL, NULL, NULL, ?, ?)",
            (request_id, tenant_id, now, now),
        )
        conn.commit()


def update_result(request_id: str, status: str, provider: str | None, response: str | None, error: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE results SET status = ?, provider = ?, response = ?, error = ?, updated_at = ? "
            "WHERE request_id = ?",
            (status, provider, response, error, now, request_id),
        )
        conn.commit()


def get_result(request_id: str) -> dict | None:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM results WHERE request_id = ?", (request_id,)
        ).fetchone()
        return dict(row) if row else None
