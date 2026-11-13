"""JSON API mounted under ``/api``."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from . import barcode, db
from .config import AppConfig
from .schemas import (
    AUTO_TAGS,
    BMI_DEFAULTS,
    BODY_BRACKETS,
    BODY_TYPES,
    DIET_FIELDS,
    DIET_IMPLIES,
    DIET_TAGS,
    FEELING_GROUPS,
    FOOD_GROUPS,
    GENDERS,
    MACRO_FIELDS,
    MOODS,
    TARGETS,
    UNITS,
    WIPE_TARGETS,
    Activity,
    ActivityIn,
    ActivityType,
    ActivityTypeIn,
    BarcodeLookup,
    BodyBaseline,
    BodyReferences,
    BodyReferencesIn,
    Cart,
    CartIn,
    Day,
    DayMetrics,
    DayMetricsIn,
    DayNote,
    DayNoteIn,
    Deleted,
    Entry,
    EntryBatchIn,
    EntryIn,
    ExpiredIn,
    Food,
    FoodIn,
    Groceries,
    HistoryDay,
    Lot,
    Macros,
    Profile,
    ProfileIn,
    SavedMeal,
    SavedMealIn,
    Target,
    TargetIn,
    Vocabulary,
    WipeIn,
    gender_group,
)
from .tracking import estimate_kcal, scale_macros, steps_burn, target_on

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
        "food_groups": [
            {"key": k, "label": label, "emoji": emoji} for k, (label, emoji) in FOOD_GROUPS.items()
        ],
        "units": list(UNITS),
        "wipe_targets": [
            {"key": k, "label": label, "hint": hint} for k, (label, hint) in WIPE_TARGETS.items()
        ],
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


def _body_references(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT gender, bmi_cutoffs FROM profile WHERE id = 1").fetchone()
    group = gender_group(row["gender"])
    custom = row["bmi_cutoffs"] is not None
    cutoffs = json.loads(row["bmi_cutoffs"]) if custom else list(BMI_DEFAULTS[group])
    bounds = [None, *cutoffs, None]
    return {
        "gender_group": group,
        "cutoffs": cutoffs,
        "custom": custom,
        "defaults": {k: list(v) for k, v in BMI_DEFAULTS.items()},
        "brackets": [
            {"key": k, "label": label, "body_type": BODY_TYPES[group][i],
             "min_bmi": bounds[i], "max_bmi": bounds[i + 1]}
            for i, (k, label) in enumerate(BODY_BRACKETS.items())
        ],
    }


@router.get("/body-references", response_model=BodyReferences)
def read_body_references(conn: Conn) -> dict:
    """Weight brackets by BMI, with a stereotypical body type for each."""
    return _body_references(conn)


@router.put("/body-references", response_model=BodyReferences)
def update_body_references(refs: BodyReferencesIn, conn: Conn) -> dict:
    """Set your own cutoffs, or ``null`` to go back to the defaults for your gender."""
    value = json.dumps(refs.cutoffs) if refs.cutoffs is not None else None
    conn.execute("UPDATE profile SET bmi_cutoffs = ? WHERE id = 1", (value,))
    return _body_references(conn)


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

# What's left of each lot: its quantity minus everything eaten or thrown out.
_LOT_LEFT = """
    SELECT l.*, c.bought_on, c.store,
           COALESCE(SUM(CASE WHEN u.kind = 'eaten' THEN u.quantity END), 0) AS eaten,
           COALESCE(SUM(CASE WHEN u.kind = 'expired' THEN u.quantity END), 0) AS expired,
           l.quantity - COALESCE(SUM(u.quantity), 0) AS remaining
    FROM stock_lots l JOIN carts c ON c.id = l.cart_id
    LEFT JOIN stock_uses u ON u.lot_id = l.id
