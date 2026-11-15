"""Favorite foods and meals come first wherever they're listed."""

from __future__ import annotations


def food(client, name, **kw) -> dict:
    r = client.post("/api/foods", json={"name": name, "unit": "g", "kcal": 100} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def test_favorite_foods_come_first_and_survive_edits(client):
    apple, banana, _cherry = (food(client, n) for n in ("Apple", "Banana", "Cherry"))
    r = client.put(f"/api/foods/{banana['id']}/favorite", json={"favorite": True})
    assert r.status_code == 200 and r.json()["favorite"] is True
    names = [f["name"] for f in client.get("/api/foods").json()]
    assert names == ["Banana", "Apple", "Cherry"]
    # searches too (the Day tab's food search)
    assert [f["name"] for f in client.get("/api/foods?q=an").json()] == ["Banana"]
    assert client.get("/api/foods?q=a&limit=1").json()[0]["name"] == "Banana"
    # editing the food keeps it a favorite
    r = client.put(f"/api/foods/{banana['id']}", json={"name": "Banana", "unit": "g", "kcal": 89})
    assert r.json()["favorite"] is True
    assert client.put(f"/api/foods/{banana['id']}/favorite", json={"favorite": False}).json()[
        "favorite"
    ] is False
    assert [f["name"] for f in client.get("/api/foods").json()][0] == "Apple"
    assert client.put("/api/foods/999/favorite", json={"favorite": True}).status_code == 404
    assert client.put(f"/api/foods/{apple['id']}/favorite", json={}).status_code == 422


def test_favorite_meals_come_first(client):
    oats = food(client, "Oats")
    ids = {}
    for name in ("Breakfast bowl", "Zesty oats"):
        r = client.post("/api/saved-meals",
                        json={"name": name, "items": [{"food_id": oats["id"], "quantity": 50}]})
        ids[name] = r.json()["id"]
    r = client.put(f"/api/saved-meals/{ids['Zesty oats']}/favorite", json={"favorite": True})
    assert r.status_code == 200 and r.json()["favorite"] is True
    assert [m["name"] for m in client.get("/api/saved-meals").json()] == [
        "Zesty oats", "Breakfast bowl"]
    # editing the meal keeps it a favorite
    r = client.put(f"/api/saved-meals/{ids['Zesty oats']}",
                   json={"name": "Zesty oats", "items": [{"food_id": oats["id"], "quantity": 60}]})
    assert r.json()["favorite"] is True
    assert client.put("/api/saved-meals/999/favorite", json={"favorite": True}).status_code == 404
