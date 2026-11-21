"""The Day tab's order, set by hand: foods and logged meals within (and across) meals,
and activities."""

from __future__ import annotations

DAY = "2026-11-20"


def _log(client, food_id, meal, qty=50):
    r = client.post(
        "/api/entries", json={"day": DAY, "meal": meal, "food_id": food_id, "quantity": qty}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _shown(client):
    """(meal, entry id or ("log", id)) in the order the Day tab shows them, once each."""
    meals = ["Breakfast", "Lunch", "Snack", "Dinner"]  # the Day tab groups them by meal
    out = []
    for e in client.get(f"/api/days/{DAY}").json()["entries"]:
        k = (e["meal"], ("log", e["meal_log_id"]) if e["meal_log_id"] else e["id"])
        if k not in out:
            out.append(k)
    return sorted(out, key=lambda k: meals.index(k[0]))


def test_food_order_moves_entries_and_meal_logs(client, oats):
    a = _log(client, oats["id"], "Breakfast")
    b = _log(client, oats["id"], "Breakfast")
    items = [{"food_id": oats["id"], "quantity": 10}, {"food_id": oats["id"], "quantity": 20}]
    sm = client.post("/api/saved-meals", json={"name": "Bowl", "items": items}).json()
    logged = client.post(
        "/api/entries/batch",
        json={"day": DAY, "meal": "Breakfast", "saved_meal_id": sm["id"], "items": items},
    ).json()
    log_id = logged[0]["meal_log_id"]
    c = _log(client, oats["id"], "Breakfast")
    # as logged, by default
    assert _shown(client) == [
        ("Breakfast", a),
        ("Breakfast", b),
        ("Breakfast", ("log", log_id)),
        ("Breakfast", c),
    ]

    # the meal log first, then c; a and b to Lunch, b before a
    order = {
        "items": [
            {"meal_log_id": log_id, "meal": "Breakfast"},
            {"entry_id": c, "meal": "Breakfast"},
            {"entry_id": b, "meal": "Lunch"},
            {"entry_id": a, "meal": "Lunch"},
        ]
    }
    r = client.put(f"/api/days/{DAY}/food-order", json=order)
    assert r.status_code == 204, r.text
    assert _shown(client) == [
        ("Breakfast", ("log", log_id)),
        ("Breakfast", c),
        ("Lunch", b),
        ("Lunch", a),
    ]
    # a meal log takes its foods along, and keeps them together
    order = {"items": [{"meal_log_id": log_id, "meal": "Dinner"}]}
    assert client.put(f"/api/days/{DAY}/food-order", json=order).status_code == 204
    day = client.get(f"/api/days/{DAY}").json()["entries"]
    assert {e["meal"] for e in day if e["meal_log_id"] == log_id} == {"Dinner"}

    # something logged later goes at the bottom of its meal
    d = _log(client, oats["id"], "Lunch")
    assert [k for m, k in _shown(client) if m == "Lunch"] == [b, a, d]


def test_food_order_rejects_what_isnt_there(client, oats):
    a = _log(client, oats["id"], "Breakfast")
    bad = {"items": [{"entry_id": a, "meal": "Lunch"}]}
    assert client.put("/api/days/2026-11-19/food-order", json=bad).status_code == 422
    both = {"items": [{"entry_id": a, "meal_log_id": 1, "meal": "Lunch"}]}
    assert client.put(f"/api/days/{DAY}/food-order", json=both).status_code == 422


def test_activity_order(client):
    def act(t, time=None):
        body = {"day": DAY, "type": "Walking", "duration_min": 10, "start_time": time}
        r = client.post("/api/activities", json=body)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def shown():
        return [a["id"] for a in client.get(f"/api/days/{DAY}").json()["activities"]]

    late, early = act("Walking", "18:00"), act("Walking", "07:00")
    assert shown() == [early, late]  # by time of day until sorted by hand
    r = client.put(f"/api/days/{DAY}/activity-order", json={"ids": [late, early]})
    assert r.status_code == 204, r.text
    assert shown() == [late, early]
    new = act("Walking", "06:00")
    assert shown() == [late, early, new]  # sorted by hand: a new one goes last
    r = client.put("/api/days/2026-11-19/activity-order", json={"ids": [late]})
    assert r.status_code == 422
