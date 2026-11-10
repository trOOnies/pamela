"""SQLite storage (``local/pamela.sqlite3``) with a tiny migration system.

Each entry of ``MIGRATIONS`` is applied once, in order; ``PRAGMA user_version``
records how many have run. Never edit an existing migration - append a new one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
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
    # 2: barcodes, portions and diet tags on foods; saved meals; activity types
    # move from info/config.toml into the database; daily steps, sleep and mood.
    """
    ALTER TABLE foods ADD COLUMN ean          TEXT;     -- normalized GTIN (8, 13 or 14 digits)
    ALTER TABLE foods ADD COLUMN serving_qty  REAL;     -- one serving, in the food's unit
    ALTER TABLE foods ADD COLUMN package_qty  REAL;     -- whole package, in the food's unit
    ALTER TABLE foods ADD COLUMN vegetarian   INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE foods ADD COLUMN vegan        INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE foods ADD COLUMN kosher       INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE foods ADD COLUMN lactose_free INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE foods ADD COLUMN peanut_free  INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE foods ADD COLUMN tacc_free    INTEGER NOT NULL DEFAULT 0;
    CREATE UNIQUE INDEX foods_ean ON foods (ean) WHERE ean IS NOT NULL;

    -- A saved meal is only a template: logging it copies its items into
    -- food_entries, so later edits on either side never affect the other.
    CREATE TABLE saved_meals (
        id           INTEGER PRIMARY KEY,
        name         TEXT    NOT NULL,
        default_meal TEXT    NOT NULL DEFAULT '',
        created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE saved_meal_items (
        id             INTEGER PRIMARY KEY,
        saved_meal_id  INTEGER NOT NULL REFERENCES saved_meals (id) ON DELETE CASCADE,
        food_id        INTEGER NOT NULL REFERENCES foods (id) ON DELETE CASCADE,
        quantity       REAL    NOT NULL CHECK (quantity > 0),
        position       INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX saved_meal_items_meal ON saved_meal_items (saved_meal_id, position);

    CREATE TABLE activity_types (
        id        INTEGER PRIMARY KEY,
        name      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        category  TEXT    NOT NULL DEFAULT 'Other',
        met       REAL    NOT NULL CHECK (met > 0 AND met <= 30),
        distance  INTEGER NOT NULL DEFAULT 0
    );
    -- MET values approximate the Compendium of Physical Activities.
    INSERT INTO activity_types (name, category, met, distance) VALUES
        ('Walking', 'Cardio', 3.5, 1),
        ('Brisk walking', 'Cardio', 4.3, 1),
        ('Nordic walking', 'Cardio', 4.8, 1),
        ('Running', 'Cardio', 9.8, 1),
        ('Jogging', 'Cardio', 7.0, 1),
        ('Trail running', 'Cardio', 9.0, 1),
        ('Treadmill running', 'Cardio', 9.0, 1),
        ('Treadmill walking (incline)', 'Cardio', 6.0, 1),
        ('Cycling', 'Cardio', 7.5, 1),
        ('Mountain biking', 'Cardio', 8.5, 1),
        ('Stationary bike, light', 'Cardio', 3.5, 0),
        ('Stationary bike, moderate', 'Cardio', 6.8, 0),
        ('Stationary bike, vigorous', 'Cardio', 8.8, 0),
        ('Spinning class', 'Cardio', 8.5, 0),
        ('Elliptical trainer', 'Cardio', 5.0, 0),
        ('Rowing machine', 'Cardio', 7.0, 1),
        ('Stair climber', 'Cardio', 9.0, 0),
        ('Jump rope', 'Cardio', 11.8, 0),
        ('Strength training', 'Gym & strength', 5.0, 0),
        ('Weightlifting, vigorous', 'Gym & strength', 6.0, 0),
        ('Powerlifting', 'Gym & strength', 6.0, 0),
        ('CrossFit', 'Gym & strength', 8.0, 0),
        ('HIIT', 'Gym & strength', 8.0, 0),
        ('Circuit training', 'Gym & strength', 6.0, 0),
        ('Functional training', 'Gym & strength', 5.0, 0),
        ('Kettlebell training', 'Gym & strength', 8.0, 0),
        ('Calisthenics', 'Gym & strength', 3.8, 0),
        ('TRX / suspension training', 'Gym & strength', 5.0, 0),
        ('Core / abs workout', 'Gym & strength', 3.8, 0),
        ('Yoga', 'Mind & body', 2.5, 0),
        ('Power yoga', 'Mind & body', 4.0, 0),
        ('Pilates', 'Mind & body', 3.0, 0),
        ('Stretching', 'Mind & body', 2.3, 0),
        ('Tai chi', 'Mind & body', 3.0, 0),
        ('Aerobics', 'Classes & combat', 7.3, 0),
        ('Step aerobics', 'Classes & combat', 8.5, 0),
        ('Zumba', 'Classes & combat', 6.5, 0),
        ('Dancing', 'Classes & combat', 5.0, 0),
        ('Aqua aerobics', 'Classes & combat', 5.3, 0),
        ('Boxing (bag work)', 'Classes & combat', 5.5, 0),
        ('Boxing, sparring', 'Classes & combat', 7.8, 0),
        ('Kickboxing', 'Classes & combat', 7.5, 0),
        ('Martial arts', 'Classes & combat', 7.0, 0),
        ('Football (soccer)', 'Sports', 7.0, 0),
        ('Football 5-a-side', 'Sports', 8.0, 0),
        ('Basketball', 'Sports', 6.5, 0),
        ('Volleyball', 'Sports', 4.0, 0),
        ('Beach volleyball', 'Sports', 8.0, 0),
        ('Tennis', 'Sports', 7.3, 0),
        ('Padel', 'Sports', 6.0, 0),
        ('Squash', 'Sports', 7.3, 0),
        ('Badminton', 'Sports', 5.5, 0),
        ('Table tennis', 'Sports', 4.0, 0),
        ('Rugby', 'Sports', 8.3, 0),
        ('Field hockey', 'Sports', 7.8, 0),
        ('Handball', 'Sports', 8.0, 0),
        ('Golf (walking)', 'Sports', 4.8, 0),
        ('Swimming', 'Outdoors & water', 6.0, 1),
        ('Swimming laps, vigorous', 'Outdoors & water', 9.8, 1),
        ('Hiking', 'Outdoors & water', 6.0, 1),
        ('Climbing / bouldering', 'Outdoors & water', 7.5, 0),
        ('Inline skating', 'Outdoors & water', 7.5, 1),
        ('Ice skating', 'Outdoors & water', 7.0, 0),
        ('Skateboarding', 'Outdoors & water', 5.0, 0),
        ('Downhill skiing', 'Outdoors & water', 5.3, 0),
        ('Cross-country skiing', 'Outdoors & water', 9.0, 1),
        ('Snowboarding', 'Outdoors & water', 5.3, 0),
        ('Surfing', 'Outdoors & water', 3.0, 0),
        ('Kayaking / canoeing', 'Outdoors & water', 5.0, 1),
        ('Stand-up paddle', 'Outdoors & water', 6.0, 1),
        ('Horse riding', 'Outdoors & water', 5.5, 0),
        ('Walking the dog', 'Everyday', 3.0, 1),
        ('Gardening', 'Everyday', 3.8, 0),
        ('Housework', 'Everyday', 3.3, 0),
        ('Playing with kids (active)', 'Everyday', 5.8, 0),
        ('Other', 'Other', 4.0, 0);

    CREATE TABLE day_metrics (
        day        TEXT    PRIMARY KEY,             -- YYYY-MM-DD
        steps      INTEGER CHECK (steps >= 0),
        sleep_min  REAL    CHECK (sleep_min >= 0 AND sleep_min <= 1440),
        mood       INTEGER CHECK (mood BETWEEN 1 AND 5),
        feelings   TEXT    NOT NULL DEFAULT '',     -- comma-separated keys
        updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 3: daily targets move from info/config.toml into the database. Each value is
    # in force from start_day until the next period of the same target starts;
    # the first period of a target has no start_day.
    """
    CREATE TABLE target_periods (
        id         INTEGER PRIMARY KEY,
        key        TEXT    NOT NULL,
        start_day  TEXT,                            -- YYYY-MM-DD, NULL = beginning
        value      INTEGER NOT NULL CHECK (value > 0),
        UNIQUE (key, start_day)
    );
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


CONFIG_ACTIVITY_TYPES_IMPORTED = "config_activity_types_imported"


def import_config_activity_types(conn: sqlite3.Connection, types: Iterable) -> bool:
    """One-time move of ``[[activity_types]]`` from info/config.toml into the database.

    Types already in the database (matched by name, ignoring case) take the config's
    MET and distance, since those were the user's own values; new ones are added under
    "Custom". Returns False when the import had already happened."""
    done = conn.execute(
        "SELECT 1 FROM meta WHERE key = ?", (CONFIG_ACTIVITY_TYPES_IMPORTED,)
    ).fetchone()
    if done:
        return False
    for t in types:
        cur = conn.execute(
            "UPDATE activity_types SET met = ?, distance = ? WHERE name = ?",
            (t.met, int(t.distance), t.name),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO activity_types (name, category, met, distance) VALUES (?, ?, ?, ?)",
                (t.name, "Custom", t.met, int(t.distance)),
            )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, datetime('now'))",
        (CONFIG_ACTIVITY_TYPES_IMPORTED,),
    )
    return True


CONFIG_TARGETS_IMPORTED = "config_targets_imported"


def import_config_targets(conn: sqlite3.Connection, targets: Mapping[str, float]) -> bool:
    """One-time move of ``[targets]`` from info/config.toml into the database, as a
    single value for all history. Values become positive integers within ``maxima``.
    Returns False when the import had already happened."""
    from .schemas import TARGETS

    if conn.execute("SELECT 1 FROM meta WHERE key = ?", (CONFIG_TARGETS_IMPORTED,)).fetchone():
        return False
    for key, (_label, _unit, top) in TARGETS.items():
        value = max(1, round(targets[key]))
        if top is not None:
            value = min(value, top)
        conn.execute("DELETE FROM target_periods WHERE key = ?", (key,))
        conn.execute(
            "INSERT INTO target_periods (key, start_day, value) VALUES (?, NULL, ?)", (key, value)
        )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, datetime('now'))", (CONFIG_TARGETS_IMPORTED,)
    )
    return True


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
