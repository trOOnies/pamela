"""The shopping list: foods (and meta foods) to buy, crossed off by saving a cart."""

from __future__ import annotations

import datetime as dt

TODAY = dt.date.today().isoformat()


def food(client, name, unit="g", **kw) -> dict:
    r = client.post("/api/foods", json={"name": name, "unit": unit, "kcal": 100} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def add(client, food_id, note="", status=201) -> dict:
    r = client.post("/api/shopping-list", json={"food_id": food_id, "note": note})
    assert r.status_code == status, r.text
    return r.json()


def cart(client, *items, cart_id=None) -> dict:
    body = {"bought_on": TODAY, "items": list(items)}
    if cart_id is None:
        r = client.post("/api/groceries/carts", json=body)
    else:
        r = client.put(f"/api/groceries/carts/{cart_id}", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def listed(client) -> list[int]:
    return [it["food_id"] for it in client.get("/api/shopping-list").json()]


def test_add_note_and_remove(client, oats):
    assert client.get("/api/shopping-list").json() == []
    it = add(client, oats["id"], "2 packs")
    assert (it["name"], it["brand"], it["note"]) == ("Rolled oats", "Acme", "2 packs")
    assert not it["is_meta"]
    assert (it["in_stock"], it["last_quantity"], it["options"]) == (0, None, [])
    # once on the list: adding it again keeps it (and its note, unless a new one is given)
    assert add(client, oats["id"])["id"] == it["id"]
    assert add(client, oats["id"])["note"] == "2 packs"
    assert add(client, oats["id"], "the big one")["note"] == "the big one"
    r = client.put(f"/api/shopping-list/{it['id']}", json={"note": ""})
    assert r.status_code == 200 and r.json()["note"] == ""
    assert client.delete(f"/api/shopping-list/{it['id']}").status_code == 204
    assert client.delete(f"/api/shopping-list/{it['id']}").status_code == 404
    assert client.put(f"/api/shopping-list/{it['id']}", json={"note": "x"}).status_code == 404
    add(client, 9999, status=404)


def test_meta_food_lists_its_foods_and_stock(client, oats):
    m = food(client, "Mozzarella cheese", is_meta=True)
    dia = food(client, "Mozzarella", brand="Dia", meta_id=m["id"], package_qty=250)
    food(client, "Mozzarella", brand="Ilolay", meta_id=m["id"])
    cart(client, {"food_id": dia["id"], "quantity": 250})
    it = add(client, m["id"])
    assert it["is_meta"] and it["in_stock"] == 250 and it["last_quantity"] is None
    opts = [(o["brand"], o["last_quantity"]) for o in it["options"]]
    assert opts == [("Dia", 250), ("Ilolay", None)]


def test_saving_a_cart_crosses_off_what_it_bought(client, oats):
    m = food(client, "Mozzarella cheese", is_meta=True)
    dia = food(client, "Mozzarella", brand="Dia", meta_id=m["id"])
    rice = food(client, "Rice")
    for f in (oats, m, rice):
        add(client, f["id"])
    c = cart(
        client, {"food_id": oats["id"], "quantity": 500}, {"food_id": dia["id"], "quantity": 250}
    )
    assert listed(client) == [rice["id"]]  # the meta food went too: one of its foods was bought
    # editing a cart: only the foods added to it cross things off
    add(client, oats["id"])
    keep = [{"id": i["id"], "food_id": i["food_id"], "quantity": i["quantity"]} for i in c["items"]]
    cart(client, *keep, cart_id=c["id"])
    assert sorted(listed(client)) == sorted([oats["id"], rice["id"]])
    cart(client, *keep, {"food_id": rice["id"], "quantity": 1000}, cart_id=c["id"])
    assert listed(client) == [oats["id"]]


def test_clear_and_food_deleted(client, oats):
    rice = food(client, "Rice")
    add(client, oats["id"])
    add(client, rice["id"])
    assert client.delete(f"/api/foods/{rice['id']}").status_code in (200, 204)
    assert listed(client) == [oats["id"]]
    assert client.delete("/api/shopping-list").status_code == 204
    assert listed(client) == []


def test_things_that_arent_food(client, oats):
    assert client.post("/api/shopping-list", json={"note": "x"}).status_code == 422
    r = client.post("/api/shopping-list", json={"food_id": oats["id"], "name": "Oats"})
    assert r.status_code == 422
    r = client.post("/api/shopping-list", json={"name": "Dish soap", "note": "lemon"})
    assert r.status_code == 201, r.text
    soap = r.json()
    assert (soap["food_id"], soap["name"], soap["note"], soap["options"]) == (
        None, "Dish soap", "lemon", []
    )
    # the same name (case and accents aside) is the same item
    again = client.post("/api/shopping-list", json={"name": "dish SOAP"}).json()
    assert (again["id"], again["note"]) == (soap["id"], "lemon")
    client.post("/api/shopping-list", json={"name": "Bags"})
    add(client, oats["id"])
    names = [it["name"] for it in client.get("/api/shopping-list").json()]
    assert names == ["Bags", "Dish soap", "Rolled oats"]
    # a cart with an other item of that name crosses it off; foods still work as before
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": TODAY, "items": [], "extras": [{"name": "dish soap", "price": 2}]},
    )
    assert r.status_code == 201, r.text
    assert [it["name"] for it in client.get("/api/shopping-list").json()] == [
        "Bags", "Rolled oats"
    ]
    # editing it: only other items new to it cross things off
    cart_id = r.json()["id"]
    client.post("/api/shopping-list", json={"name": "Dish soap"})
    body = {"bought_on": TODAY, "items": [], "extras": [{"name": "Dish soap"}, {"name": "Bags"}]}
    assert client.put(f"/api/groceries/carts/{cart_id}", json=body).status_code == 200
    assert [it["name"] for it in client.get("/api/shopping-list").json()] == [
        "Dish soap", "Rolled oats"
    ]
