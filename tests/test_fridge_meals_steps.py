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
    """Sector name (None = no sector) -> [(food, amount)]."""
    out = {s["name"]: [(f["name"], f["quantity"]) for f in s["foods"]] for s in fr["sectors"]}
    out[None] = [(f["name"], f["quantity"]) for f in fr["unsorted"]]
    return out


def sector(client, name, emoji="") -> int:
    r = client.post("/api/fridge/sectors", json={"name": name, "emoji": emoji})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def fridge(client) -> dict[str | None, list[tuple]]:
    return where(client.get("/api/fridge").json())


def log(client, food_id, q, meal="Lunch") -> int:
    r = client.post(
        "/api/entries", json={"day": D[1], "meal": meal, "food_id": food_id, "quantity": q}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def change(client, entry_id, food_id, q, **kw) -> None:
    body = {"day": D[1], "meal": "Lunch", "food_id": food_id, "quantity": q} | kw
    r = client.put(f"/api/entries/{entry_id}", json=body)
    assert r.status_code == 200, r.text


def test_sectors_and_moving_whole_foods(client, oats):
    milk = food(client, "Milk", "ml")
    buy(client, oats["id"], 500)
    buy(client, milk["id"], 1000)

    fr = client.get("/api/fridge").json()
    assert fr["sectors"] == []
    assert where(fr)[None] == [("Milk", 1000), ("Rolled oats", 500)]

    door = sector(client, "Door", "🚪")
    pantry = sector(client, "Pantry")
    fr = move(client, milk["id"], None, door)
    assert [s["name"] for s in fr["sectors"]] == ["Door", "Pantry"]  # in the order made
    assert where(fr)["Door"] == [("Milk", 1000)]
    assert where(fr)[None] == [("Rolled oats", 500)]

    fr = move(client, milk["id"], door, pantry)
    assert where(fr)["Door"] == [] and where(fr)["Pantry"] == [("Milk", 1000)]

    fr = client.put("/api/fridge/order", json={"ids": [pantry, door]}).json()
    assert [s["name"] for s in fr["sectors"]] == ["Pantry", "Door"]
    assert client.put("/api/fridge/order", json={"ids": [pantry]}).status_code == 422

    r = client.put(f"/api/fridge/sectors/{door}", json={"name": "Fridge door"})
    assert r.json()["name"] == "Fridge door" and r.json()["emoji"] == ""

    fr = move(client, milk["id"], pantry, None)
    assert where(fr)[None] == [("Milk", 1000), ("Rolled oats", 500)]

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
    assert where(fr)["Shelf"] == [("Milk", 700)]
    assert where(fr)["Door"] == [("Milk", 300)]
    assert fr["sectors"][0]["foods"][0]["places"] == 2

    fr = move(client, milk["id"], shelf, door, 100)  # adds to what's there
    assert where(fr)["Door"] == [("Milk", 400)]
    fr = move(client, milk["id"], door, freezer, 150)
    assert where(fr)["Door"] == [("Milk", 250)]
    assert where(fr)["Freezer"] == [("Milk", 150)]
    move(client, milk["id"], door, freezer, 251, status=422)  # more than is there

    # taking it out of a sector leaves it in no sector, all or part of it
    fr = move(client, milk["id"], freezer, None)
    assert where(fr)["Freezer"] == [] and where(fr)[None] == [("Milk", 150)]
    fr = move(client, milk["id"], shelf, None, 100)
    assert where(fr)["Shelf"] == [("Milk", 500)] and where(fr)[None] == [("Milk", 250)]
    fr = move(client, milk["id"], None, door, 50)
    assert where(fr)["Door"] == [("Milk", 300)] and where(fr)[None] == [("Milk", 200)]

    # Groceries says where it is
    item = client.get("/api/groceries").json()["items"][0]
    assert [(p["name"], p["quantity"]) for p in item["places"]] == [
        ("Shelf", 500),
        ("Door", 300),
    ]


def test_food_bought_goes_to_no_sector(client):
    milk = food(client, "Milk", "ml")
    buy(client, milk["id"], 1000, day=D[5])
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, milk["id"], None, shelf)
    move(client, milk["id"], shelf, door, 400)
    log(client, milk["id"], 500)  # the Shelf comes first
    assert fridge(client)["Shelf"] == [("Milk", 100)]
    assert fridge(client)["Door"] == [("Milk", 400)]
    # a new carton isn't in a sector until it's put away, even where the milk already is
    buy(client, milk["id"], 1000, day=D[1])
    w = fridge(client)
    assert (w["Shelf"], w["Door"], w[None]) == ([("Milk", 100)], [("Milk", 400)], [("Milk", 1000)])


