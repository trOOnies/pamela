"""SQLite storage (``local/pamela.sqlite3``) with a tiny migration system.

Each entry of ``MIGRATIONS`` is applied once, in order; ``PRAGMA user_version``
records how many have run. Never edit an existing migration - append a new one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE foods (
        id           INTEGER PRIMARY KEY,
        name         TEXT    NOT NULL,
        brand        TEXT    NOT NULL DEFAULT '',
        basis_qty    REAL    NOT NULL DEFAULT 100 CHECK (basis_qty > 0),
        unit         TEXT    NOT NULL DEFAULT 'g',
        kcal         REAL    NOT NULL DEFAULT 0,
        protein_g    REAL    NOT NULL DEFAULT 0,
        carbs_g      REAL    NOT NULL DEFAULT 0,
        fat_g        REAL    NOT NULL DEFAULT 0,
        fiber_g      REAL    NOT NULL DEFAULT 0,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX foods_name ON foods (name COLLATE NOCASE);

    -- Macros are stored as a snapshot so editing a food never rewrites history.
    CREATE TABLE food_entries (
        id           INTEGER PRIMARY KEY,
        day          TEXT    NOT NULL,          -- YYYY-MM-DD
        meal         TEXT    NOT NULL,
        food_id      INTEGER REFERENCES foods (id) ON DELETE SET NULL,
        name         TEXT    NOT NULL,
        quantity     REAL,                      -- in the food's unit; NULL for quick-add
        unit         TEXT    NOT NULL DEFAULT '',
        kcal         REAL    NOT NULL DEFAULT 0,
        protein_g    REAL    NOT NULL DEFAULT 0,
        carbs_g      REAL    NOT NULL DEFAULT 0,
        fat_g        REAL    NOT NULL DEFAULT 0,
        fiber_g      REAL    NOT NULL DEFAULT 0,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX food_entries_day ON food_entries (day);

    CREATE TABLE activities (
        id             INTEGER PRIMARY KEY,
        day            TEXT    NOT NULL,        -- YYYY-MM-DD
        type           TEXT    NOT NULL,
        duration_min   REAL    NOT NULL CHECK (duration_min >= 0),
        distance_km    REAL,
        kcal           REAL    NOT NULL DEFAULT 0,
        kcal_estimated INTEGER NOT NULL DEFAULT 0,
        notes          TEXT    NOT NULL DEFAULT '',
        created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX activities_day ON activities (day);
    """,
]


def _dict_row(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: value for col, value in zip(cursor.description, row, strict=True)}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may open the connection in one worker
    # thread and use it in another; each request still gets its own connection.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = _dict_row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(path: Path) -> int:
    """Bring the database at ``path`` up to date. Returns the schema version."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()["user_version"]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # executescript commits any pending transaction first; wrap each
            # migration in its own transaction so a failure leaves no half-state.
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")
        return conn.execute("PRAGMA user_version").fetchone()["user_version"]
    finally:
        conn.close()


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection that commits on success and rolls back on error."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