"""
_FOOD_SELECT = f"""
    SELECT f.*, COALESCE(u.uses, 0) AS uses, s.in_stock
    FROM foods f
    LEFT JOIN (
        SELECT food_id, COUNT(*) AS uses FROM food_entries
        WHERE food_id IS NOT NULL AND day >= date('now', '-90 days')
        GROUP BY food_id
    ) u ON u.food_id = f.id
    LEFT JOIN (
        SELECT food_id, SUM(MAX(remaining, 0)) AS in_stock
        FROM ({_LOT_LEFT} GROUP BY l.id) GROUP BY food_id
    ) s ON s.food_id = f.id
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
    _refresh_entries(conn, food_id)
    return _food_row(conn, food_id)


def _refresh_entries(conn: sqlite3.Connection, food_id: int) -> None:
    """Recompute every logged entry of a food from its current values, on any day."""
    food = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
    sets = ", ".join(f"{k} = ?" for k in ("unit", *MACRO_FIELDS))
    rows = conn.execute(
        "SELECT id, quantity FROM food_entries WHERE food_id = ? AND quantity IS NOT NULL",
        (food_id,),
    ).fetchall()
    conn.executemany(
        f"UPDATE food_entries SET {sets} WHERE id = ?",
        [
            (food["unit"], *scale_macros(food, r["quantity"]).values(), r["id"])
            for r in rows
        ],
    )


@router.delete("/foods/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_food(food_id: int, conn: Conn) -> Response:
    """Logged entries keep their macro snapshot; they just lose the link.
    The food is also removed from any saved meal and cart that contains it; a cart
    left empty goes too."""
    if conn.execute("DELETE FROM foods WHERE id = ?", (food_id,)).rowcount == 0:
        raise _not_found("food")
    _drop_empty_carts(conn)
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


_ENTRY_SELECT = """
    SELECT e.*, COALESCE((SELECT SUM(quantity) FROM stock_uses WHERE entry_id = e.id), 0)
           AS from_stock
    FROM food_entries e
"""


def _entry_row(conn: sqlite3.Connection, entry_id: int) -> dict:
    row = conn.execute(_ENTRY_SELECT + " WHERE e.id = ?", (entry_id,)).fetchone()
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
    _take_stock(conn, cur.lastrowid, values)
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
    _take_stock(conn, entry_id, values)
    return _entry_row(conn, entry_id)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, conn: Conn) -> Response:
    """What the entry took from Groceries goes back there."""
    if conn.execute("DELETE FROM food_entries WHERE id = ?", (entry_id,)).rowcount == 0:
        raise _not_found("entry")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- groceries ---------------------------------------------------------------

# Amounts below this count as nothing left (sums of floats rarely land on 0 exactly).
EPS = 1e-6


def _open_lots(conn: sqlite3.Connection, food_id: int, day: str) -> list[dict]:
    """Lots of a food bought by ``day`` with something left, in the order they're
    used: the one that expires first, then the oldest; lots without a date last."""
    return conn.execute(
        _LOT_LEFT
        + """ WHERE l.food_id = ? AND c.bought_on <= ? GROUP BY l.id HAVING remaining > ?
             ORDER BY l.expires_on IS NULL, l.expires_on, c.bought_on, l.id""",
        (food_id, day, EPS),
    ).fetchall()


def _take_stock(conn: sqlite3.Connection, entry_id: int, values: dict) -> None:
    """(Re)takes what a logged entry ate from Groceries, as far as there is any. An
    entry eating more than is left simply takes what's there."""
    conn.execute("DELETE FROM stock_uses WHERE entry_id = ?", (entry_id,))
    need = values["quantity"] or 0
    if values["food_id"] is None or need <= 0:
        return
    _take_from_lots(conn, entry_id, values["food_id"], values["day"], need)


def _take_from_lots(
    conn: sqlite3.Connection, entry_id: int, food_id: int, day: str, need: float
) -> None:
    for lot in _open_lots(conn, food_id, day):
        take = min(lot["remaining"], need)
        conn.execute(
            "INSERT INTO stock_uses (lot_id, kind, entry_id, day, quantity) "
            "VALUES (?, 'eaten', ?, ?, ?)",
            (lot["id"], entry_id, day, take),
        )
        need -= take
        if need <= EPS:
            break


