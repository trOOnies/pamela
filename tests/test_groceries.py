"""Groceries: carts, expiries, and food entries taking from the stock."""

from __future__ import annotations

import datetime as dt

import pytest

TODAY = dt.date.today()
D = [(TODAY - dt.timedelta(days=n)).isoformat() for n in range(10)]  # D[0] = today


def buy(client, food_id, quantity, day=D[5], **kw) -> dict:
    """A cart with one item; returns that item."""
    item = {"food_id": food_id, "quantity": quantity} | kw
    r = client.post("/api/groceries/carts", json={"bought_on": day, "items": [item]})
    assert r.status_code == 201, r.text
    return r.json()["items"][0]


def eat(client, food_id, quantity, day=D[1]) -> dict:
    r = client.post(
        "/api/entries",
        json={"day": day, "meal": "Breakfast", "food_id": food_id, "quantity": quantity},
    )
    assert r.status_code == 201, r.text
    return r.json()


def stock(client) -> dict[int, dict]:
    return {it["food_id"]: it for it in client.get("/api/groceries").json()["items"]}


def test_cart_and_stock(client, oats):
    r = client.post(
        "/api/groceries/carts",
        json={
            "bought_on": D[3],
            "store": "Corner shop",
            "items": [
                {"food_id": oats["id"], "quantity": 500, "expires_on": D[0], "price": 2.5},
                {"food_id": oats["id"], "quantity": 1000},
            ],
        },
    )
    assert r.status_code == 201, r.text
    cart = r.json()
    assert cart["store"] == "Corner shop" and cart["bought_on"] == D[3]
    assert [it["remaining"] for it in cart["items"]] == [500, 1000]
    assert cart["items"][0]["name"] == "Rolled oats"
    assert cart["total_price"] == 2.5
    it = stock(client)[oats["id"]]
    assert it["in_stock"] == 1500
    assert it["next_expiry"] == D[0]
    assert it["last_bought"] == D[3]
    assert it["last_quantity"] == 1000
    # the lot that expires first is used first; one without a date last
    assert [lot["expires_on"] for lot in it["lots"]] == [D[0], None]
    assert client.get(f"/api/foods/{oats['id']}").json()["in_stock"] == 1500
    carts = client.get("/api/groceries").json()["carts"]
    assert [c["id"] for c in carts] == [cart["id"]]
    assert client.get(f"/api/groceries/carts/{cart['id']}").json() == cart


def test_food_never_bought_has_no_stock(client, oats):
    assert client.get(f"/api/foods/{oats['id']}").json()["in_stock"] is None
    assert stock(client) == {}


def test_eating_takes_from_stock_soonest_expiry_first(client, oats):
    late = buy(client, oats["id"], 300, expires_on=D[0])
    soon = buy(client, oats["id"], 100, expires_on=D[2])
    e = eat(client, oats["id"], 150)
    assert e["from_stock"] == 150
    lots = {lot["id"]: lot for lot in stock(client)[oats["id"]]["lots"]}
    assert soon["id"] not in lots  # used up
    assert lots[late["id"]]["remaining"] == 250
    assert stock(client)[oats["id"]]["in_stock"] == 250


def test_eating_more_than_in_stock_takes_what_there_is(client, oats):
    buy(client, oats["id"], 100)
    e = eat(client, oats["id"], 180)
    assert e["from_stock"] == 100
    it = stock(client)[oats["id"]]
    assert it["in_stock"] == 0 and it["lots"] == []  # ran out, still listed


def test_entry_before_purchase_day_is_not_taken(client, oats):
    buy(client, oats["id"], 100, day=D[2])
    assert eat(client, oats["id"], 40, day=D[4])["from_stock"] == 0


def test_edit_and_delete_entry_give_back_stock(client, oats):
    buy(client, oats["id"], 500)
    e = eat(client, oats["id"], 100)
    r = client.put(
        f"/api/entries/{e['id']}",
        json={"day": e["day"], "meal": e["meal"], "food_id": oats["id"], "quantity": 40},
    )
    assert r.json()["from_stock"] == 40
    assert stock(client)[oats["id"]]["in_stock"] == 460
    assert client.get(f"/api/days/{e['day']}").json()["entries"][0]["from_stock"] == 40
    client.delete(f"/api/entries/{e['id']}")
    assert stock(client)[oats["id"]]["in_stock"] == 500


def test_clear_day_gives_back_stock(client, oats):
    buy(client, oats["id"], 500)
    eat(client, oats["id"], 100)
    client.delete(f"/api/days/{D[1]}")
    assert stock(client)[oats["id"]]["in_stock"] == 500


