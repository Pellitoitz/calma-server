"""SQLite with ordered, idempotent migrations (stdlib sqlite3; no ORM needed at this size).

If the schema grows into multi-user territory, SQLAlchemy + Alembic is the
upgrade path; these SQL migrations translate 1:1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1 - initial schema
    """
    CREATE TABLE model_versions (
        version INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        author TEXT,
        message TEXT,
        parent INTEGER,
        content_hash TEXT NOT NULL,
        label TEXT,              -- 'baseline', scenario name...
        file TEXT NOT NULL
    );
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        model_version INTEGER,
        model_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        replications INTEGER NOT NULL,
        engine TEXT, engine_version TEXT, app_version TEXT,
        result_json TEXT NOT NULL
    );
    CREATE TABLE experiments (
        experiment_id TEXT PRIMARY KEY,
        model_version INTEGER,
        created_at TEXT NOT NULL,
        name TEXT,
        result_json TEXT NOT NULL
    );
    CREATE TABLE history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,        -- user | ai | system
        action TEXT NOT NULL,
        request TEXT,
        interpretation TEXT,
        change_json TEXT,
        result TEXT
    );
    CREATE TABLE llm_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        provider TEXT, model TEXT, purpose TEXT,
        input_tokens INTEGER, output_tokens INTEGER,
        est_cost_usd REAL, sent_chars INTEGER
    );
    CREATE TABLE result_cache (
        key TEXT PRIMARY KEY,
        kpis_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE metrics (
        key TEXT NOT NULL,
        value REAL,
        ts TEXT NOT NULL,
        note TEXT
    );
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)  # Streamlit reruns on worker threads
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for i, sql in enumerate(MIGRATIONS, start=1):
        if i not in done:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (i,))
            conn.commit()
    return len(MIGRATIONS)
