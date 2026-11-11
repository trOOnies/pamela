"""JSON API mounted under ``/api``."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from . import barcode, db
from .config import AppConfig
from .schemas import (
    AUTO_TAGS,
    DIET_FIELDS,
    DIET_IMPLIES,
    DIET_TAGS,
    FEELING_GROUPS,
    GENDERS,
    MACRO_FIELDS,
    MOODS,
    TARGETS,
    Activity,
    ActivityIn,
    ActivityType,
    ActivityTypeIn,
    BarcodeLookup,
    BodyBaseline,
    Day,
    DayMetrics,
    DayMetricsIn,
    DayNote,
    DayNoteIn,
    Entry,
    EntryBatchIn,
    EntryIn,
    Food,
    FoodIn,
    HistoryDay,
    Macros,
    Profile,
    ProfileIn,
    SavedMeal,
    SavedMealIn,
    Target,
    TargetIn,
    Vocabulary,
)
from .tracking import estimate_kcal, scale_macros, target_on

router = APIRouter(prefix="/api")

MAX_HISTORY_DAYS = 366
METRIC_FIELDS = ("steps", "sleep_min", "mood", "weight_kg", "body_fat_pct")
UNPROCESSABLE = 422
BAD_GATEWAY = 502


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    with db.session(request.app.state.settings.db_path) as conn:
        yield conn


def get_config(request: Request) -> AppConfig:
    return request.app.state.config_store.get()


# scope="function": commit *before* the response is sent. With the default
# "request" scope the commit happens after the client already has the reply,
# so an immediate follow-up GET could read the pre-commit state.
Conn = Annotated[sqlite3.Connection, Depends(get_conn, scope="function")]
Config = Annotated[AppConfig, Depends(get_config)]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _not_future(day: dt.date) -> None:
    if day > dt.date.today():
        raise HTTPException(UNPROCESSABLE, "days in the future can't be logged yet")


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- config ------------------------------------------------------------------


@router.get("/config", response_model=AppConfig)
def read_config(config: Config) -> AppConfig:
    return config


@router.get("/vocab", response_model=Vocabulary)
def read_vocab() -> dict:
    def choices(d: dict) -> list[dict]:
        return [{"key": str(k), "label": v} for k, v in d.items()]

    feelings = [
        {"key": k, "label": label, "group": group}
        for group, members in FEELING_GROUPS.items()
        for k, label in members.items()
    ]
    return {
        "diet_tags": choices(DIET_TAGS),
        "diet_implies": DIET_IMPLIES,
        "auto_tags": choices(AUTO_TAGS),
        "moods": choices(MOODS),
        "feelings": feelings,
        "genders": choices(GENDERS),
    }


# --- profile -----------------------------------------------------------------


def _last_weight(conn: sqlite3.Connection, iso: str, before: bool = False) -> dict | None:
    """The latest weight logged on or before ``iso`` (strictly before, with ``before``)."""
    op = "<" if before else "<="
    return conn.execute(
        f"SELECT day, weight_kg FROM day_metrics WHERE weight_kg IS NOT NULL AND day {op} ? "
        "ORDER BY day DESC LIMIT 1",
        (iso,),
    ).fetchone()


def _estimate_weight(last: dict | None, config: AppConfig) -> float:
    return last["weight_kg"] if last else config.profile.weight_kg


def _profile(conn: sqlite3.Connection, config: AppConfig) -> dict:
    row = conn.execute("SELECT gender, height_cm FROM profile WHERE id = 1").fetchone()
    last = _last_weight(conn, dt.date.today().isoformat())
    return {**row, "last_weight": last, "estimate_weight_kg": _estimate_weight(last, config)}


@router.get("/profile", response_model=Profile)
def read_profile(conn: Conn, config: Config) -> dict:
    return _profile(conn, config)


@router.put("/profile", response_model=Profile)
def update_profile(profile: ProfileIn, conn: Conn, config: Config) -> dict:
    conn.execute(
        "UPDATE profile SET gender = ?, height_cm = ? WHERE id = 1",
        (profile.gender, profile.height_cm),
    )
    return _profile(conn, config)


# --- targets -----------------------------------------------------------------


def _target_periods(conn: sqlite3.Connection) -> dict[str, list[tuple[str | None, int]]]:
    """Periods per target key, oldest first (the open-ended first period leads)."""
    out: dict[str, list[tuple[str | None, int]]] = {k: [] for k in TARGETS}
    rows = conn.execute(
        "SELECT key, start_day, value FROM target_periods "
        "ORDER BY key, start_day IS NOT NULL, start_day"
    )
    for r in rows:
        if r["key"] in out:
            out[r["key"]].append((r["start_day"], r["value"]))
    return out


def _targets_on(periods: dict[str, list[tuple[str | None, int]]], iso: str) -> dict:
    return {k: target_on(p, iso) for k, p in periods.items()}


def _target(key: str, periods: list[tuple[str | None, int]]) -> dict:
    label, unit, top = TARGETS[key]
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "max": top,
        "periods": [{"start": s, "value": v} for s, v in periods],
    }


@router.get("/targets", response_model=list[Target])
def list_targets(conn: Conn) -> list[dict]:
    return [_target(k, p) for k, p in _target_periods(conn).items()]


@router.put("/targets/{key}", response_model=Target)
def update_target(key: str, target: TargetIn, conn: Conn) -> dict:
    """Replace every period of one target. A single period is a single value for all
    history, which is also how a target is reset after using custom periods."""
    if key not in TARGETS:
        raise _not_found("target")
    top = TARGETS[key][2]
    if top is not None and any(p.value > top for p in target.periods):
        raise HTTPException(UNPROCESSABLE, f"{TARGETS[key][0]} can't be more than {top}")
    conn.execute("DELETE FROM target_periods WHERE key = ?", (key,))
    conn.executemany(
        "INSERT INTO target_periods (key, start_day, value) VALUES (?, ?, ?)",
        [(key, p.start.isoformat() if p.start else None, p.value) for p in target.periods],
    )
    return _target(key, _target_periods(conn)[key])


# --- foods -------------------------------------------------------------------

_FOOD_SELECT = """
    SELECT f.*, COALESCE(u.uses, 0) AS uses
    FROM foods f
    LEFT JOIN (
        SELECT food_id, COUNT(*) AS uses FROM food_entries
        WHERE food_id IS NOT NULL AND day >= date('now', '-90 days')
        GROUP BY food_id
    ) u ON u.food_id = f.id
