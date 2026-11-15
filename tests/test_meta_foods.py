"""Meta foods (a kind of food, any brand), meals made with them, and the /exit page."""

from __future__ import annotations

import datetime as dt
import sqlite3

from fastapi.testclient import TestClient

from pamela.app import _greeting, create_app

TODAY = dt.date.today().isoformat()
YESTERDAY = (dt.date.today() - dt.timedelta(days=1)).isoformat()


def food(client, name, unit="g", status=201, **kw) -> dict:
    r = client.post("/api/foods", json={"name": name, "unit": unit, "kcal": 100} | kw)
    assert r.status_code == status, r.text
    return r.json()


def meta(client, name="Mozzarella cheese", unit="g", **kw) -> dict:
    return food(client, name, unit, is_meta=True, kcal=280, protein_g=22, fat_g=21, **kw)


def put(client, f, **changes):
    keep = ("name", "brand", "ean", "basis_qty", "unit", "kcal", "protein_g", "carbs_g", "fat_g",
            "fiber_g", "serving_qty", "package_qty", "food_group", "is_meta", "meta_id")
    return client.put(f"/api/foods/{f['id']}", json={k: f[k] for k in keep} | changes)


def test_meta_food_has_no_brand_barcode_or_package(client):
    m = meta(client, ean="7790070410139", package_qty=500)
    assert (m["is_meta"], m["ean"], m["package_qty"], m["variants"]) == (True, None, None, 0)
    food(client, "Mozzarella", is_meta=True, brand="Dia", status=422)
    food(client, "Wine", "ml", is_meta=True, food_group="alcoholic", abv_pct=12,
         package_qty=750, status=422)
    food(client, "Nested", is_meta=True, meta_id=m["id"], status=422)


def test_a_food_is_one_of_a_meta_food_in_the_same_unit(client, oats):
    m = meta(client)
    dia = food(client, "Mozzarella Dia", brand="Dia", meta_id=m["id"])
    assert (dia["meta_id"], dia["meta_name"]) == (m["id"], "Mozzarella cheese")
    assert client.get(f"/api/foods/{m['id']}").json()["variants"] == 1
    # only a meta food, in the same unit, and not itself
    food(client, "Liquid mozz", "ml", meta_id=m["id"], status=422)
    food(client, "Not a meta", meta_id=oats["id"], status=422)
    assert put(client, m, meta_id=m["id"], is_meta=False).status_code == 422
    # it can't stop being a meta food, or change unit, while foods are one of it
    assert put(client, m, is_meta=False).status_code == 409
    assert put(client, m, unit="ml").status_code == 409
    # kind= splits the catalog
    names = lambda kind: {f["name"] for f in client.get(f"/api/foods?kind={kind}").json()}  # noqa: E731
    assert names("meta") == {"Mozzarella cheese"}
    assert names("foods") == {"Rolled oats", "Mozzarella Dia"}
    assert len(names("all")) == 3
    # deleting the meta food unlinks its foods
    assert client.delete(f"/api/foods/{m['id']}").status_code == 204
    assert client.get(f"/api/foods/{dia['id']}").json()["meta_id"] is None


def test_meta_food_cant_be_logged_or_bought(client):
    m = meta(client)
    r = client.post("/api/entries", json={"day": TODAY, "meal": "Lunch", "food_id": m["id"],
                                          "quantity": 50})
    assert r.status_code == 422 and "pick which" in r.text
    r = client.post("/api/groceries/carts",
                    json={"bought_on": TODAY, "items": [{"food_id": m["id"], "quantity": 500}]})
    assert r.status_code == 422 and "can't be bought" in r.text


def test_food_in_groceries_cant_become_meta(client, oats):
    item = {"food_id": oats["id"], "quantity": 500}
    r = client.post("/api/groceries/carts", json={"bought_on": YESTERDAY, "items": [item]})
    assert r.status_code == 201
    assert put(client, oats, brand="", is_meta=True).status_code == 409


def test_meal_with_a_meta_food_offers_its_foods(client):
    m = meta(client)
    dia = food(client, "Mozzarella Dia", brand="Dia", meta_id=m["id"], basis_qty=30, kcal=79)
    other = food(client, "Mozzarella Barra", brand="Other", meta_id=m["id"], kcal=250)
    garlic = food(client, "Garlic", kcal=149)
    r = client.post("/api/groceries/carts", json={"bought_on": YESTERDAY, "items": [
        {"food_id": dia["id"], "quantity": 40}, {"food_id": other["id"], "quantity": 40}]})
    assert r.status_code == 201
    r = client.post("/api/saved-meals", json={"name": "Pizza", "items": [
        {"food_id": m["id"], "quantity": 68}, {"food_id": garlic["id"], "quantity": 5}]})
    assert r.status_code == 201, r.text
    sm = r.json()
    cheese, g = sm["items"]
    assert cheese["is_meta"] and not g["is_meta"]
    assert cheese["kcal"] == 280 * 68 / 100  # typical values
    assert {o["id"] for o in cheese["options"]} == {dia["id"], other["id"]}
    # what's left of a meta food is what's left of all its foods
    assert (cheese["in_stock"], cheese["missing"]) == (80, 0)
    assert g["options"] == []
    # logging: the picked food goes in its place
    r = client.post("/api/entries/batch", json={
        "day": TODAY, "meal": "Dinner", "saved_meal_id": sm["id"],
        "items": [{"food_id": dia["id"], "quantity": 68},
                  {"food_id": garlic["id"], "quantity": 5}]})
    assert r.status_code == 201, r.text
    assert r.json()[0]["name"] == "Mozzarella Dia"
    assert round(r.json()[0]["kcal"], 2) == round(79 * 68 / 30, 2)


def test_exit_page_says_goodbye_then_stops(settings):
    calls = []
    app = create_app(settings)
    app.state.request_exit = lambda: calls.append("exit")
    with TestClient(app) as client:
        oats = food(client, "Oats", kcal=380)
        r = client.post("/api/entries", json={"day": TODAY, "meal": "Breakfast",
                                              "food_id": oats["id"], "quantity": 50})
        assert r.status_code == 201
        assert calls == []
        r = client.get("/exit")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert calls == ["exit"]
        page = r.text
        assert "Everything is saved" in page and "{{" not in page
        assert "1 food</b> · 190 kcal" in page
        assert "/static/" not in page  # nothing to load once the server is gone
    wal = settings.db_path.with_name(settings.db_path.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM food_entries").fetchone() == (1,)


def test_greeting_by_time_of_day():
    assert "night" in _greeting(2) and "night" in _greeting(23)
    assert "day" in _greeting(8) and "evening" in _greeting(20)