def test_saved_meal_batch_takes_from_stock(client, oats):
    buy(client, oats["id"], 500)
    r = client.post(
        "/api/entries/batch",
        json={"day": D[1], "meal": "Lunch", "items": [{"food_id": oats["id"], "quantity": 60}]},
    )
    assert r.json()[0]["from_stock"] == 60


def test_late_purchase_covers_what_was_eaten_since(client, oats):
    e = eat(client, oats["id"], 80, day=D[2])
    early = eat(client, oats["id"], 50, day=D[6])
    assert e["from_stock"] == 0
    buy(client, oats["id"], 500, day=D[3])
    day = client.get(f"/api/days/{D[2]}").json()
    assert day["entries"][0]["from_stock"] == 80
    assert client.get(f"/api/days/{D[6]}").json()["entries"][0]["id"] == early["id"]
    assert client.get(f"/api/days/{D[6]}").json()["entries"][0]["from_stock"] == 0
    assert stock(client)[oats["id"]]["in_stock"] == 420


def test_expire_and_undo(client, oats):
    lot = buy(client, oats["id"], 500, expires_on=D[2])
    url = f"/api/groceries/lots/{lot['id']}/expired"
    r = client.post(url, json={"day": D[1], "quantity": 200})
    assert r.status_code == 200, r.text
    assert r.json()["remaining"] == 300 and r.json()["expired"] == 200
    r = client.post(url, json={"day": D[0]})
    assert r.json()["remaining"] == 0  # all that was left
    assert stock(client)[oats["id"]]["in_stock"] == 0
    expired = client.get("/api/groceries").json()["expired"]
    assert [h["quantity"] for h in expired] == [300, 200]
    assert expired[0]["cart_id"] == lot["cart_id"]
    assert expired[0]["food_group"] == ""
    assert client.delete(f"/api/groceries/expired/{expired[0]['id']}").status_code == 204
    assert stock(client)[oats["id"]]["in_stock"] == 300
    assert client.delete(f"/api/groceries/expired/{expired[0]['id']}").status_code == 404


def test_expire_validation(client, oats):
    lot = buy(client, oats["id"], 100, day=D[3])
    url = f"/api/groceries/lots/{lot['id']}/expired"
    assert client.post(url, json={"day": D[1], "quantity": 150}).status_code == 422
    assert client.post(url, json={"day": D[5]}).status_code == 422  # before it was bought
    future = (TODAY + dt.timedelta(days=1)).isoformat()
    assert client.post(url, json={"day": future}).status_code == 422
    client.post(url, json={"day": D[1]})
    assert client.post(url, json={"day": D[1]}).status_code == 422  # nothing left
    assert client.post("/api/groceries/lots/999/expired", json={"day": D[1]}).status_code == 404


def cart_body(cart: dict, **kw) -> dict:
    """A PUT body that keeps the cart as it is, with ``kw`` changed."""
    items = [
        {k: it[k] for k in ("id", "food_id", "quantity", "expires_on", "price")}
        for it in cart["items"]
    ]
    extras = [{k: x[k] for k in ("name", "quantity", "unit", "price")} for x in cart["extras"]]
    keep = {k: cart[k] for k in ("discount", "discount_pct", "delivery_fee")}
    return {"bought_on": cart["bought_on"], "store": cart["store"], "items": items,
            "extras": extras} | keep | kw


def test_edit_cart(client, oats):
    other = client.post("/api/foods", json={"name": "Milk", "unit": "ml"}).json()
    lot = buy(client, oats["id"], 500)
    eat(client, oats["id"], 300)
    cart = client.get(f"/api/groceries/carts/{lot['cart_id']}").json()
    body = cart_body(cart, store="Market")
    body["items"][0] |= {"quantity": 600, "price": 3}
    body["items"].append({"food_id": other["id"], "quantity": 1000})
    r = client.put(f"/api/groceries/carts/{cart['id']}", json=body)
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["store"] == "Market" and edited["total_price"] == 3
    assert [(it["id"] == lot["id"], it["remaining"]) for it in edited["items"]] == [
        (True, 300),
        (False, 1000),
    ]
    # smaller than what was eaten: refused, and nothing changes
    body = cart_body(edited)
    body["items"][0]["quantity"] = 200
    r = client.put(f"/api/groceries/carts/{cart['id']}", json=body)
    assert r.status_code == 422 and "already used" in r.json()["detail"]
    assert client.get(f"/api/groceries/carts/{cart['id']}").json() == edited
    # remove an item
    body = cart_body(edited)
    body["items"] = body["items"][:1]
    r = client.put(f"/api/groceries/carts/{cart['id']}", json=body)
    assert [it["food_id"] for it in r.json()["items"]] == [oats["id"]]
    assert other["id"] not in stock(client)


