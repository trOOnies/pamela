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

    -- Macros are stored per entry; editing a food recomputes its entries, deleting
    -- it leaves them with their last values.
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
    # 4: body weight and body fat in the daily check-in, a free-text note per day,
    # and the profile (gender, height) in the database.
    """
    ALTER TABLE day_metrics ADD COLUMN weight_kg REAL
        CHECK (weight_kg > 0 AND weight_kg <= 500);
    ALTER TABLE day_metrics ADD COLUMN body_fat_pct REAL
        CHECK (body_fat_pct > 0 AND body_fat_pct < 100);

    CREATE TABLE day_notes (
        day        TEXT    PRIMARY KEY,             -- YYYY-MM-DD
        text       TEXT    NOT NULL,
        updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    -- A single row.
    CREATE TABLE profile (
        id         INTEGER PRIMARY KEY CHECK (id = 1),
        gender     TEXT    NOT NULL DEFAULT 'unspecified',
        height_cm  REAL    CHECK (height_cm >= 50 AND height_cm <= 280)
    );
    INSERT INTO profile (id) VALUES (1);
    """,
    # 5: an optional emoji per exercise type ('' = use its group's default), filled
    # in for the built-in types.
    """
    ALTER TABLE activity_types ADD COLUMN emoji TEXT NOT NULL DEFAULT '';
    CREATE TEMP TABLE _emoji (name TEXT PRIMARY KEY, emoji TEXT NOT NULL);
    INSERT INTO _emoji (name, emoji) VALUES
        ('Walking', '🚶'), ('Brisk walking', '🚶‍♀️'), ('Nordic walking', '🚶‍♂️'),
        ('Running', '🏃'), ('Jogging', '🏃‍♀️'), ('Trail running', '⛰️'),
        ('Treadmill running', '🏃‍♂️'), ('Treadmill walking (incline)', '📈'),
        ('Cycling', '🚴'), ('Mountain biking', '🚵'),
        ('Stationary bike, light', '🚲'), ('Stationary bike, moderate', '🚲'),
        ('Stationary bike, vigorous', '🚲'), ('Spinning class', '🚴‍♀️'),
        ('Elliptical trainer', '🔄'), ('Rowing machine', '🚣'), ('Stair climber', '🪜'),
        ('Jump rope', '🪢'),
        ('Strength training', '🏋️'), ('Weightlifting, vigorous', '🏋️‍♂️'),
        ('Powerlifting', '🏋️‍♀️'), ('CrossFit', '🔥'), ('HIIT', '⏱️'),
        ('Circuit training', '🔁'), ('Functional training', '🤸'),
        ('Kettlebell training', '💪'), ('Calisthenics', '🤸‍♂️'),
        ('TRX / suspension training', '⛓️'), ('Core / abs workout', '🎯'),
        ('Yoga', '🧘'), ('Power yoga', '🧘‍♀️'), ('Pilates', '🤸‍♀️'), ('Stretching', '🙆'),
        ('Tai chi', '☯️'),
        ('Aerobics', '🎽'), ('Step aerobics', '👟'), ('Zumba', '💃'), ('Dancing', '🕺'),
        ('Aqua aerobics', '🏊‍♀️'), ('Boxing (bag work)', '🥊'), ('Boxing, sparring', '🥊'),
        ('Kickboxing', '🦵'), ('Martial arts', '🥋'),
        ('Football (soccer)', '⚽'), ('Football 5-a-side', '🥅'), ('Basketball', '🏀'),
        ('Volleyball', '🏐'), ('Beach volleyball', '🏖️'), ('Tennis', '🎾'), ('Padel', '🎾'),
        ('Squash', '🧱'), ('Badminton', '🏸'), ('Table tennis', '🏓'), ('Rugby', '🏉'),
        ('Field hockey', '🏑'), ('Handball', '🤾'), ('Golf (walking)', '⛳'),
        ('Swimming', '🏊'), ('Swimming laps, vigorous', '🏊‍♂️'), ('Hiking', '🥾'),
        ('Climbing / bouldering', '🧗'), ('Inline skating', '🛼'), ('Ice skating', '⛸️'),
        ('Skateboarding', '🛹'), ('Downhill skiing', '⛷️'), ('Cross-country skiing', '🎿'),
        ('Snowboarding', '🏂'), ('Surfing', '🏄'), ('Kayaking / canoeing', '🛶'),
        ('Stand-up paddle', '🏄‍♂️'), ('Horse riding', '🏇'),
        ('Walking the dog', '🐕'), ('Gardening', '🌱'), ('Housework', '🧹'),
        ('Playing with kids (active)', '🧒');
    UPDATE activity_types
       SET emoji = (SELECT e.emoji FROM _emoji e WHERE e.name = activity_types.name)
     WHERE name IN (SELECT name FROM _emoji);
    DROP TABLE _emoji;
    """,
    # 6: a food's kcal may be empty (not known yet, counted as 0), which differs
    # from 0 (confirmed calorie-free). SQLite can't drop NOT NULL in place, so the
    # table is rebuilt (migrate() runs with foreign keys off, keeping ids and links).
    # Adds the pescatarian and ovo-lacto vegetarian tags, which vegetarian implies
    # (they are the two branches below it: fish vs eggs and dairy).
    """
    CREATE TABLE foods_new (
        id                 INTEGER PRIMARY KEY,
        name               TEXT    NOT NULL,
        brand              TEXT    NOT NULL DEFAULT '',
        ean                TEXT,     -- normalized GTIN (8, 13 or 14 digits)
        basis_qty          REAL    NOT NULL DEFAULT 100 CHECK (basis_qty > 0),
        unit               TEXT    NOT NULL DEFAULT 'g',
        kcal               REAL    CHECK (kcal >= 0),   -- NULL = not entered yet
        protein_g          REAL    NOT NULL DEFAULT 0,
        carbs_g            REAL    NOT NULL DEFAULT 0,
        fat_g              REAL    NOT NULL DEFAULT 0,
        fiber_g            REAL    NOT NULL DEFAULT 0,
        serving_qty        REAL,     -- one serving, in the food's unit
        package_qty        REAL,     -- whole package, in the food's unit
        pescatarian        INTEGER NOT NULL DEFAULT 0,
        ovolactovegetarian INTEGER NOT NULL DEFAULT 0,
        vegetarian         INTEGER NOT NULL DEFAULT 0,
        vegan              INTEGER NOT NULL DEFAULT 0,
        kosher             INTEGER NOT NULL DEFAULT 0,
        lactose_free       INTEGER NOT NULL DEFAULT 0,
        peanut_free        INTEGER NOT NULL DEFAULT 0,
        tacc_free          INTEGER NOT NULL DEFAULT 0,
        created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    INSERT INTO foods_new (id, name, brand, ean, basis_qty, unit, kcal, protein_g,
        carbs_g, fat_g, fiber_g, serving_qty, package_qty, pescatarian,
        ovolactovegetarian, vegetarian, vegan, kosher, lactose_free, peanut_free,
        tacc_free, created_at, updated_at)
    SELECT id, name, brand, ean, basis_qty, unit, kcal, protein_g, carbs_g, fat_g,
        fiber_g, serving_qty, package_qty, vegetarian OR vegan, vegetarian OR vegan,
        vegetarian OR vegan, vegan, kosher, lactose_free, peanut_free, tacc_free,
        created_at, updated_at
    FROM foods;
    DROP TABLE foods;
    ALTER TABLE foods_new RENAME TO foods;
    CREATE INDEX foods_name ON foods (name COLLATE NOCASE);
    CREATE UNIQUE INDEX foods_ean ON foods (ean) WHERE ean IS NOT NULL;
    """,
    # 7: a food group per food ('' = none); the unit "unit" becomes "whole" (a whole
    # item, like an apple), next to the new "u" (one piece of a pack).
    """
    ALTER TABLE foods ADD COLUMN food_group TEXT NOT NULL DEFAULT '';
    UPDATE foods SET unit = 'whole' WHERE unit = 'unit';
    UPDATE food_entries SET unit = 'whole' WHERE unit = 'unit';
    """,
    # 8: the user's own BMI cutoffs for the weight references (a JSON list); NULL
    # means the defaults for their gender.
    """
    ALTER TABLE profile ADD COLUMN bmi_cutoffs TEXT;
    """,
    # 9: optional conditions on an activity: time of day, weather and how it felt.
    """
    ALTER TABLE activities ADD COLUMN start_time   TEXT;   -- HH:MM
    ALTER TABLE activities ADD COLUMN temp_c       REAL CHECK (temp_c BETWEEN -60 AND 60);
    ALTER TABLE activities ADD COLUMN humidity_pct REAL CHECK (humidity_pct BETWEEN 0 AND 100);
    ALTER TABLE activities ADD COLUMN wind_kmh     REAL CHECK (wind_kmh >= 0);
    ALTER TABLE activities ADD COLUMN comfort      INTEGER CHECK (comfort BETWEEN 1 AND 5);
    """,
    # 10: groceries. A lot is one purchase of a catalog food, in the food's unit.
    # What's left of it is its quantity minus its uses: eaten (taken by a logged food
    # entry, which goes with the entry) or expired (thrown out).
    """
    CREATE TABLE stock_lots (
        id          INTEGER PRIMARY KEY,
        food_id     INTEGER NOT NULL REFERENCES foods (id) ON DELETE CASCADE,
        quantity    REAL    NOT NULL CHECK (quantity > 0),
        bought_on   TEXT    NOT NULL,               -- YYYY-MM-DD
        expires_on  TEXT,                           -- YYYY-MM-DD, NULL = no date
        price       REAL    CHECK (price >= 0),
        store       TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX stock_lots_food ON stock_lots (food_id);

    CREATE TABLE stock_uses (
        id          INTEGER PRIMARY KEY,
        lot_id      INTEGER NOT NULL REFERENCES stock_lots (id) ON DELETE CASCADE,
        kind        TEXT    NOT NULL CHECK (kind IN ('eaten', 'expired')),
        entry_id    INTEGER REFERENCES food_entries (id) ON DELETE CASCADE,
        day         TEXT    NOT NULL,               -- YYYY-MM-DD
        quantity    REAL    NOT NULL CHECK (quantity > 0),
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        CHECK ((kind = 'eaten') = (entry_id IS NOT NULL))
    );
    CREATE INDEX stock_uses_lot ON stock_uses (lot_id);
    CREATE INDEX stock_uses_entry ON stock_uses (entry_id);
    """,
    # 11: purchases come in carts, one per trip to the shops; the day and the store
    # move from each lot to its cart. Lots bought on the same day at the same store
    # become one cart. The table is rebuilt (ids kept, so stock_uses stay linked).
    """
    CREATE TABLE carts (
        id          INTEGER PRIMARY KEY,
        bought_on   TEXT    NOT NULL,               -- YYYY-MM-DD
        store       TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX carts_day ON carts (bought_on);
    INSERT INTO carts (bought_on, store, created_at)
    SELECT bought_on, store, MIN(created_at) FROM stock_lots
    GROUP BY bought_on, store ORDER BY bought_on, MIN(created_at);

    CREATE TABLE stock_lots_new (
        id          INTEGER PRIMARY KEY,
        cart_id     INTEGER NOT NULL REFERENCES carts (id) ON DELETE CASCADE,
        food_id     INTEGER NOT NULL REFERENCES foods (id) ON DELETE CASCADE,
        quantity    REAL    NOT NULL CHECK (quantity > 0),
        expires_on  TEXT,                           -- YYYY-MM-DD, NULL = no date
        price       REAL    CHECK (price >= 0),
        position    INTEGER NOT NULL DEFAULT 0,     -- order within the cart
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    INSERT INTO stock_lots_new (id, cart_id, food_id, quantity, expires_on, price, position,
                                created_at)
    SELECT l.id, c.id, l.food_id, l.quantity, l.expires_on, l.price, l.id, l.created_at
    FROM stock_lots l JOIN carts c ON c.bought_on = l.bought_on AND c.store = l.store;
    DROP TABLE stock_lots;
    ALTER TABLE stock_lots_new RENAME TO stock_lots;
    CREATE INDEX stock_lots_food ON stock_lots (food_id);
    CREATE INDEX stock_lots_cart ON stock_lots (cart_id, position);
    """,
    # 12: a discount on a cart's subtotal (an amount or a percentage, not both), and
    # other items in a cart that aren't food (cleaning products, bags...). Those only
    # make the cart's total match the receipt: they're not in the catalog or the stock.
    """
    ALTER TABLE carts ADD COLUMN discount     REAL CHECK (discount > 0);
    ALTER TABLE carts ADD COLUMN discount_pct REAL CHECK (discount_pct > 0 AND discount_pct <= 100);

    CREATE TABLE cart_extras (
        id          INTEGER PRIMARY KEY,
        cart_id     INTEGER NOT NULL REFERENCES carts (id) ON DELETE CASCADE,
        name        TEXT    NOT NULL,
        quantity    REAL    NOT NULL DEFAULT 1 CHECK (quantity > 0),
        unit        TEXT    NOT NULL DEFAULT 'u',
        price       REAL    CHECK (price >= 0),
        position    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX cart_extras_cart ON cart_extras (cart_id, position);
    """,
    # 13: an optional delivery fee per cart, added to the total after the discount.
    """
    ALTER TABLE carts ADD COLUMN delivery_fee REAL CHECK (delivery_fee >= 0);
    """,
    # 14: the Fridge: sectors (shelves, drawers, the pantry...) that mirror where food
    # is kept at home; each catalog food is in at most one sector, and stays there
    # when it runs out, so it goes back to its place when bought again. Saved meals get
    # an optional recipe. Exercise types done on foot get the steps they take per
    # minute, so a day's steps aren't counted twice (once as steps, once as activity).
    """
    CREATE TABLE fridge_sectors (
        id          INTEGER PRIMARY KEY,
        name        TEXT    NOT NULL,
        emoji       TEXT    NOT NULL DEFAULT '',
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE fridge_foods (
        food_id     INTEGER PRIMARY KEY REFERENCES foods (id) ON DELETE CASCADE,
        sector_id   INTEGER NOT NULL REFERENCES fridge_sectors (id) ON DELETE CASCADE
    );
    CREATE INDEX fridge_foods_sector ON fridge_foods (sector_id);

    ALTER TABLE saved_meals ADD COLUMN recipe TEXT NOT NULL DEFAULT '';

    ALTER TABLE activity_types ADD COLUMN steps_per_min REAL
        CHECK (steps_per_min > 0 AND steps_per_min <= 300);   -- NULL = not on foot
    CREATE TEMP TABLE _cadence (name TEXT PRIMARY KEY, spm REAL NOT NULL);
    INSERT INTO _cadence (name, spm) VALUES
        ('Walking', 100), ('Brisk walking', 115), ('Nordic walking', 110),
        ('Running', 160), ('Jogging', 150), ('Trail running', 150),
        ('Treadmill running', 160), ('Treadmill walking (incline)', 100),
        ('Hiking', 100), ('Walking the dog', 90), ('Golf (walking)', 70);
    UPDATE activity_types
       SET steps_per_min = (SELECT c.spm FROM _cadence c WHERE c.name = activity_types.name)
     WHERE name IN (SELECT name FROM _cadence);
    DROP TABLE _cadence;
    """,
]

# Shown for an exercise type without an emoji of its own.
CATEGORY_EMOJI: dict[str, str] = {
    "Cardio": "🏃",
    "Gym & strength": "🏋️",
    "Mind & body": "🧘",
    "Classes & combat": "🥊",
    "Sports": "🏅",
    "Outdoors & water": "🏞️",
    "Everyday": "🏡",
    "Other": "✨",
}
DEFAULT_CATEGORY_EMOJI = "💪"


def category_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, DEFAULT_CATEGORY_EMOJI)


def checkpoint(path: Path) -> None:
    """Fold the WAL into the main file, so the database is one self-contained file."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


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
        # Off, so a migration can rebuild a table: dropping the old one must not
        # cascade to the rows that point at it. Checked before each commit instead.
        conn.execute("PRAGMA foreign_keys = OFF")
        version = conn.execute("PRAGMA user_version").fetchone()["user_version"]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # executescript commits any pending transaction first; wrap each
            # migration in its own transaction so a failure leaves no half-state.
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};")
            if broken := conn.execute("PRAGMA foreign_key_check").fetchall():
                conn.rollback()
                raise RuntimeError(f"migration {i} broke foreign keys: {broken[:5]}")
            conn.commit()
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
