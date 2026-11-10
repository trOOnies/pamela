from __future__ import annotations

import datetime as dt

import pytest

DAY = "2026-11-09"


def test_index_and_static_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>Pamela</title>" in r.text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert js.headers["cache-control"] == "no-cache"
    assert client.get("/static/app.css").status_code == 200


def test_startup_creates_config_and_db(client, settings):
    assert settings.config_path.exists()
    assert settings.db_path.exists()


def test_config_endpoint_and_error(client, settings):
    cfg = client.get("/api/config").json()
    assert cfg["meals"]["names"] == ["Breakfast", "Lunch", "Snack", "Dinner"]
    settings.config_path.write_text("[targets]\nkcal = 'lots'\n")
    r = client.get("/api/config")
    assert r.status_code == 500
    assert "targets.kcal" in r.json()["detail"]


# --- foods -------------------------------------------------------------------


def test_food_crud(client, oats):
    assert oats["uses"] == 0
    fid = oats["id"]
    assert client.get(f"/api/foods/{fid}").json()["name"] == "Rolled oats"

    upd = {k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "protein_g", "carbs_g")}
    upd |= {"kcal": 390, "fat_g": 6.5, "fiber_g": 9}
    r = client.put(f"/api/foods/{fid}", json=upd)
    assert r.status_code == 200
    assert r.json()["kcal"] == 390

    assert client.delete(f"/api/foods/{fid}").status_code == 204
    assert client.get(f"/api/foods/{fid}").status_code == 404
    assert client.delete(f"/api/foods/{fid}").status_code == 404
    assert client.put(f"/api/foods/{fid}", json=upd).status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": "x", "basis_qty": 0},
        {"name": "x", "kcal": -1},
        {"name": "x", "surprise": 1},
    ],
)
def test_food_validation(client, bad):
    assert client.post("/api/foods", json=bad).status_code == 422


def test_food_search_and_usage_order(client, oats):
    rice = client.post("/api/foods", json={"name": "White rice", "kcal": 130}).json()
    client.post("/api/foods", json={"name": "100% juice", "kcal": 45})

    names = [f["name"] for f in client.get("/api/foods").json()]
    assert names == ["100% juice", "Rolled oats", "White rice"]

    # every word must match name or brand
    assert [f["name"] for f in client.get("/api/foods", params={"q": "acme oat"}).json()] == [
        "Rolled oats"
    ]
    assert client.get("/api/foods", params={"q": "acme rice"}).json() == []
    # LIKE wildcards are matched literally
    assert [f["name"] for f in client.get("/api/foods", params={"q": "%"}).json()] == ["100% juice"]

    # recently logged foods float to the top
    today = dt.date.today().isoformat()
    for _ in range(2):
        client.post(
            "/api/entries",
            json={"day": today, "meal": "Lunch", "food_id": rice["id"], "quantity": 150},
        )
    foods = client.get("/api/foods").json()
    assert foods[0]["name"] == "White rice"
    assert foods[0]["uses"] == 2


# --- entries -----------------------------------------------------------------


def test_entry_from_food_scales_and_snapshots(client, oats):
    r = client.post(
        "/api/entries",
        json={"day": DAY, "meal": "Breakfast", "food_id": oats["id"], "quantity": 50},
    )
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["name"] == "Rolled oats"
    assert e["unit"] == "g"
    assert e["kcal"] == pytest.approx(190)
    assert e["protein_g"] == pytest.approx(6.5)
    assert e["fiber_g"] == pytest.approx(5)

    # changing the food later does not rewrite history...
    upd = {k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "protein_g", "carbs_g")}
    client.put(f"/api/foods/{oats['id']}", json=upd | {"kcal": 1000, "fat_g": 0, "fiber_g": 0})
    day = client.get(f"/api/days/{DAY}").json()
    assert day["entries"][0]["kcal"] == pytest.approx(190)

    # ...but editing the entry recomputes it from the current food values
    r = client.put(
        f"/api/entries/{e['id']}",
        json={"day": DAY, "meal": "Breakfast", "food_id": oats["id"], "quantity": 10},
    )
    assert r.json()["kcal"] == pytest.approx(100)

    # deleting the food keeps the entry, unlinked
    client.delete(f"/api/foods/{oats['id']}")
    entry = client.get(f"/api/days/{DAY}").json()["entries"][0]
    assert entry["food_id"] is None
    assert entry["kcal"] == pytest.approx(100)


def test_quick_add_entry(client):
    r = client.post(
        "/api/entries",
        json={"day": DAY, "meal": "Snack", "name": "Coffee", "kcal": 40, "protein_g": 2},
    )
    assert r.status_code == 201
    e = r.json()
    assert (e["food_id"], e["quantity"], e["kcal"], e["carbs_g"]) == (None, None, 40, 0)


