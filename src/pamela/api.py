"""JSON API mounted under ``/api``."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from . import db
from .config import AppConfig
from .schemas import (
    MACRO_FIELDS,
    Activity,
    ActivityIn,
    Day,
    Entry,
    EntryIn,
    Food,
    FoodIn,
    HistoryDay,
    Macros,
)
from .tracking import estimate_kcal, scale_macros

router = APIRouter(prefix="/api")

MAX_HISTORY_DAYS = 366
UNPROCESSABLE = 422


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


# --- config ------------------------------------------------------------------


@router.get("/config", response_model=AppConfig)
def read_config(config: Config) -> AppConfig:
    return config


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

    ``q`` matches every whitespace-separated word against name or brand."""
    where, params = [], []
    for word in q.split():
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(f.name LIKE ? ESCAPE '\\' OR f.brand LIKE ? ESCAPE '\\')")
        params += [like, like]
    sql = _FOOD_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY uses DESC, f.name COLLATE NOCASE LIMIT ?"
    return conn.execute(sql, (*params, limit)).fetchall()


@router.post("/foods", response_model=Food, status_code=status.HTTP_201_CREATED)
def create_food(food: FoodIn, conn: Conn) -> dict:
    data = food.model_dump()
    cols = ", ".join(data)
    marks = ", ".join("?" * len(data))
    cur = conn.execute(f"INSERT INTO foods ({cols}) VALUES ({marks})", tuple(data.values()))
    return _food_row(conn, cur.lastrowid)


@router.get("/foods/{food_id}", response_model=Food)
def read_food(food_id: int, conn: Conn) -> dict:
    return _food_row(conn, food_id)


@router.put("/foods/{food_id}", response_model=Food)
def update_food(food_id: int, food: FoodIn, conn: Conn) -> dict:
    data = food.model_dump()
    sets = ", ".join(f"{k} = ?" for k in data)
    cur = conn.execute(
        f"UPDATE foods SET {sets}, updated_at = datetime('now') WHERE id = ?",
        (*data.values(), food_id),
    )
    if cur.rowcount == 0:
        raise _not_found("food")
    return _food_row(conn, food_id)


@router.delete("/foods/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_food(food_id: int, conn: Conn) -> Response:
    """Logged entries keep their macro snapshot; they just lose the link."""
    if conn.execute("DELETE FROM foods WHERE id = ?", (food_id,)).rowcount == 0:
        raise _not_found("food")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- food entries ------------------------------------------------------------


def _entry_values(entry: EntryIn, conn: sqlite3.Connection, config: AppConfig) -> dict:
    if entry.meal not in config.meals.names:
        raise HTTPException(
            UNPROCESSABLE,
            f"unknown meal {entry.meal!r}; configured meals: {', '.join(config.meals.names)}",
        )
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


@router.post("/entries", response_model=Entry, status_code=status.HTTP_201_CREATED)
def create_entry(entry: EntryIn, conn: Conn, config: Config) -> dict:
    values = _entry_values(entry, conn, config)
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    cur = conn.execute(
        f"INSERT INTO food_entries ({cols}) VALUES ({marks})", tuple(values.values())
    )
    return _entry_row(conn, cur.lastrowid)


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


# --- activities --------------------------------------------------------------


def _activity_values(activity: ActivityIn, config: AppConfig) -> dict:
    values = activity.model_dump()
    values["day"] = activity.day.isoformat()
    if activity.kcal is None:
        atype = config.activity_type(activity.type)
        if atype is None:
            raise HTTPException(
                UNPROCESSABLE,
                f"unknown activity type {activity.type!r}: enter kcal manually "
                "or add the type to info/config.toml",
            )
        values["kcal"] = estimate_kcal(atype.met, config.profile.weight_kg, activity.duration_min)
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
    values = _activity_values(activity, config)
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    cur = conn.execute(f"INSERT INTO activities ({cols}) VALUES ({marks})", tuple(values.values()))
    return _activity_row(conn, cur.lastrowid)


@router.put("/activities/{activity_id}", response_model=Activity)
def update_activity(activity_id: int, activity: ActivityIn, conn: Conn, config: Config) -> dict:
    _activity_row(conn, activity_id)
    values = _activity_values(activity, config)
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE activities SET {sets} WHERE id = ?", (*values.values(), activity_id))
    return _activity_row(conn, activity_id)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(activity_id: int, conn: Conn) -> Response:
    if conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,)).rowcount == 0:
        raise _not_found("activity")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- aggregates --------------------------------------------------------------


@router.get("/days/{day}", response_model=Day)
def read_day(day: dt.date, conn: Conn) -> dict:
    iso = day.isoformat()
    entries = conn.execute(
        "SELECT * FROM food_entries WHERE day = ? ORDER BY created_at, id", (iso,)
    ).fetchall()
    activities = conn.execute(
        "SELECT * FROM activities WHERE day = ? ORDER BY created_at, id", (iso,)
    ).fetchall()
    totals = Macros(**{k: sum(e[k] for e in entries) for k in MACRO_FIELDS})
    return {
        "day": day,
        "entries": entries,
        "activities": activities,
        "totals": totals,
        "burned_kcal": sum(a["kcal"] for a in activities),
        "active_min": sum(a["duration_min"] for a in activities),
    }


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
    out = []
    for i in range((end - start).days + 1):
        d = start + dt.timedelta(days=i)
        f, a = food.get(d.isoformat()), act.get(d.isoformat())
        out.append(
            HistoryDay(
                day=d,
                entry_count=f["n"] if f else 0,
                burned_kcal=a["kcal"] if a else 0,
                active_min=a["mins"] if a else 0,
                **({k: f[k] for k in MACRO_FIELDS} if f else {}),
            )
        )
    return out