def test_eating_takes_from_sectors_by_priority(client):
    milk = food(client, "Milk", "ml")
    buy(client, milk["id"], 1000)
    outside, attic = sector(client, "Outside"), sector(client, "Attic")
    move(client, milk["id"], None, attic)
    move(client, milk["id"], attic, outside, 300)

    def spots():
        w = fridge(client)
        return w["Outside"], w["Attic"]

    entry = log(client, milk["id"], 200)  # the first sector goes first
    assert spots() == ([("Milk", 100)], [("Milk", 700)])

    # changing the entry: eating more takes the extra by priority too...
    change(client, entry, milk["id"], 250)
    assert spots() == ([("Milk", 50)], [("Milk", 700)])
    # ...past the first sector into the next
    change(client, entry, milk["id"], 400)
    assert spots() == ([], [("Milk", 600)])
    # eating less gives it back where it came from, the last sector it ate from first
    change(client, entry, milk["id"], 250)
    assert spots() == ([("Milk", 50)], [("Milk", 700)])
    change(client, entry, milk["id"], 100)
    assert spots() == ([("Milk", 200)], [("Milk", 700)])

    # a saved meal's foods follow the same order
    r = client.post(
        "/api/entries/batch",
        json={"day": D[1], "meal": "Dinner", "items": [{"food_id": milk["id"], "quantity": 250}]},
    )
    assert r.status_code == 201, r.text
    assert spots() == ([], [("Milk", 650)])

    # the order is the user's: put Attic first and it goes first
    move(client, milk["id"], attic, outside, 250)
    client.put("/api/fridge/order", json={"ids": [attic, outside]})
    log(client, milk["id"], 100)
    assert spots() == ([("Milk", 250)], [("Milk", 300)])


def test_deleting_what_was_eaten_puts_it_back(client):
    milk = food(client, "Milk", "ml")
    buy(client, milk["id"], 1000)
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, milk["id"], None, shelf, 300)
    move(client, milk["id"], None, door, 300)  # 400 in no sector
    entry = log(client, milk["id"], 800)  # 300 from each sector, 200 from no sector
    assert fridge(client) == {"Shelf": [], "Door": [], None: [("Milk", 200)]}
    assert client.delete(f"/api/entries/{entry}").status_code == 204
    full = {"Shelf": [("Milk", 300)], "Door": [("Milk", 300)], None: [("Milk", 400)]}
    assert fridge(client) == full

    # eaten out: it gives back what it took; changed to another food, too
    entry = log(client, milk["id"], 100)
    change(client, entry, milk["id"], 100, eaten_out=True)
    assert fridge(client)["Shelf"] == [("Milk", 300)]
    change(client, entry, milk["id"], 100)
    assert fridge(client)["Shelf"] == [("Milk", 200)]
    water = food(client, "Water", "ml")
    change(client, entry, water["id"], 100)
    assert fridge(client)["Shelf"] == [("Milk", 300)]
    client.delete(f"/api/entries/{entry}")

    # a logged saved meal, a cleared day, a wiped food log: all put it back
    items = [{"food_id": milk["id"], "quantity": 350}]
    sm = client.post("/api/saved-meals", json={"name": "Glass", "items": items}).json()
    batch = {"day": D[1], "meal": "Dinner", "saved_meal_id": sm["id"], "items": items}
    logged = client.post("/api/entries/batch", json=batch).json()
    assert fridge(client)["Shelf"] == [] and fridge(client)["Door"] == [("Milk", 250)]
    client.delete(f"/api/meal-logs/{logged[0]['meal_log_id']}")
    assert fridge(client)["Shelf"] == [("Milk", 300)] and fridge(client)["Door"] == [("Milk", 300)]
    log(client, milk["id"], 350)
    client.delete(f"/api/days/{D[1]}")
    assert fridge(client)["Shelf"] == [("Milk", 300)] and fridge(client)["Door"] == [("Milk", 300)]
    log(client, milk["id"], 350)
    client.post("/api/wipe", json={"what": ["food_log"]})
    assert fridge(client)["Shelf"] == [("Milk", 300)] and fridge(client)["Door"] == [("Milk", 300)]

    # a sector deleted meanwhile: it goes back to no sector
    entry = log(client, milk["id"], 300)
    client.delete(f"/api/fridge/sectors/{shelf}")
    client.delete(f"/api/entries/{entry}")
    assert fridge(client) == {"Door": [("Milk", 300)], None: [("Milk", 700)]}


def test_throwing_out_takes_from_no_sector_first(client, oats):
    buy(client, oats["id"], 1000)
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, oats["id"], None, shelf, 300)
    move(client, oats["id"], None, door, 300)
    lot = client.get("/api/groceries").json()["items"][0]["lots"][0]["id"]

    def toss(q):
        r = client.post(f"/api/groceries/lots/{lot}/expired", json={"day": D[0], "quantity": q})
        assert r.status_code == 200, r.text

    toss(500)  # no sector first, then the newest place
    w = fridge(client)
    assert (w["Shelf"], w["Door"], w[None]) == ([("Rolled oats", 300)], [("Rolled oats", 200)], [])
    toss(200)
    assert fridge(client) == {"Shelf": [("Rolled oats", 300)], "Door": [], None: []}