"""


def _food_row(conn: sqlite3.Connection, food_id: int) -> dict:
    row = conn.execute(_FOOD_SELECT + " WHERE f.id = ?", (food_id,)).fetchone()
    if row is None:
        raise _not_found("food")
    return row


@router.get("/foods", response_model=list[Food])
def list_foods(
    conn: Conn,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[dict]:
    """Foods ordered by how often they were logged recently, then by name.

    ``q`` matches every whitespace-separated word against name, brand or barcode."""
    where, params = [], []
    for word in q.split():
        like = _like(word)
        where.append(
            "(f.name LIKE ? ESCAPE '\\' OR f.brand LIKE ? ESCAPE '\\' OR f.ean LIKE ? ESCAPE '\\')"
        )
        params += [like, like, like]
    sql = _FOOD_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY uses DESC, f.name COLLATE NOCASE LIMIT ?"
    return conn.execute(sql, (*params, limit)).fetchall()


def _ean_conflict(conn: sqlite3.Connection, food: FoodIn, food_id: int | None = None) -> None:
    if food.ean is None:
        return
    other = conn.execute(
        "SELECT id, name FROM foods WHERE ean = ? AND id IS NOT ?", (food.ean, food_id)
    ).fetchone()
    if other:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"barcode {food.ean} already belongs to \u201c{other['name']}\u201d",
        )


@router.get("/brands", response_model=list[str])
def list_brands(conn: Conn) -> list[str]:
    """Brands already used in the catalog, most used first. Spellings that differ
    only in case count as one, shown as the most common spelling."""
    rows = conn.execute(
        """SELECT brand, COUNT(*) AS n FROM foods WHERE brand != ''
           GROUP BY brand ORDER BY n DESC, brand COLLATE NOCASE"""
    ).fetchall()
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["brand"].casefold(), r["brand"])
    return list(seen.values())


@router.post("/foods", response_model=Food, status_code=status.HTTP_201_CREATED)
def create_food(food: FoodIn, conn: Conn) -> dict:
    _ean_conflict(conn, food)
    data = food.model_dump()
    cols = ", ".join(data)
    marks = ", ".join("?" * len(data))
    cur = conn.execute(f"INSERT INTO foods ({cols}) VALUES ({marks})", tuple(data.values()))
    return _food_row(conn, cur.lastrowid)


@router.get("/barcode/{code}", response_model=BarcodeLookup)
def lookup_barcode(code: str, conn: Conn, online: bool = True) -> dict:
    """Find a product by barcode: first in the catalog, then on Open Food Facts.

    An Open Food Facts hit comes back as a ``draft`` to review; nothing is saved."""
    try:
        ean = barcode.normalize_ean(code)
    except ValueError as e:
        raise HTTPException(UNPROCESSABLE, str(e)) from e
    row = conn.execute(_FOOD_SELECT + " WHERE f.ean = ?", (ean,)).fetchone()
    if row:
        return {"ean": ean, "source": "catalog", "food": row}
    if not online:
        return {"ean": ean, "source": None}
    try:
        product = barcode.fetch_product(ean)
    except barcode.LookupUnavailable as e:
        raise HTTPException(BAD_GATEWAY, str(e)) from e
    if product is None:
        return {"ean": ean, "source": None}
    return {"ean": ean, "source": "openfoodfacts", "draft": barcode.product_to_draft(ean, product)}


@router.get("/foods/{food_id}", response_model=Food)
def read_food(food_id: int, conn: Conn) -> dict:
    return _food_row(conn, food_id)


@router.put("/foods/{food_id}", response_model=Food)
def update_food(food_id: int, food: FoodIn, conn: Conn) -> dict:
    _food_row(conn, food_id)
    _ean_conflict(conn, food, food_id)
    data = food.model_dump()
    sets = ", ".join(f"{k} = ?" for k in data)
    conn.execute(
        f"UPDATE foods SET {sets}, updated_at = datetime('now') WHERE id = ?",
        (*data.values(), food_id),
    )
    return _food_row(conn, food_id)


@router.delete("/foods/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_food(food_id: int, conn: Conn) -> Response:
    """Logged entries keep their macro snapshot; they just lose the link.
    The food is also removed from any saved meal that contains it."""
    if conn.execute("DELETE FROM foods WHERE id = ?", (food_id,)).rowcount == 0:
        raise _not_found("food")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- saved meals -------------------------------------------------------------

_ITEM_COLS = ", ".join(
    f"f.{c}"
    for c in (
        "name",
        "brand",
        "unit",
        "basis_qty",
        "serving_qty",
        "package_qty",
        *MACRO_FIELDS,
        *DIET_FIELDS,
    )
)


def _saved_meals(conn: sqlite3.Connection, saved_meal_id: int | None = None) -> list[dict]:
    where, params = ("WHERE id = ?", (saved_meal_id,)) if saved_meal_id is not None else ("", ())
    meals = conn.execute(
        f"SELECT * FROM saved_meals {where} ORDER BY name COLLATE NOCASE, id", params
    ).fetchall()
    item_where = "WHERE i.saved_meal_id = ?" if saved_meal_id is not None else ""
    items = conn.execute(
        f"""SELECT i.saved_meal_id, i.quantity, f.id AS food_id, {_ITEM_COLS}
            FROM saved_meal_items i JOIN foods f ON f.id = i.food_id
            {item_where} ORDER BY i.position, i.id""",
        params,
    ).fetchall()
    by_meal: dict[int, list[dict]] = {m["id"]: [] for m in meals}
    for it in items:
        by_meal[it["saved_meal_id"]].append(it)
    out = []
    for m in meals:
        rows = by_meal[m["id"]]
        scaled = [
            it | scale_macros(it, it["quantity"]) | {"kcal_missing": it["kcal"] is None}
            for it in rows
        ]
        tags = [t for t in DIET_FIELDS if rows and all(it[t] for it in rows)]
        if rows and all(it["kcal"] == 0 for it in rows):
            tags.append("calorie_free")
        out.append(
            m
            | {
                "items": scaled,
                "totals": {k: sum(it[k] for it in scaled) for k in MACRO_FIELDS},
                "tags": tags,
            }
        )
    return out


def _saved_meal(conn: sqlite3.Connection, saved_meal_id: int) -> dict:
    found = _saved_meals(conn, saved_meal_id)
    if not found:
        raise _not_found("saved meal")
    return found[0]


def _store_items(conn: sqlite3.Connection, saved_meal_id: int, meal: SavedMealIn) -> None:
    ids = {it.food_id for it in meal.items}
    marks = ", ".join("?" * len(ids))
    known = {r["id"] for r in conn.execute(f"SELECT id FROM foods WHERE id IN ({marks})", (*ids,))}
    if missing := ids - known:
        raise HTTPException(UNPROCESSABLE, f"food not found: {', '.join(map(str, missing))}")
    conn.execute("DELETE FROM saved_meal_items WHERE saved_meal_id = ?", (saved_meal_id,))
    conn.executemany(
        "INSERT INTO saved_meal_items (saved_meal_id, food_id, quantity, position) "
        "VALUES (?, ?, ?, ?)",
        [(saved_meal_id, it.food_id, it.quantity, i) for i, it in enumerate(meal.items)],
    )


@router.get("/saved-meals", response_model=list[SavedMeal])
def list_saved_meals(conn: Conn) -> list[dict]:
    return _saved_meals(conn)


@router.post("/saved-meals", response_model=SavedMeal, status_code=status.HTTP_201_CREATED)
def create_saved_meal(meal: SavedMealIn, conn: Conn) -> dict:
    cur = conn.execute(
        "INSERT INTO saved_meals (name, default_meal) VALUES (?, ?)",
        (meal.name, meal.default_meal),
    )
    _store_items(conn, cur.lastrowid, meal)
    return _saved_meal(conn, cur.lastrowid)


@router.get("/saved-meals/{saved_meal_id}", response_model=SavedMeal)
def read_saved_meal(saved_meal_id: int, conn: Conn) -> dict:
    return _saved_meal(conn, saved_meal_id)


@router.put("/saved-meals/{saved_meal_id}", response_model=SavedMeal)
def update_saved_meal(saved_meal_id: int, meal: SavedMealIn, conn: Conn) -> dict:
    cur = conn.execute(
        "UPDATE saved_meals SET name = ?, default_meal = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (meal.name, meal.default_meal, saved_meal_id),
    )
    if cur.rowcount == 0:
        raise _not_found("saved meal")
    _store_items(conn, saved_meal_id, meal)
    return _saved_meal(conn, saved_meal_id)


@router.delete("/saved-meals/{saved_meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_meal(saved_meal_id: int, conn: Conn) -> Response:
    """Entries already logged from it are untouched."""
    if conn.execute("DELETE FROM saved_meals WHERE id = ?", (saved_meal_id,)).rowcount == 0:
        raise _not_found("saved meal")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- food entries ------------------------------------------------------------


def _entry_values(entry: EntryIn, conn: sqlite3.Connection, config: AppConfig) -> dict:
    if entry.meal not in config.meals.names:
        raise HTTPException(
            UNPROCESSABLE,
            f"unknown meal {entry.meal!r}; configured meals: {', '.join(config.meals.names)}",
        )
    _not_future(entry.day)
    values: dict = {"day": entry.day.isoformat(), "meal": entry.meal}
    if entry.food_id is not None:
        food = conn.execute("SELECT * FROM foods WHERE id = ?", (entry.food_id,)).fetchone()
        if food is None:
            raise HTTPException(UNPROCESSABLE, "food not found")
        assert entry.quantity is not None  # guaranteed by EntryIn validation
        values |= {
            "food_id": food["id"],
            "name": entry.name or food["name"],
            "quantity": entry.quantity,
            "unit": food["unit"],
            **scale_macros(food, entry.quantity),
        }
    else:
        values |= {
            "food_id": None,
            "name": entry.name,
            "quantity": entry.quantity,
            "unit": "",
            **{k: getattr(entry, k) or 0 for k in MACRO_FIELDS},
        }
    return values


def _entry_row(conn: sqlite3.Connection, entry_id: int) -> dict:
    row = conn.execute("SELECT * FROM food_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise _not_found("entry")
    return row


def _insert_entry(conn: sqlite3.Connection, entry: EntryIn, config: AppConfig) -> int:
    values = _entry_values(entry, conn, config)
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    cur = conn.execute(
        f"INSERT INTO food_entries ({cols}) VALUES ({marks})", tuple(values.values())
    )
    return cur.lastrowid


@router.post("/entries", response_model=Entry, status_code=status.HTTP_201_CREATED)
def create_entry(entry: EntryIn, conn: Conn, config: Config) -> dict:
    return _entry_row(conn, _insert_entry(conn, entry, config))


@router.post("/entries/batch", response_model=list[Entry], status_code=status.HTTP_201_CREATED)
def create_entries(batch: EntryBatchIn, conn: Conn, config: Config) -> list[dict]:
    """Log several foods into one meal, all or nothing."""
    ids = [
        _insert_entry(
            conn,
            EntryIn(day=batch.day, meal=batch.meal, food_id=it.food_id, quantity=it.quantity),
            config,
        )
        for it in batch.items
    ]
    return [_entry_row(conn, i) for i in ids]


@router.put("/entries/{entry_id}", response_model=Entry)
def update_entry(entry_id: int, entry: EntryIn, conn: Conn, config: Config) -> dict:
    _entry_row(conn, entry_id)
    values = _entry_values(entry, conn, config)
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE food_entries SET {sets} WHERE id = ?", (*values.values(), entry_id))
    return _entry_row(conn, entry_id)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, conn: Conn) -> Response:
    if conn.execute("DELETE FROM food_entries WHERE id = ?", (entry_id,)).rowcount == 0:
        raise _not_found("entry")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- activity types ----------------------------------------------------------

# Categories keep the order in which they first appear (the seed order).
_TYPE_SELECT = """
    SELECT t.*, COALESCE(u.uses, 0) AS uses
    FROM activity_types t
    LEFT JOIN (
        SELECT lower(type) AS k, COUNT(*) AS uses FROM activities
        WHERE day >= date('now', '-90 days') GROUP BY lower(type)
    ) u ON u.k = lower(t.name)