def _lot_row(conn: sqlite3.Connection, lot_id: int) -> dict:
    row = conn.execute(_LOT_LEFT + " WHERE l.id = ? GROUP BY l.id", (lot_id,)).fetchone()
    if row is None:
        raise _not_found("cart item")
    return row


def _food_exists(conn: sqlite3.Connection, ids: set[int]) -> None:
    marks = ", ".join("?" * len(ids))
    known = {r["id"] for r in conn.execute(f"SELECT id FROM foods WHERE id IN ({marks})", (*ids,))}
    if missing := ids - known:
        raise HTTPException(UNPROCESSABLE, f"food not found: {', '.join(map(str, missing))}")


def _foods_info(conn: sqlite3.Connection) -> dict[int, dict]:
    return {
        f["id"]: f
        for f in conn.execute(
            "SELECT id, name, brand, unit, serving_qty, package_qty, food_group FROM foods"
        )
    }


def _carts(conn: sqlite3.Connection, cart_id: int | None = None) -> list[dict]:
    """Carts, newest first, each with its items in the order they were entered."""
    where, params = ("WHERE id = ?", (cart_id,)) if cart_id is not None else ("", ())
    carts = conn.execute(
        f"SELECT * FROM carts {where} ORDER BY bought_on DESC, created_at DESC, id DESC", params
    ).fetchall()
    lot_where = "WHERE l.cart_id = ?" if cart_id is not None else ""
    lots = conn.execute(
        _LOT_LEFT + f" {lot_where} GROUP BY l.id ORDER BY l.position, l.id", params
    ).fetchall()
    foods = _foods_info(conn)
    by_cart: dict[int, list[dict]] = {c["id"]: [] for c in carts}
    for lot in lots:
        f = foods[lot["food_id"]]
        by_cart[lot["cart_id"]].append(
            lot | {k: f[k] for k in ("name", "brand", "unit", "package_qty", "food_group")}
        )
    extras: dict[int, list[dict]] = {c["id"]: [] for c in carts}
    extra_where = "WHERE cart_id = ?" if cart_id is not None else ""
    for x in conn.execute(
        f"SELECT * FROM cart_extras {extra_where} ORDER BY position, id", params
    ):
        extras[x["cart_id"]].append(x)
    out = []
    for c in carts:
        items, others = by_cart[c["id"]], extras[c["id"]]
        prices = [it["price"] for it in [*items, *others] if it["price"] is not None]
        subtotal = sum(prices) if prices else None
        off = _discount_amount(subtotal or 0, c["discount"], c["discount_pct"])
        fee = c["delivery_fee"]
        total = None
        if subtotal is not None or fee is not None:
            total = (subtotal or 0) - off + (fee or 0)
        out.append(
            c
            | {
                "items": items,
                "extras": others,
                "subtotal": subtotal,
                "discount_amount": off,
                "total_price": total,
            }
        )
    return out


def _discount_amount(subtotal: float, discount: float | None, pct: float | None) -> float:
    if discount is not None:
        return discount
    if pct is not None:
        return round(subtotal * pct / 100, 2)
    return 0


def _cart(conn: sqlite3.Connection, cart_id: int) -> dict:
    found = _carts(conn, cart_id)
    if not found:
        raise _not_found("cart")
    return found[0]


