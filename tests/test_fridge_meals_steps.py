"""The Fridge tab's sectors, what a meal needs from Groceries, and steps counting
towards burned kcal and active time."""

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


# --- fridge ------------------------------------------------------------------


def move(client, food_id, frm, to, quantity=None, status=200) -> dict:
    r = client.post(
        "/api/fridge/move",
        json={"food_id": food_id, "from_sector_id": frm, "to_sector_id": to, "quantity": quantity},
    )
    assert r.status_code == status, r.text
    return r.json()


def where(fr) -> dict[str | None, list[tuple]]:
    """Sector name (None = no sector) -> [(food, amount, main)]."""
    out = {
        s["name"]: [(f["name"], f["quantity"], f["main"]) for f in s["foods"]]
        for s in fr["sectors"]
    }
    out[None] = [(f["name"], f["quantity"], f["main"]) for f in fr["unsorted"]]
    return out


def sector(client, name, emoji="") -> int:
    r = client.post("/api/fridge/sectors", json={"name": name, "emoji": emoji})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_sectors_and_moving_whole_foods(client, oats):
    milk = food(client, "Milk", "ml")
    buy(client, oats["id"], 500)
    buy(client, milk["id"], 1000)

    fr = client.get("/api/fridge").json()
    assert fr["sectors"] == []
    assert where(fr)[None] == [("Milk", 1000, False), ("Rolled oats", 500, False)]

    door = sector(client, "Door", "🚪")
    pantry = sector(client, "Pantry")
    fr = move(client, milk["id"], None, door)
    assert [s["name"] for s in fr["sectors"]] == ["Door", "Pantry"]  # in the order made
    assert where(fr)["Door"] == [("Milk", 1000, True)]
    assert where(fr)[None] == [("Rolled oats", 500, False)]

    fr = move(client, milk["id"], door, pantry)
    assert where(fr)["Door"] == [] and where(fr)["Pantry"] == [("Milk", 1000, True)]

    fr = client.put("/api/fridge/order", json={"ids": [pantry, door]}).json()
    assert [s["name"] for s in fr["sectors"]] == ["Pantry", "Door"]
    assert client.put("/api/fridge/order", json={"ids": [pantry]}).status_code == 422

    r = client.put(f"/api/fridge/sectors/{door}", json={"name": "Fridge door"})
    assert r.json()["name"] == "Fridge door" and r.json()["emoji"] == ""

    fr = move(client, milk["id"], pantry, None)
    assert where(fr)[None] == [("Milk", 1000, False), ("Rolled oats", 500, False)]

    move(client, 999, None, door, status=404)
    move(client, milk["id"], None, 999, status=404)
    move(client, milk["id"], door, pantry, status=422)  # it isn't there
    move(client, milk["id"], None, None, status=422)


def test_a_food_split_over_sectors(client):
    milk = food(client, "Milk", "ml")
    buy(client, milk["id"], 1000)
    shelf, door, freezer = (
        sector(client, "Shelf"),
        sector(client, "Door"),
        sector(client, "Freezer"),
    )
    move(client, milk["id"], None, shelf)
    fr = move(client, milk["id"], shelf, door, 300)
    assert where(fr)["Shelf"] == [("Milk", 700, True)]
    assert where(fr)["Door"] == [("Milk", 300, False)]
    assert fr["sectors"][0]["foods"][0]["places"] == 2

    fr = move(client, milk["id"], shelf, door, 100)  # adds to what's there
    assert where(fr)["Door"] == [("Milk", 400, False)]
    fr = move(client, milk["id"], door, freezer, 150)
    assert where(fr)["Door"] == [("Milk", 250, False)]
    assert where(fr)["Freezer"] == [("Milk", 150, False)]
    move(client, milk["id"], door, freezer, 251, status=422)  # more than is there

    # taking a part out sends it back to the main place
    fr = move(client, milk["id"], freezer, None)
    assert where(fr)["Shelf"] == [("Milk", 750, True)] and where(fr)["Freezer"] == []
    move(client, milk["id"], shelf, None, 10, status=422)

    # Groceries says where it is
    item = client.get("/api/groceries").json()["items"][0]
    assert [(p["name"], p["quantity"], p["main"]) for p in item["places"]] == [
        ("Shelf", 750, True),
        ("Door", 250, False),
    ]

    # moving all of the main place moves the main place
    fr = move(client, milk["id"], shelf, door)
    assert where(fr)["Shelf"] == [] and where(fr)["Door"] == [("Milk", 1000, True)]


def test_eating_and_buying_with_a_split_food(client):
    milk = food(client, "Milk", "ml")
    buy(client, milk["id"], 1000, day=D[5])
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, milk["id"], None, shelf)
    move(client, milk["id"], shelf, door, 400)

    def drink(q):
        r = client.post(
            "/api/entries",
            json={"day": D[1], "meal": "Breakfast", "food_id": milk["id"], "quantity": q},
        )
        assert r.status_code == 201

    drink(500)  # the main place empties first, then the set amount gives way
    fr = client.get("/api/fridge").json()
    assert where(fr)["Shelf"] == [("Milk", 100, True)] and where(fr)["Door"] == [
        ("Milk", 400, False)
    ]
    drink(300)
    fr = client.get("/api/fridge").json()
    assert where(fr)["Shelf"] == [("Milk", 0, True)] and where(fr)["Door"] == [("Milk", 200, False)]
    # a new carton goes to the main place, not back to the door
    buy(client, milk["id"], 1000, day=D[1])
    fr = client.get("/api/fridge").json()
    assert where(fr)["Shelf"] == [("Milk", 1000, True)] and where(fr)["Door"] == [
        ("Milk", 200, False)
    ]


def test_food_that_ran_out_keeps_its_sector(client, oats):
    buy(client, oats["id"], 100)
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, oats["id"], None, shelf)
    move(client, oats["id"], shelf, door, 60)
    fr = move(client, oats["id"], shelf, None)  # no main place any more
    assert where(fr)[None] == [("Rolled oats", 40, False)]
    client.post(
        "/api/entries",
        json={"day": D[1], "meal": "Breakfast", "food_id": oats["id"], "quantity": 100},
    )
    fr = client.get("/api/fridge").json()
    # ran out: its last place becomes its main one, so it goes back there
    assert where(fr)["Door"] == [("Rolled oats", 0, True)]
    assert fr["unsorted"] == []  # foods that ran out aren't listed as unsorted
    buy(client, oats["id"], 300, day=D[0])
    assert where(client.get("/api/fridge").json())["Door"] == [("Rolled oats", 300, True)]


def test_deleting_a_sector_or_food(client, oats):
    buy(client, oats["id"], 100)
    shelf = sector(client, "Shelf")
    move(client, oats["id"], None, shelf)
    assert client.delete(f"/api/fridge/sectors/{shelf}").status_code == 204
    assert client.delete(f"/api/fridge/sectors/{shelf}").status_code == 404
    fr = client.get("/api/fridge").json()
    assert fr["sectors"] == [] and where(fr)[None] == [("Rolled oats", 100, False)]

    shelf = sector(client, "Shelf")
    move(client, oats["id"], None, shelf)
    client.delete(f"/api/foods/{oats['id']}")
    assert client.get("/api/fridge").json()["sectors"][0]["foods"] == []

    r = client.post("/api/wipe", json={"what": ["fridge"]})
    assert r.json()["counts"] == {"fridge": 1}
    assert client.get("/api/fridge").json()["sectors"] == []


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