"""
_TYPE_ORDER = """
    ORDER BY (SELECT MIN(c.id) FROM activity_types c WHERE c.category = t.category),
             t.name COLLATE NOCASE
"""


def _type_row(conn: sqlite3.Connection, type_id: int) -> dict:
    row = conn.execute(_TYPE_SELECT + " WHERE t.id = ?", (type_id,)).fetchone()
    if row is None:
        raise _not_found("activity type")
    return _with_icons(row)


def _type_conflict(conn: sqlite3.Connection, t: ActivityTypeIn, type_id: int | None = None) -> None:
    other = conn.execute(
        "SELECT id FROM activity_types WHERE name = ? AND id IS NOT ?", (t.name, type_id)
    ).fetchone()
    if other:
        raise HTTPException(status.HTTP_409_CONFLICT, f"there is already a type named {t.name!r}")


def _with_icons(row: dict) -> dict:
    row["category_icon"] = db.category_emoji(row["category"])
    row["icon"] = row["emoji"] or row["category_icon"]
    return row


@router.get("/activity-types", response_model=list[ActivityType])
def list_activity_types(conn: Conn) -> list[dict]:
    return [_with_icons(r) for r in conn.execute(_TYPE_SELECT + _TYPE_ORDER).fetchall()]


@router.post("/activity-types", response_model=ActivityType, status_code=status.HTTP_201_CREATED)
def create_activity_type(t: ActivityTypeIn, conn: Conn) -> dict:
    _type_conflict(conn, t)
    cur = conn.execute(
        "INSERT INTO activity_types (name, category, met, distance, emoji) VALUES (?, ?, ?, ?, ?)",
        (t.name, t.category, t.met, int(t.distance), t.emoji),
    )
    return _type_row(conn, cur.lastrowid)


@router.put("/activity-types/{type_id}", response_model=ActivityType)
def update_activity_type(type_id: int, t: ActivityTypeIn, conn: Conn) -> dict:
    """Logged activities keep the name they were logged with."""
    _type_row(conn, type_id)
    _type_conflict(conn, t, type_id)
    conn.execute(
        "UPDATE activity_types SET name = ?, category = ?, met = ?, distance = ?, emoji = ?"
        " WHERE id = ?",
        (t.name, t.category, t.met, int(t.distance), t.emoji, type_id),
    )
    return _type_row(conn, type_id)


@router.delete("/activity-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity_type(type_id: int, conn: Conn) -> Response:
    if conn.execute("DELETE FROM activity_types WHERE id = ?", (type_id,)).rowcount == 0:
        raise _not_found("activity type")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- activities --------------------------------------------------------------


def _activity_values(activity: ActivityIn, conn: sqlite3.Connection, config: AppConfig) -> dict:
    _not_future(activity.day)
    values = activity.model_dump()
    values["day"] = activity.day.isoformat()
    if activity.kcal is None:
        atype = conn.execute(
            "SELECT met FROM activity_types WHERE name = ?", (activity.type,)
        ).fetchone()
        if atype is None:
            raise HTTPException(
                UNPROCESSABLE,
                f"unknown activity type {activity.type!r}: enter kcal manually "
                "or add the type in Settings",
            )
        weight = _estimate_weight(_last_weight(conn, values["day"]), config)
        values["kcal"] = estimate_kcal(atype["met"], weight, activity.duration_min)
        values["kcal_estimated"] = 1
    else:
        values["kcal_estimated"] = 0
    return values


def _activity_row(conn: sqlite3.Connection, activity_id: int) -> dict:
    row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        raise _not_found("activity")
    return row


@router.post("/activities", response_model=Activity, status_code=status.HTTP_201_CREATED)
def create_activity(activity: ActivityIn, conn: Conn, config: Config) -> dict:
    values = _activity_values(activity, conn, config)
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    cur = conn.execute(f"INSERT INTO activities ({cols}) VALUES ({marks})", tuple(values.values()))
    return _activity_row(conn, cur.lastrowid)


@router.put("/activities/{activity_id}", response_model=Activity)
def update_activity(activity_id: int, activity: ActivityIn, conn: Conn, config: Config) -> dict:
    _activity_row(conn, activity_id)
    values = _activity_values(activity, conn, config)
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE activities SET {sets} WHERE id = ?", (*values.values(), activity_id))
    return _activity_row(conn, activity_id)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(activity_id: int, conn: Conn) -> Response:
    if conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,)).rowcount == 0:
        raise _not_found("activity")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- daily metrics -----------------------------------------------------------


def _metrics(conn: sqlite3.Connection, iso: str) -> dict:
    row = conn.execute("SELECT * FROM day_metrics WHERE day = ?", (iso,)).fetchone()
    if row is None:
        return DayMetrics().model_dump()
    return {
        "steps": row["steps"],
        "sleep_min": row["sleep_min"],
        "mood": row["mood"],
        "feelings": [f for f in row["feelings"].split(",") if f],
        "weight_kg": row["weight_kg"],
        "body_fat_pct": row["body_fat_pct"],
    }


@router.get("/days/{day}/metrics", response_model=DayMetrics)
def read_day_metrics(day: dt.date, conn: Conn) -> dict:
    return _metrics(conn, day.isoformat())


@router.put("/days/{day}/metrics", response_model=DayMetrics)
def update_day_metrics(day: dt.date, metrics: DayMetricsIn, conn: Conn) -> dict:
    """Steps, sleep, mood, weight and body fat for a day; send every field (empty ones
    are cleared)."""
    _not_future(day)
    iso = day.isoformat()
    m = metrics
    values = (m.steps, m.sleep_min, m.mood, m.weight_kg, m.body_fat_pct)
    if all(v is None for v in values) and not m.feelings:
        conn.execute("DELETE FROM day_metrics WHERE day = ?", (iso,))
    else:
        conn.execute(
            """INSERT INTO day_metrics (day, steps, sleep_min, mood, weight_kg, body_fat_pct,
                                        feelings)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (day) DO UPDATE SET
                 steps = excluded.steps, sleep_min = excluded.sleep_min,
                 mood = excluded.mood, weight_kg = excluded.weight_kg,
                 body_fat_pct = excluded.body_fat_pct, feelings = excluded.feelings,
                 updated_at = datetime('now')""",
            (iso, *values, ",".join(m.feelings)),
        )
    return _metrics(conn, iso)


# --- day notes ---------------------------------------------------------------


def _note(conn: sqlite3.Connection, iso: str) -> str:
    row = conn.execute("SELECT text FROM day_notes WHERE day = ?", (iso,)).fetchone()
    return row["text"] if row else ""


@router.get("/days/{day}/note", response_model=DayNote)
def read_day_note(day: dt.date, conn: Conn) -> dict:
    return {"text": _note(conn, day.isoformat())}


@router.put("/days/{day}/note", response_model=DayNote)
def update_day_note(day: dt.date, note: DayNoteIn, conn: Conn) -> dict:
    """A few words on how the day went. Empty text deletes the note."""
    _not_future(day)
    iso = day.isoformat()
    if not note.text:
        conn.execute("DELETE FROM day_notes WHERE day = ?", (iso,))
    else:
        conn.execute(
            """INSERT INTO day_notes (day, text) VALUES (?, ?)
               ON CONFLICT (day) DO UPDATE SET text = excluded.text,
                 updated_at = datetime('now')""",
            (iso, note.text),
        )
    return {"text": _note(conn, iso)}


# --- aggregates --------------------------------------------------------------


@router.get("/days/{day}", response_model=Day)
def read_day(day: dt.date, conn: Conn, config: Config) -> dict:
    iso = day.isoformat()
    entries = conn.execute(
        "SELECT * FROM food_entries WHERE day = ? ORDER BY created_at, id", (iso,)
    ).fetchall()
    activities = conn.execute(
        "SELECT * FROM activities WHERE day = ? ORDER BY created_at, id", (iso,)
    ).fetchall()
    totals = Macros(**{k: sum(e[k] for e in entries) for k in MACRO_FIELDS})
    last = _last_weight(conn, iso)
    return {
        "day": day,
        "entries": entries,
        "activities": activities,
        "totals": totals,
        "burned_kcal": sum(a["kcal"] for a in activities),
        "active_min": sum(a["duration_min"] for a in activities),
        "metrics": _metrics(conn, iso),
        "note": _note(conn, iso),
        "previous_weight": _last_weight(conn, iso, before=True),
        "estimate_weight_kg": _estimate_weight(last, config),
        "targets": _targets_on(_target_periods(conn), iso),
    }


@router.get("/history/baseline", response_model=BodyBaseline)
def read_history_baseline(conn: Conn, before: dt.date) -> dict:
    """The latest weight and body fat logged strictly before ``before``: what a
    period's latest values are compared with."""
    def last(col: str) -> dict | None:
        return conn.execute(
            f"SELECT day, {col} AS value FROM day_metrics WHERE {col} IS NOT NULL AND day < ? "
            "ORDER BY day DESC LIMIT 1",
            (before.isoformat(),),
        ).fetchone()

    return {"weight_kg": last("weight_kg"), "body_fat_pct": last("body_fat_pct")}