@router.get("/groceries", response_model=Groceries)
def read_groceries(
    conn: Conn, days: Annotated[int, Query(ge=1, le=MAX_HISTORY_DAYS)] = 30
) -> dict:
    """Every food ever bought with what's left of it (foods that ran out have no
    lots), every cart, and what expired in the last ``days`` days."""
    lots = conn.execute(
        _LOT_LEFT
        + """ GROUP BY l.id
             ORDER BY l.expires_on IS NULL, l.expires_on, c.bought_on, l.id"""
    ).fetchall()
    by_food: dict[int, list[dict]] = {}
    for lot in lots:
        by_food.setdefault(lot["food_id"], []).append(lot)
    foods = _foods_info(conn)
    items = []
    for food_id, food_lots in by_food.items():
        f = foods[food_id]
        open_lots = [lot for lot in food_lots if lot["remaining"] > EPS]
        expiries = [lot["expires_on"] for lot in open_lots if lot["expires_on"]]
        last = max(food_lots, key=lambda lot: (lot["bought_on"], lot["id"]))
        items.append(
            {
                "food_id": food_id,
                **{k: f[k] for k in ("name", "brand", "unit", "serving_qty", "package_qty")},
                "food_group": f["food_group"],
                "in_stock": sum(lot["remaining"] for lot in open_lots),
                "next_expiry": min(expiries, default=None),
                "last_bought": last["bought_on"],
                "last_quantity": last["quantity"],
                "lots": open_lots,
            }
        )
    items.sort(key=lambda it: (it["name"].casefold(), it["brand"].casefold()))

    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    expired = conn.execute(
        """SELECT u.id, u.lot_id, l.cart_id, u.day, l.food_id, u.quantity
           FROM stock_uses u JOIN stock_lots l ON l.id = u.lot_id
           WHERE u.kind = 'expired' AND u.day >= ?
           ORDER BY u.day DESC, u.created_at DESC, u.id DESC LIMIT 500""",
        (since,),
    ).fetchall()
    for ev in expired:
        f = foods[ev["food_id"]]
        ev.update(name=f["name"], brand=f["brand"], unit=f["unit"], food_group=f["food_group"])
    return {"items": items, "carts": _carts(conn), "expired": expired}


def _fill_shortfalls(conn: sqlite3.Connection, food_id: int, since: str) -> None:
    """Entries of a food logged on or after ``since`` that couldn't take all they ate
    (nothing was in stock yet) take the rest now, oldest first. This way a cart
    entered a few days late still covers what was eaten from it meanwhile."""
    rows = conn.execute(
        """SELECT e.id, e.day, e.quantity - COALESCE(SUM(u.quantity), 0) AS short
           FROM food_entries e LEFT JOIN stock_uses u ON u.entry_id = e.id
           WHERE e.food_id = ? AND e.day >= ? AND e.quantity IS NOT NULL
           GROUP BY e.id HAVING short > ? ORDER BY e.day, e.created_at, e.id""",
        (food_id, since, EPS),
    ).fetchall()
    for e in rows:
        _take_from_lots(conn, e["id"], food_id, e["day"], e["short"])


