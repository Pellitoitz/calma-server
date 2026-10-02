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
    # 2 - AI orchestration: interpretations (draft + answers), engineer corrections, AI audit log
    """
    CREATE TABLE interpretations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        model_version INTEGER,
        text TEXT NOT NULL,
        draft_json TEXT NOT NULL,
        answers_json TEXT NOT NULL DEFAULT '{}',
        interpreter TEXT,
        prompt_version TEXT,
        generation_ms REAL
    );
    CREATE TABLE corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        model_version INTEGER,
        parameter TEXT NOT NULL,
        component TEXT,
        ai_value TEXT,
        engineer_value TEXT,
        reason TEXT,
        request TEXT
    );
    CREATE TABLE ai_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        purpose TEXT NOT NULL,
        provider TEXT, model TEXT, prompt_version TEXT,
        input_text TEXT,
        output_json TEXT,
        validation_errors TEXT,
        repairs INTEGER DEFAULT 0,
        accepted INTEGER DEFAULT 0,
        input_tokens INTEGER, output_tokens INTEGER, est_cost_usd REAL, latency_ms REAL
    );
    """,
    # 3 - economic evaluations (engine >= 0.9.0): many evaluations per physical run, referenced (never copied)
    """
    CREATE TABLE economic_evaluations (
        evaluation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        physical_model_hash TEXT NOT NULL,
        economic_hash TEXT NOT NULL,
        economics_engine_version TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        assumptions_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        approved_by TEXT,
        approved_at TEXT
    );
    CREATE INDEX idx_econ_run ON economic_evaluations(run_id);
    """,
]


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    existed = path.exists() and path.stat().st_size > 0
    conn = sqlite3.connect(path, check_same_thread=False)  # Streamlit reruns on worker threads
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if existed:
            pending = _pending(conn)
            if pending and _done(conn):  # existing project, schema upgrade: keep a copy of the pre-migration DB first
                backup = path.with_name(f"{path.name}.pre-migration-v{max(_done(conn))}.bak")
                if not backup.exists():
                    dst = sqlite3.connect(backup)
                    conn.backup(dst)
                    dst.close()
        migrate(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _done(conn: sqlite3.Connection) -> set[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def _pending(conn: sqlite3.Connection) -> list[int]:
    done = _done(conn)
    return [i for i in range(1, len(MIGRATIONS) + 1) if i not in done]


def schema_version(conn: sqlite3.Connection) -> int:
    done = _done(conn)
    return max(done) if done else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order. Each migration is ATOMIC (its DDL and its schema_migrations row commit
    together or not at all), so a failed migration leaves the database exactly as before and can be retried."""
    for i in _pending(conn):
        try:
            conn.executescript(f"BEGIN;\n{MIGRATIONS[i - 1]}\n;INSERT INTO schema_migrations(version) VALUES ({i});\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return len(MIGRATIONS)