def test_edit_cart_validation(client, oats):
    a = buy(client, oats["id"], 500)
    b = buy(client, oats["id"], 100)
    cart = client.get(f"/api/groceries/carts/{a['cart_id']}").json()
    url = f"/api/groceries/carts/{cart['id']}"
    body = cart_body(cart)
    body["items"][0]["id"] = b["id"]  # an item of another cart
    assert client.put(url, json=body).status_code == 422
    body = cart_body(cart)
    body["items"].append(dict(body["items"][0]))  # twice
    assert client.put(url, json=body).status_code == 422
    other = client.post("/api/foods", json={"name": "Milk"}).json()
    body = cart_body(cart)
    body["items"][0]["food_id"] = other["id"]
    assert client.put(url, json=body).status_code == 422
    assert client.put(url, json=cart_body(cart, items=[])).status_code == 422
    assert client.put("/api/groceries/carts/999", json=cart_body(cart)).status_code == 404


def test_moving_cart_later_gives_back_earlier_meals(client, oats):
    lot = buy(client, oats["id"], 500, day=D[5])
    e = eat(client, oats["id"], 100, day=D[4])
    assert e["from_stock"] == 100
    cart = client.get(f"/api/groceries/carts/{lot['cart_id']}").json()
    client.put(f"/api/groceries/carts/{cart['id']}", json=cart_body(cart, bought_on=D[2]))
    assert client.get(f"/api/days/{D[4]}").json()["entries"][0]["from_stock"] == 0
    assert stock(client)[oats["id"]]["in_stock"] == 500
    # and earlier again: it covers that meal once more
    client.put(f"/api/groceries/carts/{cart['id']}", json=cart_body(cart, bought_on=D[6]))
    assert client.get(f"/api/days/{D[4]}").json()["entries"][0]["from_stock"] == 100


def test_delete_cart_keeps_entries_and_falls_back(client, oats):
    first = buy(client, oats["id"], 50, day=D[6], expires_on=D[3])
    later = buy(client, oats["id"], 500, day=D[5])
    eat(client, oats["id"], 100)
    assert client.delete(f"/api/groceries/carts/{first['cart_id']}").status_code == 204
    entry = client.get(f"/api/days/{D[1]}").json()["entries"][0]
    # it took 50 from the deleted cart; now all 100 come from the other one
    assert entry["quantity"] == 100 and entry["from_stock"] == 100
    assert stock(client)[oats["id"]]["in_stock"] == 400
    client.delete(f"/api/groceries/carts/{later['cart_id']}")
    assert client.get(f"/api/days/{D[1]}").json()["entries"][0]["from_stock"] == 0
    assert client.delete(f"/api/groceries/carts/{later['cart_id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"bought_on": D[1], "items": []},
        {"bought_on": D[1], "items": [{"food_id": 1, "quantity": 0}]},
        {"bought_on": D[1], "items": [{"food_id": 1, "quantity": 1, "expires_on": D[2]}]},
        {"bought_on": D[1], "items": [{"food_id": 1, "quantity": 1, "price": -1}]},
        {"bought_on": D[1], "items": [{"id": 1, "food_id": 1, "quantity": 1}]},
    ],
)
def test_cart_validation(client, oats, body):
    assert client.post("/api/groceries/carts", json=body).status_code == 422


def test_cart_unknown_food_or_future(client, oats):
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": D[1], "items": [{"food_id": 999, "quantity": 1}]},
    )
    assert r.status_code == 422
    future = (TODAY + dt.timedelta(days=1)).isoformat()
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": future, "items": [{"food_id": oats["id"], "quantity": 1}]},
    )
    assert r.status_code == 422


def test_wipe_groceries_and_foods(client, oats):
    buy(client, oats["id"], 500)
    eat(client, oats["id"], 100)
    r = client.post("/api/wipe", json={"what": ["groceries"]})
    assert r.json()["counts"] == {"groceries": 1}
    assert stock(client) == {}
    assert client.get(f"/api/days/{D[1]}").json()["entries"][0]["from_stock"] == 0
    buy(client, oats["id"], 500)
    r = client.post("/api/wipe", json={"what": ["foods"]})
    assert r.json()["counts"]["groceries"] == 1  # the cart left empty
    assert client.get("/api/groceries").json() == {"items": [], "carts": [], "expired": []}