def _store_cart_items(conn: sqlite3.Connection, cart_id: int, cart: CartIn) -> set[int]:
    """Makes the cart's lots match ``cart.items``: items with an id update that lot,
    the others are added, and lots left out are removed. Its other items are replaced,
    and its discount checked against the new subtotal. Returns the foods touched."""
    prices = [it.price for it in [*cart.items, *cart.extras] if it.price is not None]
    subtotal = sum(prices)
    if cart.discount is not None and cart.discount > subtotal + EPS:
        raise HTTPException(
            UNPROCESSABLE,
            f"the discount ({cart.discount:g}) is more than the cart's subtotal ({subtotal:g})",
        )
    conn.execute(
        "UPDATE carts SET discount = ?, discount_pct = ?, delivery_fee = ? WHERE id = ?",
        (cart.discount, cart.discount_pct, cart.delivery_fee, cart_id),
    )
    conn.execute("DELETE FROM cart_extras WHERE cart_id = ?", (cart_id,))
    conn.executemany(
        "INSERT INTO cart_extras (cart_id, name, quantity, unit, price, position) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(cart_id, x.name, x.quantity, x.unit, x.price, i) for i, x in enumerate(cart.extras)],
    )
    old = {
        lot["id"]: lot
        for lot in conn.execute(
            _LOT_LEFT + " WHERE l.cart_id = ? GROUP BY l.id", (cart_id,)
        ).fetchall()
    }
    ids = [it.id for it in cart.items if it.id is not None]
    if len(ids) != len(set(ids)):
        raise HTTPException(UNPROCESSABLE, "an item appears twice in the cart")
    if strangers := set(ids) - old.keys():
        raise HTTPException(
            UNPROCESSABLE, f"not in this cart: item {', '.join(map(str, sorted(strangers)))}"
        )
    if cart.items:
        _food_exists(conn, {it.food_id for it in cart.items})
    foods = _foods_info(conn)
    for gone in old.keys() - set(ids):
        conn.execute("DELETE FROM stock_lots WHERE id = ?", (gone,))
    for pos, it in enumerate(cart.items):
        expires = it.expires_on.isoformat() if it.expires_on else None
        if it.id is None:
            conn.execute(
                "INSERT INTO stock_lots (cart_id, food_id, quantity, expires_on, price, position)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (cart_id, it.food_id, it.quantity, expires, it.price, pos),
            )
            continue
        lot = old[it.id]
        f = foods[lot["food_id"]]
        if it.food_id != lot["food_id"]:
            raise HTTPException(
                UNPROCESSABLE, f"an item's food can't change (it's {f['name']}): remove it instead"
            )
        used = lot["eaten"] + lot["expired"]
        if it.quantity < used - EPS:
            raise HTTPException(
                UNPROCESSABLE,
                f"{f['name']}: {used:g} {f['unit']} of it is already used; "
                "the amount bought can't be less than that",
            )
        conn.execute(
            "UPDATE stock_lots SET quantity = ?, expires_on = ?, price = ?, position = ? "
            "WHERE id = ?",
            (it.quantity, expires, it.price, pos, it.id),
        )
    return {lot["food_id"] for lot in old.values()} | {it.food_id for it in cart.items}


@router.post("/groceries/carts", response_model=Cart, status_code=status.HTTP_201_CREATED)
def create_cart(cart: CartIn, conn: Conn) -> dict:
    """Log a trip to the shops: each item goes into the stock. Foods already logged
    on or after that day, while none were in stock, are taken from it."""
    _not_future(cart.bought_on)
    for it in cart.items:
        if it.id is not None:
            raise HTTPException(UNPROCESSABLE, "a new cart's items have no id yet")
    cur = conn.execute(
        "INSERT INTO carts (bought_on, store) VALUES (?, ?)",
        (cart.bought_on.isoformat(), cart.store),
    )
    for food_id in _store_cart_items(conn, cur.lastrowid, cart):
        _fill_shortfalls(conn, food_id, cart.bought_on.isoformat())
    return _cart(conn, cur.lastrowid)


@router.get("/groceries/carts/{cart_id}", response_model=Cart)
def read_cart(cart_id: int, conn: Conn) -> dict:
    return _cart(conn, cart_id)


@router.put("/groceries/carts/{cart_id}", response_model=Cart)
def update_cart(cart_id: int, cart: CartIn, conn: Conn) -> dict:
    """Change a cart: its day and store, and its items (send every item; those with
    an ``id`` are kept and updated, new ones have none, missing ones are removed).
    An item can't be made smaller than what was already eaten or thrown out of it."""
    old = _cart(conn, cart_id)
    _not_future(cart.bought_on)
    day = cart.bought_on.isoformat()
    conn.execute(
        "UPDATE carts SET bought_on = ?, store = ?, updated_at = datetime('now') WHERE id = ?",
        (day, cart.store, cart_id),
    )
    foods = _store_cart_items(conn, cart_id, cart)
    # Bought later than thought: what was eaten before that day didn't come from it.
    conn.execute(
        "DELETE FROM stock_uses WHERE kind = 'eaten' AND day < ? "
        "AND lot_id IN (SELECT id FROM stock_lots WHERE cart_id = ?)",
        (day, cart_id),
    )
    for food_id in foods:
        _fill_shortfalls(conn, food_id, min(day, old["bought_on"]))
    return _cart(conn, cart_id)


