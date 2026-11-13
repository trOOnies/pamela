"""What a meal needs from Groceries, and steps counting towards burned kcal and
active time."""

from __future__ import annotations

import datetime as dt

import pytest

from pamela.tracking import STEP_CADENCE, STEP_MET

TODAY = dt.date.today()
D = [(TODAY - dt.timedelta(days=n)).isoformat() for n in range(10)]  # D[0] = today


def buy(client, food_id, quantity, day=D[5]) -> None:
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": day, "items": [{"food_id": food_id, "quantity": quantity}]},
    )
    assert r.status_code == 201, r.text


def food(client, name, unit="g", **kw) -> dict:
    r = client.post("/api/foods", json={"name": name, "unit": unit, "kcal": 100} | kw)
    assert r.status_code == 201, r.text
    return r.json()


# --- meals ---------------------------------------------------------------------


def test_meal_recipe_and_what_is_in_stock(client, oats):
    milk = food(client, "Milk", "ml", package_qty=1000)
    body = {
        "name": "Porridge",
        "items": [
            {"food_id": oats["id"], "quantity": 60},
            {"food_id": milk["id"], "quantity": 250},
        ],
        "recipe": "Simmer 5 min.\nStir.",
    }
    sm = client.post("/api/saved-meals", json=body).json()
    assert sm["recipe"] == "Simmer 5 min.\nStir."
    assert sm["can_make"] is False
    assert [(it["in_stock"], it["missing"]) for it in sm["items"]] == [(0, 60), (0, 250)]

    buy(client, oats["id"], 500)
    buy(client, milk["id"], 100)
    sm = client.get(f"/api/saved-meals/{sm['id']}").json()
    assert sm["can_make"] is False
    assert [(it["in_stock"], it["missing"]) for it in sm["items"]] == [(500, 0), (100, 150)]

    buy(client, milk["id"], 1000)
    sm = client.get(f"/api/saved-meals/{sm['id']}").json()
    assert sm["can_make"] is True
    assert all(it["missing"] == 0 for it in sm["items"])

    r = client.put(f"/api/saved-meals/{sm['id']}", json=body | {"recipe": ""})
    assert r.json()["recipe"] == ""


def test_meal_with_a_food_twice_shares_the_stock(client, oats):
    buy(client, oats["id"], 100)
    sm = client.post(
        "/api/saved-meals",
        json={
            "name": "Double oats",
            "items": [
                {"food_id": oats["id"], "quantity": 80},
                {"food_id": oats["id"], "quantity": 50},
            ],
        },
    ).json()
    assert [it["missing"] for it in sm["items"]] == [0, 30]
    assert sm["can_make"] is False


# --- steps -----------------------------------------------------------------------


def steps_kcal(steps, weight=75.0):
    return STEP_MET * weight * (steps / STEP_CADENCE) / 60


def test_steps_add_to_burned_and_active(client):
    day = D[1]
    client.put(f"/api/days/{day}/metrics", json={"steps": 5000})
    d = client.get(f"/api/days/{day}").json()
    assert d["steps_burn"]["steps"] == 5000
    assert d["steps_burn"]["min"] == pytest.approx(5000 / STEP_CADENCE)
    assert d["burned_kcal"] == pytest.approx(steps_kcal(5000))
    assert d["active_min"] == pytest.approx(50)

    # an activity done on foot already accounts for its steps
    walking = next(t for t in client.get("/api/activity-types").json() if t["name"] == "Walking")
    assert walking["steps_per_min"] == 100
    client.post(
        "/api/activities", json={"day": day, "type": "Walking", "duration_min": 20, "kcal": 90}
    )
    d = client.get(f"/api/days/{day}").json()
    assert d["steps_burn"]["steps"] == 3000
    assert d["burned_kcal"] == pytest.approx(90 + steps_kcal(3000))
    assert d["active_min"] == pytest.approx(20 + 30)

    # one that isn't on foot doesn't
    yoga = {"day": day, "type": "Yoga", "duration_min": 30, "kcal": 80}
    client.post("/api/activities", json=yoga)
    d = client.get(f"/api/days/{day}").json()
    assert d["steps_burn"]["steps"] == 3000
    assert d["active_min"] == pytest.approx(20 + 30 + 30)

    # the same numbers in History
    h = client.get("/api/history", params={"start": day, "end": day}).json()[0]
    assert h["burned_kcal"] == pytest.approx(d["burned_kcal"])
    assert h["active_min"] == pytest.approx(d["active_min"])


def test_more_logged_on_foot_than_steps_adds_nothing(client):
    day = D[1]
    client.put(f"/api/days/{day}/metrics", json={"steps": 1000})
    client.post(
        "/api/activities", json={"day": day, "type": "Running", "duration_min": 30, "kcal": 300}
    )
    d = client.get(f"/api/days/{day}").json()
    assert d["steps_burn"] == {"steps": 0, "min": 0, "kcal": 0}
    assert d["burned_kcal"] == 300 and d["active_min"] == 30


def test_steps_use_that_days_weight(client):
    client.put(f"/api/days/{D[5]}/metrics", json={"weight_kg": 100})
    client.put(f"/api/days/{D[3]}/metrics", json={"steps": 6000})
    client.put(f"/api/days/{D[2]}/metrics", json={"weight_kg": 50, "steps": 6000})
    d = client.get(f"/api/days/{D[3]}").json()
    assert d["burned_kcal"] == pytest.approx(steps_kcal(6000, 100))
    days = client.get("/api/history", params={"start": D[4], "end": D[2]}).json()
    h = {x["day"]: x for x in days}
    assert h[D[3]]["burned_kcal"] == pytest.approx(steps_kcal(6000, 100))
    assert h[D[2]]["burned_kcal"] == pytest.approx(steps_kcal(6000, 50))
    assert h[D[4]]["burned_kcal"] == 0


def test_steps_per_min_on_exercise_types(client):
    r = client.post(
        "/api/activity-types",
        json={"name": "Treadmill hike", "met": 6, "steps_per_min": 110},
    )
    assert r.status_code == 201 and r.json()["steps_per_min"] == 110
    t = r.json()
    r = client.put(f"/api/activity-types/{t['id']}", json={"name": "Treadmill hike", "met": 6})
    assert r.json()["steps_per_min"] is None
    r = client.post("/api/activity-types", json={"name": "x", "met": 6, "steps_per_min": 0})
    assert r.status_code == 422