@pytest.mark.parametrize(
    "bad",
    [
        {"meal": "Breakfast"},  # neither food nor name
        {"meal": "Breakfast", "food_id": 1},  # food without quantity
        {"meal": "Breakfast", "food_id": 1, "quantity": 0},
        {"meal": "Breakfast", "name": "x", "kcal": -3},
        {"meal": "Brunch", "name": "x"},  # meal not in config
        {"meal": "Breakfast", "food_id": 999, "quantity": 5},  # unknown food
    ],
)
def test_entry_validation(client, oats, bad):
    r = client.post("/api/entries", json={"day": DAY} | bad)
    assert r.status_code == 422, r.text


def test_entry_update_delete_missing(client):
    body = {"day": DAY, "meal": "Snack", "name": "x"}
    assert client.put("/api/entries/42", json=body).status_code == 404
    assert client.delete("/api/entries/42").status_code == 404


# --- activities --------------------------------------------------------------


def test_activity_estimates_kcal_from_met(client):
    r = client.post("/api/activities", json={"day": DAY, "type": "running", "duration_min": 30})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kcal"] == pytest.approx(9.8 * 75 * 0.5)
    assert a["kcal_estimated"] is True


def test_activity_manual_kcal_and_unknown_type(client):
    r = client.post(
        "/api/activities",
        json={"day": DAY, "type": "Climbing", "duration_min": 60, "kcal": 500, "notes": "gym"},
    )
    assert r.status_code == 201
    assert r.json()["kcal_estimated"] is False
    r = client.post("/api/activities", json={"day": DAY, "type": "Climbing", "duration_min": 60})
    assert r.status_code == 422
    assert "unknown activity type" in r.json()["detail"]


def test_activity_update_and_delete(client):
    a = client.post(
        "/api/activities",
        json={"day": DAY, "type": "Walking", "duration_min": 20, "distance_km": 1.6},
    ).json()
    r = client.put(
        f"/api/activities/{a['id']}",
        json={"day": DAY, "type": "Walking", "duration_min": 40, "distance_km": 3.2, "kcal": 150},
    )
    assert r.json()["kcal"] == 150
    assert r.json()["duration_min"] == 40
    assert client.delete(f"/api/activities/{a['id']}").status_code == 204
    assert client.delete(f"/api/activities/{a['id']}").status_code == 404
    body = {"day": DAY, "type": "Walking", "duration_min": 1}
    assert client.put(f"/api/activities/{a['id']}", json=body).status_code == 404


def test_activity_validation(client):
    body = {"day": DAY, "type": "Walking", "duration_min": 0}
    assert client.post("/api/activities", json=body).status_code == 422


# --- aggregates --------------------------------------------------------------


def test_day_totals(client, oats):
    client.post(
        "/api/entries",
        json={"day": DAY, "meal": "Breakfast", "food_id": oats["id"], "quantity": 100},
    )
    client.post("/api/entries", json={"day": DAY, "meal": "Lunch", "name": "Sandwich", "kcal": 420})
    client.post("/api/entries", json={"day": "2026-11-10", "meal": "Lunch", "name": "x", "kcal": 1})
    client.post(
        "/api/activities", json={"day": DAY, "type": "Yoga", "duration_min": 45, "kcal": 120}
    )

    day = client.get(f"/api/days/{DAY}").json()
    assert len(day["entries"]) == 2
    assert day["totals"]["kcal"] == pytest.approx(800)
    assert day["totals"]["protein_g"] == pytest.approx(13)
    assert day["burned_kcal"] == 120
    assert day["active_min"] == 45

    empty = client.get("/api/days/2020-01-01").json()
    assert empty["entries"] == [] and empty["totals"]["kcal"] == 0
    assert client.get("/api/days/not-a-date").status_code == 422


def test_history_fills_every_day(client):
    client.post(
        "/api/entries", json={"day": "2026-11-02", "meal": "Lunch", "name": "a", "kcal": 500}
    )
    client.post(
        "/api/entries", json={"day": "2026-11-02", "meal": "Dinner", "name": "b", "kcal": 700}
    )
    client.post(
        "/api/activities", json={"day": "2026-11-04", "type": "Running", "duration_min": 10}
    )

    days = client.get("/api/history", params={"start": "2026-11-01", "end": "2026-11-05"}).json()
    assert [d["day"] for d in days] == [f"2026-11-0{i}" for i in range(1, 6)]
    assert days[1]["kcal"] == 1200 and days[1]["entry_count"] == 2
    assert days[0]["kcal"] == 0 and days[0]["entry_count"] == 0
    assert days[3]["active_min"] == 10 and days[3]["burned_kcal"] > 0


def test_history_defaults_and_limits(client):
    days = client.get("/api/history").json()
    assert len(days) == 30
    assert days[-1]["day"] == dt.date.today().isoformat()
    r = client.get("/api/history", params={"start": "2026-11-05", "end": "2026-11-01"})
    assert r.status_code == 422
    r = client.get("/api/history", params={"start": "2024-01-01", "end": "2026-01-01"})
    assert r.status_code == 422


def test_db_session_commits_before_response():
    """Regression: a follow-up GET right after a POST must see the new row."""
    import typing

    from pamela.api import Conn

    (dep,) = typing.get_args(Conn)[1:]
    assert dep.scope == "function"