@router.get("/history", response_model=list[HistoryDay])
def read_history(
    conn: Conn,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list[HistoryDay]:
    """Daily totals for every day in ``[start, end]`` (default: last 30 days)."""
    end = end or dt.date.today()
    start = start or end - dt.timedelta(days=29)
    if start > end:
        raise HTTPException(UNPROCESSABLE, "start must be <= end")
    if (end - start).days + 1 > MAX_HISTORY_DAYS:
        raise HTTPException(UNPROCESSABLE, f"range is limited to {MAX_HISTORY_DAYS} days")
    span = (start.isoformat(), end.isoformat())
    sums = ", ".join(f"SUM({k}) AS {k}" for k in MACRO_FIELDS)
    food = {
        r["day"]: r
        for r in conn.execute(
            f"SELECT day, COUNT(*) AS n, {sums} FROM food_entries "
            "WHERE day BETWEEN ? AND ? GROUP BY day",
            span,
        )
    }
    act = {
        r["day"]: r
        for r in conn.execute(
            "SELECT day, SUM(kcal) AS kcal, SUM(duration_min) AS mins FROM activities "
            "WHERE day BETWEEN ? AND ? GROUP BY day",
            span,
        )
    }
    metrics = {
        r["day"]: r
        for r in conn.execute(
            "SELECT day, steps, sleep_min, mood, weight_kg, body_fat_pct FROM day_metrics "
            "WHERE day BETWEEN ? AND ?",
            span,
        )
    }
    noted = {
        r["day"]
        for r in conn.execute("SELECT day FROM day_notes WHERE day BETWEEN ? AND ?", span)
    }
    periods = _target_periods(conn)
    out = []
    for i in range((end - start).days + 1):
        d = start + dt.timedelta(days=i)
        iso = d.isoformat()
        f, a, m = food.get(iso), act.get(iso), metrics.get(iso)
        out.append(
            HistoryDay(
                day=d,
                entry_count=f["n"] if f else 0,
                burned_kcal=a["kcal"] if a else 0,
                active_min=a["mins"] if a else 0,
                **({k: f[k] for k in MACRO_FIELDS} if f else {}),
                **({k: m[k] for k in METRIC_FIELDS} if m else {}),
                has_note=iso in noted,
                targets=_targets_on(periods, iso),
            )
        )
    return out