def test_what_is_in_no_sector_is_eaten_last(client, oats):
    buy(client, oats["id"], 1000)
    shelf = sector(client, "Shelf")
    fr = move(client, oats["id"], None, shelf, 300)
    assert where(fr)["Shelf"] == [("Rolled oats", 300)]
    assert where(fr)[None] == [("Rolled oats", 700)]
    log(client, oats["id"], 400, meal="Breakfast")
    w = fridge(client)
    assert w["Shelf"] == [] and w[None] == [("Rolled oats", 600)]


def test_food_that_ran_out_leaves_its_sectors(client, oats):
    buy(client, oats["id"], 100)
    shelf, door = sector(client, "Shelf"), sector(client, "Door")
    move(client, oats["id"], None, shelf, 40)
    move(client, oats["id"], None, door)
    log(client, oats["id"], 100, meal="Breakfast")
    fr = client.get("/api/fridge").json()
    assert where(fr)["Door"] == [] and where(fr)["Shelf"] == []
    # it says where the last of it was eaten from
    assert [(o["name"], o["sector"]) for o in fr["recently_out"]] == [("Rolled oats", "Door")]
    assert fr["unsorted"] == []  # foods that ran out aren't listed as unsorted
    buy(client, oats["id"], 300, day=D[0])
    fr = client.get("/api/fridge").json()
    assert where(fr)["Door"] == [] and where(fr)[None] == [("Rolled oats", 300)]
    assert fr["recently_out"] == []


def test_main_places_become_set_amounts(tmp_path):
    """Migration 27: a main place keeps what it held; an emptied one goes."""
    from pamela import db

    path = tmp_path / "old.sqlite3"
    conn = db.connect(path)
    for i, script in enumerate(db.MIGRATIONS[:26], start=1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")
    conn.executescript("""
        INSERT INTO foods (id, name) VALUES (1, 'Milk'), (2, 'Oats');
        INSERT INTO carts (id, bought_on) VALUES (1, '2026-01-01');
        INSERT INTO stock_lots (id, cart_id, food_id, quantity)
            VALUES (1, 1, 1, 1000), (2, 1, 2, 50);
        INSERT INTO stock_uses (lot_id, kind, day, quantity)
            VALUES (1, 'expired', '2026-01-02', 100), (2, 'expired', '2026-01-02', 50);
        INSERT INTO fridge_sectors (id, name) VALUES (1, 'Shelf'), (2, 'Door');
        INSERT INTO fridge_places (food_id, sector_id, quantity) VALUES (1, 1, NULL), (1, 2, 300),
            (2, 1, NULL);
    """)
    conn.commit()
    conn.close()
    assert db.migrate(path) == len(db.MIGRATIONS)
    conn = db.connect(path)
    rows = conn.execute("SELECT food_id, sector_id, quantity FROM fridge_places ORDER BY id")
    assert [tuple(r.values()) for r in rows] == [(1, 1, 600), (1, 2, 300)]
    conn.close()


def test_deleting_a_sector_or_food(client, oats):
    buy(client, oats["id"], 100)
    shelf = sector(client, "Shelf")
    move(client, oats["id"], None, shelf)
    assert client.delete(f"/api/fridge/sectors/{shelf}").status_code == 204
    assert client.delete(f"/api/fridge/sectors/{shelf}").status_code == 404
    fr = client.get("/api/fridge").json()
    assert fr["sectors"] == [] and where(fr)[None] == [("Rolled oats", 100)]

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
    assert [it["stocked"] for it in sm["items"]] == [False, False]  # never bought: not tracked

    buy(client, oats["id"], 500)
    buy(client, milk["id"], 100)
    sm = client.get(f"/api/saved-meals/{sm['id']}").json()
    assert sm["can_make"] is False
    assert [(it["in_stock"], it["missing"]) for it in sm["items"]] == [(500, 0), (100, 150)]
    assert [it["stocked"] for it in sm["items"]] == [True, True]

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


def test_recently_ran_out(client, oats):
    old_day = (TODAY - dt.timedelta(days=40)).isoformat()
    milk, rice, tea = food(client, "Milk", "ml"), food(client, "Rice"), food(client, "Tea")
    buy(client, oats["id"], 100)
    buy(client, milk["id"], 1000)
    buy(client, rice["id"], 500)
    buy(client, tea["id"], 50, day=old_day)
    door = sector(client, "Door", "🚪")
    move(client, milk["id"], None, door)

    def eat(food_id, q, day):
        r = client.post(
            "/api/entries", json={"day": day, "meal": "Lunch", "food_id": food_id, "quantity": q}
        )
        assert r.status_code == 201, r.text

    eat(milk["id"], 1000, D[2])
    eat(rice["id"], 200, D[1])  # some left: still in stock
    eat(oats["id"], 100, D[4])
    eat(tea["id"], 50, (TODAY - dt.timedelta(days=31)).isoformat())  # too long ago
    out = client.get("/api/fridge").json()["recently_out"]
    assert [(o["name"], o["ran_out_on"], o["sector"], o["emoji"]) for o in out] == [
        ("Milk", D[2], "Door", "🚪"),
        ("Rolled oats", D[4], None, ""),
    ]