@router.delete("/groceries/carts/{cart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart(cart_id: int, conn: Conn) -> Response:
    """Everything in it leaves the stock. Logged entries stay as they are; what they
    ate from it is taken from other carts, if there's any."""
    old = _cart(conn, cart_id)
    conn.execute("DELETE FROM carts WHERE id = ?", (cart_id,))
    for food_id in {it["food_id"] for it in old["items"]}:
        _fill_shortfalls(conn, food_id, old["bought_on"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _lot_unit(conn: sqlite3.Connection, lot: dict) -> str:
    return conn.execute("SELECT unit FROM foods WHERE id = ?", (lot["food_id"],)).fetchone()["unit"]


@router.post("/groceries/lots/{lot_id}/expired", response_model=Lot)
def expire_lot(lot_id: int, body: ExpiredIn, conn: Conn) -> dict:
    """It expired or went off: take it (or part of it) out of the stock."""
    lot = _lot_row(conn, lot_id)
    _not_future(body.day)
    if body.day.isoformat() < lot["bought_on"]:
        raise HTTPException(UNPROCESSABLE, "it can't expire before the day it was bought")
    left = lot["remaining"]
    if left <= EPS:
        raise HTTPException(UNPROCESSABLE, "nothing is left of it")
    qty = body.quantity if body.quantity is not None else left
    if qty > left + EPS:
        raise HTTPException(
            UNPROCESSABLE, f"only {left:g} {_lot_unit(conn, lot)} of it is left"
        )
    conn.execute(
        "INSERT INTO stock_uses (lot_id, kind, day, quantity) VALUES (?, 'expired', ?, ?)",
        (lot_id, body.day.isoformat(), min(qty, left)),
    )
    return _lot_row(conn, lot_id)


@router.delete("/groceries/expired/{use_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expired(use_id: int, conn: Conn) -> Response:
    """Undo marking something as expired: it's back in stock."""
    cur = conn.execute("DELETE FROM stock_uses WHERE id = ? AND kind = 'expired'", (use_id,))
    if cur.rowcount == 0:
        raise _not_found("expiry")
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
        "INSERT INTO activity_types (name, category, met, distance, emoji, steps_per_min) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (t.name, t.category, t.met, int(t.distance), t.emoji, t.steps_per_min),
    )
    return _type_row(conn, cur.lastrowid)


@router.put("/activity-types/{type_id}", response_model=ActivityType)
def update_activity_type(type_id: int, t: ActivityTypeIn, conn: Conn) -> dict:
    """Logged activities keep the name they were logged with."""
    _type_row(conn, type_id)
    _type_conflict(conn, t, type_id)
    conn.execute(
        "UPDATE activity_types SET name = ?, category = ?, met = ?, distance = ?, emoji = ?,"
        " steps_per_min = ? WHERE id = ?",
        (t.name, t.category, t.met, int(t.distance), t.emoji, t.steps_per_min, type_id),
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


@router.delete("/days/{day}", response_model=Deleted)
def clear_day(day: dt.date, conn: Conn) -> dict:
    """Everything logged for one day, as if it had never been filled in: food
    entries, activities, the check-in and the note."""
    iso = day.isoformat()
    counts = {
        key: conn.execute(f"DELETE FROM {table} WHERE day = ?", (iso,)).rowcount
        for key, table in (
            ("food_log", "food_entries"),
            ("activities", "activities"),
            ("checkins", "day_metrics"),
            ("notes", "day_notes"),
        )
    }
    return {"counts": counts}


def _drop_empty_carts(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "DELETE FROM carts WHERE id NOT IN (SELECT cart_id FROM stock_lots) "
        "AND id NOT IN (SELECT cart_id FROM cart_extras)"
    ).rowcount


# table that each wipe target empties
_WIPE_TABLES = {
    "food_log": "food_entries",
    "activities": "activities",
    "checkins": "day_metrics",
    "notes": "day_notes",
    "saved_meals": "saved_meals",
    "groceries": "carts",
    "foods": "foods",
}


@router.post("/wipe", response_model=Deleted)
def wipe(body: WipeIn, conn: Conn) -> dict:
    """Delete whole kinds of tracked data, for good (the Danger Zone)."""
    counts = {}
    for key in dict.fromkeys(body.what):  # once each, in the order given
        counts[key] = conn.execute(f"DELETE FROM {_WIPE_TABLES[key]}").rowcount
    if "foods" in counts and "saved_meals" not in counts:
        # their items went with the foods: a saved meal left empty goes too
        counts["saved_meals"] = conn.execute(
            "DELETE FROM saved_meals WHERE id NOT IN (SELECT saved_meal_id FROM saved_meal_items)"
        ).rowcount
    if "foods" in counts and "groceries" not in counts:
        counts["groceries"] = _drop_empty_carts(conn)
    return {"counts": counts}


@router.get("/days/{day}", response_model=Day)
def read_day(day: dt.date, conn: Conn, config: Config) -> dict:
    iso = day.isoformat()
    entries = conn.execute(
        _ENTRY_SELECT + " WHERE e.day = ? ORDER BY e.created_at, e.id", (iso,)
    ).fetchall()
    activities = conn.execute(
        "SELECT * FROM activities WHERE day = ? "
        # by time of day when given; the rest in the order they were logged
        "ORDER BY start_time IS NULL, start_time, created_at, id",
        (iso,),
    ).fetchall()
    totals = Macros(**{k: sum(e[k] for e in entries) for k in MACRO_FIELDS})
    last = _last_weight(conn, iso)
    weight = _estimate_weight(last, config)
    metrics = _metrics(conn, iso)
    covered = _steps_covered(conn, iso, iso).get(iso, 0)
    steps = steps_burn(metrics["steps"], covered, weight)
    return {
        "day": day,
        "entries": entries,
        "activities": activities,
        "totals": totals,
        "burned_kcal": sum(a["kcal"] for a in activities) + steps["kcal"],
        "active_min": sum(a["duration_min"] for a in activities) + steps["min"],
        "steps_burn": steps,
        "metrics": metrics,
        "note": _note(conn, iso),
        "previous_weight": _last_weight(conn, iso, before=True),
        "estimate_weight_kg": weight,
        "targets": _targets_on(_target_periods(conn), iso),
    }


def _steps_covered(conn: sqlite3.Connection, start: str, end: str) -> dict[str, float]:
    """Per day, the steps that its logged on-foot activities account for: minutes x
    their type's steps per minute (types matched by name, as when estimating kcal)."""
    return {
        r["day"]: r["covered"]
        for r in conn.execute(
            """SELECT a.day, SUM(a.duration_min * t.steps_per_min) AS covered
               FROM activities a JOIN activity_types t ON t.name = a.type
               WHERE a.day BETWEEN ? AND ? AND t.steps_per_min IS NOT NULL
               GROUP BY a.day""",
            (start, end),
        )
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
    config: Config,
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
    covered = _steps_covered(conn, *span)
    last = _last_weight(conn, span[0], before=True)  # updated as days go by
    out = []
    for i in range((end - start).days + 1):
        d = start + dt.timedelta(days=i)
        iso = d.isoformat()
        f, a, m = food.get(iso), act.get(iso), metrics.get(iso)
        if m and m["weight_kg"] is not None:
            last = m
        steps = steps_burn(
            m["steps"] if m else None, covered.get(iso, 0), _estimate_weight(last, config)
        )
        out.append(
            HistoryDay(
                day=d,
                entry_count=f["n"] if f else 0,
                burned_kcal=(a["kcal"] if a else 0) + steps["kcal"],
                active_min=(a["mins"] if a else 0) + steps["min"],
                **({k: f[k] for k in MACRO_FIELDS} if f else {}),
                **({k: m[k] for k in METRIC_FIELDS} if m else {}),
                has_note=iso in noted,
                targets=_targets_on(periods, iso),
            )
        )
    return out
