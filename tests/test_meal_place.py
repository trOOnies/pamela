"""Saved meals are homemade, eaten out, or either (asked each time they're logged)."""

from __future__ import annotations

import sqlite3

from pamela import db

TODAY = "2026-11-20"


def _meal(client, oats, **extra):
    r = client.post("/api/saved-meals", json={
        "name": "Porridge", "items": [{"food_id": oats["id"], "quantity": 50}], **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _log(client, sm, oats, eaten_out):
    return client.post("/api/entries/batch", json={
        "day": TODAY, "meal": "Breakfast", "saved_meal_id": sm["id"], "eaten_out": eaten_out,
        "items": [{"food_id": oats["id"], "quantity": 50}]})


def test_new_meals_are_homemade_and_the_place_is_kept(client, oats):
    sm = _meal(client, oats)
    assert sm["place"] == "home"
    body = {"name": "Porridge", "items": [{"food_id": oats["id"], "quantity": 50}], "place": "out"}
    r = client.put(f"/api/saved-meals/{sm['id']}", json=body)
    assert r.status_code == 200 and r.json()["place"] == "out"
    assert client.get(f"/api/saved-meals/{sm['id']}").json()["place"] == "out"
    assert client.put(f"/api/saved-meals/{sm['id']}", json=body | {"place": "x"}).status_code == 422


def test_logging_follows_the_meals_place(client, oats):
    home, out, both = (_meal(client, oats, place=p) for p in ("home", "out", "both"))
    assert _log(client, home, oats, True).status_code == 422
    assert _log(client, out, oats, False).status_code == 422
    r = _log(client, home, oats, False)
    assert r.status_code == 201 and not r.json()[0]["eaten_out"]
    r = _log(client, out, oats, True)
    assert r.status_code == 201 and r.json()[0]["eaten_out"]
    for eaten_out in (False, True):
        r = _log(client, both, oats, eaten_out)
        assert r.status_code == 201 and r.json()[0]["eaten_out"] is eaten_out


def test_meals_saved_before_can_be_either(tmp_path):
    """Migration 33: meals saved before it keep being loggable either way."""
    path = tmp_path / "p.sqlite3"
    conn = sqlite3.connect(path)
    for i, script in enumerate(db.MIGRATIONS[:32], start=1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i}; COMMIT;")
    conn.execute("INSERT INTO saved_meals (name) VALUES ('Old')")
    conn.commit()
    conn.close()
    db.migrate(path)
    with db.session(path) as c:
        assert c.execute("SELECT place FROM saved_meals").fetchone()["place"] == "both"