def test_deleting_a_food_drops_carts_left_empty(client, oats):
    milk = client.post("/api/foods", json={"name": "Milk"}).json()
    client.post(
        "/api/groceries/carts",
        json={"bought_on": D[1], "items": [{"food_id": oats["id"], "quantity": 1},
                                           {"food_id": milk["id"], "quantity": 1}]},
    )
    lone = buy(client, milk["id"], 1)
    client.delete(f"/api/foods/{milk['id']}")
    carts = client.get("/api/groceries").json()["carts"]
    assert len(carts) == 1 and [it["food_id"] for it in carts[0]["items"]] == [oats["id"]]
    assert client.get(f"/api/groceries/carts/{lone['cart_id']}").status_code == 404


def test_discount_and_other_items(client, oats):
    r = client.post(
        "/api/groceries/carts",
        json={
            "bought_on": D[1],
            "items": [{"food_id": oats["id"], "quantity": 500, "price": 6}],
            "extras": [
                {"name": "Dish soap", "quantity": 2, "unit": "u", "price": 3.5},
                {"name": "Bag"},
            ],
            "discount": 1.5,
        },
    )
    assert r.status_code == 201, r.text
    cart = r.json()
    assert cart["subtotal"] == 9.5
    assert cart["discount_amount"] == 1.5 and cart["total_price"] == 8
    assert [(x["name"], x["quantity"], x["unit"], x["price"]) for x in cart["extras"]] == [
        ("Dish soap", 2, "u", 3.5),
        ("Bag", 1, "u", None),
    ]
    # other items are not foods and never in stock
    assert [f["name"] for f in client.get("/api/foods").json()] == ["Rolled oats"]
    assert list(stock(client)) == [oats["id"]]

    # a percentage instead, and other items replaced
    body = cart_body(cart, discount=None, discount_pct=10, extras=[{"name": "Sponges", "price": 4}])
    r = client.put(f"/api/groceries/carts/{cart['id']}", json=body)
    assert r.status_code == 200, r.text
    cart = r.json()
    assert (cart["discount"], cart["discount_pct"]) == (None, 10)
    assert cart["subtotal"] == 10 and cart["discount_amount"] == 1 and cart["total_price"] == 9
    assert [x["name"] for x in cart["extras"]] == ["Sponges"]


def test_cart_of_other_items_only(client, oats):
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": D[1], "store": "Pharmacy", "extras": [{"name": "Soap", "price": 2}]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["items"] == [] and r.json()["total_price"] == 2
    assert stock(client) == {}
    # deleting foods never drops a cart that still has other items
    buy(client, oats["id"], 1)
    client.delete(f"/api/foods/{oats['id']}")
    assert [c["store"] for c in client.get("/api/groceries").json()["carts"]] == ["Pharmacy"]


@pytest.mark.parametrize(
    "extra",
    [
        {"discount": 0},
        {"discount_pct": 0},
        {"discount_pct": 101},
        {"discount": 1, "discount_pct": 5},
        {"discount": 50},  # more than the subtotal
        {"extras": [{"name": ""}]},
        {"extras": [{"name": "Soap", "quantity": 0}]},
        {"extras": [{"name": "Soap", "price": -1}]},
        {"items": [], "extras": []},
    ],
)
def test_discount_and_other_items_validation(client, oats, extra):
    body = {"bought_on": D[1], "items": [{"food_id": oats["id"], "quantity": 1, "price": 10}]}
    r = client.post("/api/groceries/carts", json=body | extra)
    assert r.status_code == 422, r.text
    assert client.get("/api/groceries").json()["carts"] == []  # nothing half-saved


def test_delivery_fee(client, oats):
    item = {"food_id": oats["id"], "quantity": 500, "price": 10}
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": D[1], "items": [item], "discount_pct": 10, "delivery_fee": 2.5},
    )
    assert r.status_code == 201, r.text
    cart = r.json()
    # the discount only applies to the subtotal; the fee comes on top
    assert (cart["subtotal"], cart["discount_amount"], cart["delivery_fee"]) == (10, 1, 2.5)
    assert cart["total_price"] == 11.5
    r = client.put(f"/api/groceries/carts/{cart['id']}", json=cart_body(cart, delivery_fee=None))
    assert r.json()["delivery_fee"] is None and r.json()["total_price"] == 9
    # a fee with no prices: the total is the fee
    r = client.post(
        "/api/groceries/carts",
        json={"bought_on": D[1], "items": [item | {"price": None}], "delivery_fee": 3},
    )
    assert (r.json()["subtotal"], r.json()["total_price"]) == (None, 3)
    bad = {"bought_on": D[1], "items": [item], "delivery_fee": -1}
    assert client.post("/api/groceries/carts", json=bad).status_code == 422
