from __future__ import annotations

import datetime as dt

import pytest

from pamela.api import _is_due


def _r(**kw) -> dict:
    base = {"repeat": "daily", "every": 1, "weekday": None, "month_day": None}
    return base | {"start_day": "2026-01-01"} | kw


D = dt.date


def test_daily_from_its_start():
    r = _r(start_day="2026-03-10")
    assert not _is_due(r, D(2026, 3, 9))
    assert _is_due(r, D(2026, 3, 10)) and _is_due(r, D(2027, 1, 1))


def test_weekly_every_so_many_weeks():
    # 2026-03-11 is a Wednesday: the first Monday on or after it is 03-16
    r = _r(repeat="weekly", weekday=0, every=2, start_day="2026-03-11")
    due = [d for d in (D(2026, 3, 16) + dt.timedelta(days=i) for i in range(35)) if _is_due(r, d)]
    assert due == [D(2026, 3, 16), D(2026, 3, 30), D(2026, 4, 13)]
    assert not _is_due(r, D(2026, 3, 9))  # before the start
    weekly = _r(repeat="weekly", weekday=2, start_day="2026-03-11")
    assert _is_due(weekly, D(2026, 3, 11)) and _is_due(weekly, D(2026, 3, 18))
    assert not _is_due(weekly, D(2026, 3, 12))


def test_monthly_on_a_day_or_the_last_one():
    r = _r(repeat="monthly", month_day=31)
    assert _is_due(r, D(2026, 1, 31)) and _is_due(r, D(2026, 2, 28))
    assert _is_due(r, D(2026, 4, 30)) and not _is_due(r, D(2026, 4, 29))
    assert _is_due(_r(repeat="monthly", month_day=15), D(2026, 6, 15))


@pytest.fixture
def lentils(client) -> dict:
    return client.post("/api/foods", json={"name": "Lentils", "kcal": 116}).json()


def test_reminder_crud_and_day(client, lentils, oats):
    today = dt.date.today().isoformat()
    body = {"food_id": lentils["id"], "repeat": "daily", "start_day": today, "note": "iron"}
    r = client.post("/api/reminders", json=body)
    assert r.status_code == 201, r.text
    rem = r.json()
    assert rem["name"] == "Lentils" and rem["next_day"] == today and rem["weekday"] is None

    day = client.get(f"/api/days/{today}").json()
    assert [(x["name"], x["done"]) for x in day["reminders"]] == [("Lentils", False)]

    # something else doesn't tick it off; the food itself does
    client.post(
        "/api/entries", json={"day": today, "meal": "Lunch", "food_id": oats["id"], "quantity": 50}
    )
    assert not client.get(f"/api/days/{today}").json()["reminders"][0]["done"]
    client.post(
        "/api/entries",
        json={"day": today, "meal": "Lunch", "food_id": lentils["id"], "quantity": 200},
    )
    assert client.get(f"/api/days/{today}").json()["reminders"][0]["done"]
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    assert client.get("/api/reminders").json()[0]["next_day"] == tomorrow

    # weekly needs its weekday; what it doesn't use is dropped
    bad = client.put(f"/api/reminders/{rem['id']}", json=body | {"repeat": "weekly"})
    assert bad.status_code == 422
    upd = client.put(
        f"/api/reminders/{rem['id']}",
        json=body | {"repeat": "monthly", "month_day": 5, "weekday": 3},
    )
    assert upd.status_code == 200 and upd.json()["weekday"] is None and upd.json()["month_day"] == 5

    # a food and a meal at once, or neither, is refused; an unknown food is not found
    assert client.post("/api/reminders", json=body | {"saved_meal_id": 1}).status_code == 422
    assert client.post("/api/reminders", json=body | {"food_id": None}).status_code == 422
    assert client.post("/api/reminders", json=body | {"food_id": 999}).status_code == 404

    # it goes with its food
    client.delete(f"/api/foods/{lentils['id']}")
    assert client.get("/api/reminders").json() == []


def test_meal_and_meta_reminders(client, oats):
    today = dt.date.today().isoformat()
    meta = client.post("/api/foods", json={"name": "Oats", "is_meta": True, "kcal": 380}).json()
    client.put(
        f"/api/foods/{oats['id']}",
        json={k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "kcal")}
        | {"meta_id": meta["id"]},
    )
    meal = client.post(
        "/api/saved-meals",
        json={"name": "Porridge", "items": [{"food_id": oats["id"], "quantity": 60}]},
    ).json()
    for target in ({"food_id": meta["id"]}, {"saved_meal_id": meal["id"]}):
        assert (
            client.post(
                "/api/reminders", json=target | {"repeat": "daily", "start_day": today}
            ).status_code
            == 201
        )

    names = {x["name"]: x["done"] for x in client.get(f"/api/days/{today}").json()["reminders"]}
    assert names == {"Oats": False, "Porridge": False}
    # logging the meal ticks off both: it's from the meal, and its oats are one of "Oats"
    item = {"food_id": oats["id"], "quantity": 60}
    batch = {"day": today, "meal": "Breakfast", "saved_meal_id": meal["id"], "items": [item]}
    r = client.post("/api/entries/batch", json=batch)
    assert r.status_code == 201, r.text
    assert all(x["done"] for x in client.get(f"/api/days/{today}").json()["reminders"])

    assert client.post("/api/wipe", json={"what": ["reminders"]}).json()["counts"] == {
        "reminders": 2
    }
