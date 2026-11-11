"""Barcodes, diet tags and portions; saved meals; activity types; daily metrics."""

from __future__ import annotations

import datetime as dt

import pytest

from pamela import barcode

DAY = "2026-11-09"
EAN = "7790070410139"  # valid check digit


def food(client, **kw) -> dict:
    body = {"name": "Food", "kcal": 100, "protein_g": 1} | kw
    r = client.post("/api/foods", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- barcodes ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4006381333931", "4006381333931"),
        ("4006-3813 33931", "4006381333931"),
        ("96385074", "96385074"),  # EAN-8
        ("036000291452", "0036000291452"),  # UPC-A becomes EAN-13
    ],
)
def test_normalize_ean(raw, expected):
    assert barcode.normalize_ean(raw) == expected


@pytest.mark.parametrize(
    ("raw", "msg"),
    [("4006381333932", "check digit"), ("12345", "digits"), ("40063813339a1", "digits only")],
)
def test_normalize_ean_rejects(raw, msg):
    with pytest.raises(ValueError, match=msg):
        barcode.normalize_ean(raw)


OFF_PRODUCT = {
    "product_name": "Galletitas de arroz",
    "brands": "Marolio, Otra",
    "product_quantity": "150",
    "product_quantity_unit": "g",
    "serving_quantity": 30,
    "nutriments": {
        "energy_100g": 1600,  # kJ only
        "proteins_100g": "7.5",
        "carbohydrates_100g": 80,
        "fat_100g": 3,
    },
    "labels_tags": ["en:gluten-free", "en:kosher-parve"],
    "ingredients_analysis_tags": ["en:vegan", "en:palm-oil-free"],
    "allergens_tags": ["en:peanuts"],
}


def test_product_to_draft():
    d = barcode.product_to_draft(EAN, OFF_PRODUCT)
    assert d["name"] == "Galletitas de arroz"
    assert d["brand"] == "Marolio"
    assert (d["basis_qty"], d["unit"]) == (100, "g")
    assert d["kcal"] == pytest.approx(382.41, abs=0.01)
    assert (d["protein_g"], d["fiber_g"]) == (7.5, 0)
    assert (d["serving_qty"], d["package_qty"]) == (30, 150)
    assert d["vegan"] and d["vegetarian"] and d["kosher"] and d["tacc_free"]
    assert d["ovolactovegetarian"] and d["pescatarian"]
    assert not d["lactose_free"]
    assert not d["peanut_free"]  # allergens say peanuts


def test_barcode_lookup_sources(client, monkeypatch):
    calls = []

    def fake_fetch(code):
        calls.append(code)
        return OFF_PRODUCT if code == EAN else None

    monkeypatch.setattr(barcode, "fetch_product", fake_fetch)

    r = client.get(f"/api/barcode/{EAN}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "openfoodfacts"
    assert body["food"] is None
    assert body["draft"]["name"] == "Galletitas de arroz"
    # nothing was saved
    assert client.get("/api/foods").json() == []

    # once in the catalog, the catalog answers without going online
    created = food(client, **{k: body["draft"][k] for k in ("name", "ean", "kcal")})
    calls.clear()
    body = client.get(f"/api/barcode/{EAN}").json()
    assert body["source"] == "catalog" and body["food"]["id"] == created["id"]
    assert calls == []

    body = client.get("/api/barcode/4006381333931").json()
    assert body == {"ean": "4006381333931", "source": None, "food": None, "draft": None}
    assert (
        client.get("/api/barcode/4006381333931", params={"online": False}).json()["source"] is None
    )

    assert client.get("/api/barcode/123").status_code == 422


def test_barcode_lookup_unavailable(client, monkeypatch):
    def down(code):
        raise barcode.LookupUnavailable("couldn't reach Open Food Facts (timeout)")

    monkeypatch.setattr(barcode, "fetch_product", down)
    r = client.get(f"/api/barcode/{EAN}")
    assert r.status_code == 502
    assert "Open Food Facts" in r.json()["detail"]


def test_food_barcode_tags_and_portions(client):
    f = food(
        client,
        name="Leche",
        ean=" 7790070410139 ",
        unit="ml",
        serving_qty=200,
        package_qty=1000,
        vegan=True,
        tacc_free=True,
    )
    assert f["ean"] == EAN
    # vegan implies every broader diet
    assert f["vegetarian"] and f["ovolactovegetarian"] and f["pescatarian"]
    assert (f["tacc_free"], f["kosher"]) == (True, False)
    assert (f["serving_qty"], f["package_qty"]) == (200, 1000)

    # barcodes are unique, and searchable
    r = client.post("/api/foods", json={"name": "Copy", "ean": EAN})
    assert r.status_code == 409
    assert "Leche" in r.json()["detail"]
    assert [x["name"] for x in client.get("/api/foods", params={"q": "70410"}).json()] == ["Leche"]

    # updating the same food with its own barcode is fine; clearing it too
    upd = {"name": "Leche", "ean": EAN, "unit": "ml", "kcal": 60}
    assert client.put(f"/api/foods/{f['id']}", json=upd).status_code == 200
    r = client.put(f"/api/foods/{f['id']}", json=upd | {"ean": ""})
    assert r.json()["ean"] is None
    assert r.json()["vegan"] is False  # tags not sent are cleared

    assert client.post("/api/foods", json={"name": "x", "ean": "123"}).status_code == 422
    assert client.post("/api/foods", json={"name": "x", "serving_qty": 0}).status_code == 422


def test_diet_tags_imply_only_broader_ones(client):
    # the two branches below vegetarian don't imply each other
    f = food(client, name="Egg", ovolactovegetarian=True)
    assert (f["pescatarian"], f["ovolactovegetarian"], f["vegetarian"], f["vegan"]) == (
        False, True, False, False,
    )
    f = food(client, name="Tuna", pescatarian=True)
    assert (f["pescatarian"], f["ovolactovegetarian"], f["vegetarian"]) == (True, False, False)
    f = food(client, name="Lentils", vegetarian=True)
    assert (f["pescatarian"], f["ovolactovegetarian"], f["vegan"]) == (True, True, False)


def test_kcal_empty_is_unknown_zero_is_calorie_free(client, oats):
    unknown = food(client, name="Mystery", kcal=None, protein_g=0)
    assert unknown["kcal"] is None and unknown["calorie_free"] is False
    assert client.post("/api/foods", json={"name": "No kcal key"}).json()["kcal"] is None
    zero = food(client, name="Water", kcal=0, protein_g=0, unit="ml", vegan=True)
    assert zero["kcal"] == 0 and zero["calorie_free"] is True
    assert oats["calorie_free"] is False
    # the tag can't be set by hand
    r = client.post("/api/foods", json={"name": "x", "kcal": 50, "calorie_free": True})
    assert r.status_code == 422
    # becoming known (or unknown again) changes the tag with it
    r = client.put(f"/api/foods/{zero['id']}", json={"name": "Water", "unit": "ml"})
    assert (r.json()["kcal"], r.json()["calorie_free"]) == (None, False)
    water_in = {"name": "Water", "unit": "ml", "kcal": 0, "vegan": True}
    r = client.put(f"/api/foods/{zero['id']}", json=water_in)
    assert r.json()["calorie_free"] is True

    # an unknown kcal still logs, counted as 0
    r = client.post(
        "/api/entries", json={"day": DAY, "meal": "Lunch", "food_id": unknown["id"], "quantity": 50}
    )
    assert r.status_code == 201 and r.json()["kcal"] == 0
    assert r.json()["protein_g"] == 0

    sm = client.post(
        "/api/saved-meals",
        json={"name": "m", "items": [{"food_id": unknown["id"], "quantity": 10},
                                     {"food_id": oats["id"], "quantity": 100}]},
    ).json()
    assert [it["kcal_missing"] for it in sm["items"]] == [True, False]
    assert sm["totals"]["kcal"] == pytest.approx(380)
    water = client.post(
        "/api/saved-meals", json={"name": "w", "items": [{"food_id": zero["id"], "quantity": 500}]}
    ).json()
    assert "calorie_free" in water["tags"] and "vegan" in water["tags"]
    assert "calorie_free" not in sm["tags"]


def test_food_group(client):
    f = food(client, name="Apple", unit="whole", food_group="fruits")
    assert (f["food_group"], f["unit"]) == ("fruits", "whole")
    assert food(client, name="Plain")["food_group"] == ""
    r = client.put(f"/api/foods/{f['id']}", json={"name": "Apple", "food_group": ""})
    assert r.json()["food_group"] == ""
    assert client.post("/api/foods", json={"name": "x", "food_group": "rocks"}).status_code == 422
    v = client.get("/api/vocab").json()
    assert {"key": "cookies", "label": "Cookies", "emoji": "🍪"} in v["food_groups"]
    assert {"u", "whole", "g", "ml"} <= set(v["units"]) and "unit" not in v["units"]


def test_brands_are_distinct_and_most_used_first(client):
    for name, brand in [("a", "Arcor"), ("b", "Check"), ("c", "check"), ("d", "Check"), ("e", "")]:
        food(client, name=name, brand=brand)
    assert client.get("/api/brands").json() == ["Check", "Arcor"]


# --- saved meals -------------------------------------------------------------


def test_saved_meal_crud_and_tags(client, oats):
    milk = food(
        client, name="Milk", unit="ml", kcal=50, protein_g=3.4, vegetarian=True, tacc_free=True
    )
    client.put(
        f"/api/foods/{oats['id']}",
        json={k: oats[k] for k in ("name", "brand", "kcal", "protein_g")}
        | {"vegan": True, "tacc_free": True},
    )
    body = {
        "name": "Usual breakfast",
        "default_meal": "Breakfast",
        "items": [
            {"food_id": oats["id"], "quantity": 60},
            {"food_id": milk["id"], "quantity": 200},
        ],
    }
    r = client.post("/api/saved-meals", json=body)
    assert r.status_code == 201, r.text
    sm = r.json()
    assert [it["name"] for it in sm["items"]] == ["Rolled oats", "Milk"]
    assert sm["items"][1]["kcal"] == pytest.approx(100)
    assert sm["totals"]["kcal"] == pytest.approx(380 * 0.6 + 100)
    # shared by every item (vegetarian implies the broader ones)
    assert sm["tags"] == ["pescatarian", "ovolactovegetarian", "vegetarian", "tacc_free"]

    body["items"] = [{"food_id": milk["id"], "quantity": 250}]
    r = client.put(f"/api/saved-meals/{sm['id']}", json=body | {"name": "Just milk"})
    assert r.json()["name"] == "Just milk"
    assert len(r.json()["items"]) == 1
    assert client.get("/api/saved-meals").json()[0]["totals"]["kcal"] == pytest.approx(125)

    # deleting a food drops it from saved meals
    client.delete(f"/api/foods/{milk['id']}")
    assert client.get(f"/api/saved-meals/{sm['id']}").json()["items"] == []

    assert client.delete(f"/api/saved-meals/{sm['id']}").status_code == 204
    assert client.get(f"/api/saved-meals/{sm['id']}").status_code == 404
    assert client.put(f"/api/saved-meals/{sm['id']}", json=body).status_code == 404
    assert client.delete(f"/api/saved-meals/{sm['id']}").status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "x", "items": []},
        {"name": "", "items": [{"food_id": 1, "quantity": 1}]},
        {"name": "x", "items": [{"food_id": 1, "quantity": 0}]},
        {"name": "x", "items": [{"food_id": 999, "quantity": 1}]},
    ],
)
def test_saved_meal_validation(client, oats, bad):
    assert client.post("/api/saved-meals", json=bad).status_code == 422


def test_batch_entries_log_a_modified_saved_meal(client, oats):
    milk = food(client, name="Milk", unit="ml", kcal=50)
    sm = client.post(
        "/api/saved-meals",
        json={
            "name": "Breakfast",
            "items": [
                {"food_id": oats["id"], "quantity": 60},
                {"food_id": milk["id"], "quantity": 200},
            ],
        },
    ).json()

    # the day gets an edited copy: half the oats, no milk
    r = client.post(
        "/api/entries/batch",
        json={"day": DAY, "meal": "Breakfast", "items": [{"food_id": oats["id"], "quantity": 30}]},
    )
    assert r.status_code == 201, r.text
    assert [(e["name"], e["quantity"]) for e in r.json()] == [("Rolled oats", 30)]
    # ...and the saved meal is untouched
    assert len(client.get(f"/api/saved-meals/{sm['id']}").json()["items"]) == 2

    # all or nothing
    r = client.post(
        "/api/entries/batch",
        json={
            "day": DAY,
            "meal": "Lunch",
            "items": [{"food_id": oats["id"], "quantity": 1}, {"food_id": 999, "quantity": 1}],
        },
    )
    assert r.status_code == 422
    assert len(client.get(f"/api/days/{DAY}").json()["entries"]) == 1


# --- activity types ----------------------------------------------------------


def test_activity_types_seeded_and_grouped(client):
    types = client.get("/api/activity-types").json()
    names = {t["name"] for t in types}
    assert len(types) > 60
    assert {"CrossFit", "Stationary bike, moderate", "Padel", "Walking"} <= names
    cats = [t["category"] for t in types]
    assert cats[0] == "Cardio"
    # each category appears in one contiguous block
    blocks = [c for i, c in enumerate(cats) if i == 0 or cats[i - 1] != c]
    assert len(blocks) == len(set(blocks))


def test_activity_type_crud_and_estimate(client):
    r = client.post("/api/activity-types", json={"name": "Pogo", "category": "Custom", "met": 6})
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["distance"], t["uses"]) == (False, 0)
    assert client.post("/api/activity-types", json={"name": "pogo", "met": 1}).status_code == 409

    old = "2020-01-01"  # outside the 90-day "uses" window
    r = client.post("/api/activities", json={"day": old, "type": "POGO", "duration_min": 60})
    assert r.json()["kcal"] == pytest.approx(6 * 75)

    today = dt.date.today().isoformat()
    client.post("/api/activities", json={"day": today, "type": "pogo", "duration_min": 10})
    pogo = next(x for x in client.get("/api/activity-types").json() if x["name"] == "Pogo")
    assert pogo["uses"] == 1

    r = client.put(
        f"/api/activity-types/{t['id']}",
        json={"name": "Pogo stick", "category": "Custom", "met": 7, "distance": True},
    )
    assert r.json()["met"] == 7 and r.json()["distance"] is True
    body = {"name": "Walking", "met": 1}
    assert client.put(f"/api/activity-types/{t['id']}", json=body).status_code == 409

    assert client.delete(f"/api/activity-types/{t['id']}").status_code == 204
    assert client.delete(f"/api/activity-types/{t['id']}").status_code == 404
    assert client.put(f"/api/activity-types/{t['id']}", json=body).status_code == 404
    # the logged activity keeps its name and kcal
    assert client.get(f"/api/days/{old}").json()["activities"][0]["type"] == "POGO"
    assert client.post("/api/activity-types", json={"name": "x", "met": 31}).status_code == 422


def test_legacy_config_types_are_imported_on_start(tmp_path):
    from fastapi.testclient import TestClient

    from pamela.app import create_app
    from pamela.config import Settings

    settings = Settings(local_dir=tmp_path / "local", info_dir=tmp_path / "info")
    settings.info_dir.mkdir()
    settings.config_path.write_text(
        "[[activity_types]]\nname = 'Unicycling'\nmet = 5.5\ndistance = true\n"
    )
    with TestClient(create_app(settings)) as c:
        uni = [t for t in c.get("/api/activity-types").json() if t["name"] == "Unicycling"]
        assert uni[0]["category"] == "Custom" and uni[0]["distance"] is True
        assert "activity_types" not in c.get("/api/config").json()


# --- daily metrics -----------------------------------------------------------


def test_day_metrics_roundtrip(client):
    assert client.get(f"/api/days/{DAY}").json()["metrics"] == {
        "steps": None,
        "sleep_min": None,
        "mood": None,
        "feelings": [],
        "weight_kg": None,
        "body_fat_pct": None,
    }
    r = client.put(
        f"/api/days/{DAY}/metrics",
        json={"steps": 9500, "sleep_min": 450, "mood": 4, "feelings": ["tired", "happy", "happy"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["feelings"] == ["happy", "tired"]  # canonical order, deduplicated
    assert client.get(f"/api/days/{DAY}").json()["metrics"]["steps"] == 9500

    r = client.put(f"/api/days/{DAY}/metrics", json={"steps": 10000, "mood": 5})
    assert r.json() == {
        "steps": 10000,
        "sleep_min": None,
        "mood": 5,
        "feelings": [],
        "weight_kg": None,
        "body_fat_pct": None,
    }

    days = client.get("/api/history", params={"start": DAY, "end": "2026-11-10"}).json()
    assert (days[0]["steps"], days[0]["mood"], days[0]["sleep_min"]) == (10000, 5, None)
    assert days[1]["steps"] is None

    # clearing every field removes the row
    client.put(f"/api/days/{DAY}/metrics", json={})
    assert client.get(f"/api/days/{DAY}/metrics").json()["steps"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"steps": -1},
        {"sleep_min": 1441},
        {"mood": 0},
        {"mood": 6},
        {"feelings": ["hangry"]},
        {"surprise": 1},
    ],
)
def test_day_metrics_validation(client, bad):
    assert client.put(f"/api/days/{DAY}/metrics", json=bad).status_code == 422


def test_vocab(client):
    v = client.get("/api/vocab").json()
    assert v["diet_implies"] == {
        "vegan": ["vegetarian"],
        "vegetarian": ["pescatarian", "ovolactovegetarian"],
    }
    assert [t["key"] for t in v["diet_tags"]] == [
        "pescatarian",
        "ovolactovegetarian",
        "vegetarian",
        "vegan",
        "kosher",
        "lactose_free",
        "peanut_free",
        "tacc_free",
    ]
    assert [m["label"] for m in v["moods"]] == ["Awful", "Bad", "Okay", "Good", "Great"]
    assert {"key": "anxious", "label": "Anxious", "group": "Tense"} in v["feelings"]
    groups = [f["group"] for f in v["feelings"]]
    # each group is one contiguous run, so the Day view can show it as a row
    runs = [g for i, g in enumerate(groups) if i == 0 or groups[i - 1] != g]
    assert len(runs) == len(set(runs)) == 5


def test_fetch_product_handles_answers(monkeypatch):
    import io
    import json
    import urllib.error

    answers = {}

    def fake_urlopen(req, timeout):
        assert req.get_header("User-agent").startswith("pamela/")
        code = req.full_url.split("/product/")[1].split(".json")[0]
        a = answers[code]
        if isinstance(a, Exception):
            raise a
        return io.BytesIO(json.dumps(a).encode())

    monkeypatch.setattr(barcode.urllib.request, "urlopen", fake_urlopen)
    answers["1"] = {"status": 1, "product": {"product_name": "x"}}
    answers["2"] = {"status": 0, "status_verbose": "product not found"}
    answers["3"] = urllib.error.HTTPError("u", 404, "Not Found", None, None)
    answers["4"] = urllib.error.HTTPError("u", 503, "Unavailable", None, None)
    answers["5"] = urllib.error.URLError("no network")
    assert barcode.fetch_product("1") == {"product_name": "x"}
    assert barcode.fetch_product("2") is None
    assert barcode.fetch_product("3") is None
    with pytest.raises(barcode.LookupUnavailable, match="503"):
        barcode.fetch_product("4")
    with pytest.raises(barcode.LookupUnavailable, match="reach"):
        barcode.fetch_product("5")


# --- targets -----------------------------------------------------------------


def test_targets_imported_from_config_once(tmp_path):
    from fastapi.testclient import TestClient

    from pamela.app import create_app
    from pamela.config import Settings

    settings = Settings(local_dir=tmp_path / "local", info_dir=tmp_path / "info")
    settings.info_dir.mkdir()
    settings.config_path.write_text("[targets]\nkcal = 1999.6\nfat_g = 0\nsleep_h = 7.4\n")
    with TestClient(create_app(settings)) as c:
        t = {x["key"]: x for x in c.get("/api/targets").json()}
        assert t["kcal"]["periods"] == [{"start": None, "value": 2000}]  # rounded
        assert t["fat_g"]["periods"][0]["value"] == 1  # must be positive
        assert t["sleep_h"]["periods"][0]["value"] == 7
        assert t["steps"]["periods"][0]["value"] == 8000  # default
        assert "targets" not in c.get("/api/config").json()
        c.put("/api/targets/kcal", json={"periods": [{"start": None, "value": 2500}]})
    settings.config_path.write_text("[targets]\nkcal = 1000\n")
    with TestClient(create_app(settings)) as c:  # restart: the config is ignored now
        kcal = next(x for x in c.get("/api/targets").json() if x["key"] == "kcal")
        assert kcal["periods"][0]["value"] == 2500


def test_target_periods_apply_per_day(client):
    body = {
        "periods": [
            {"start": None, "value": 2000},
            {"start": "2026-11-03", "value": 2400},
            {"start": "2026-11-05", "value": 1800},
        ]
    }
    r = client.put("/api/targets/kcal", json=body)
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["periods"]] == [2000, 2400, 1800]

    days = client.get("/api/history", params={"start": "2026-11-01", "end": "2026-11-06"}).json()
    assert [d["targets"]["kcal"] for d in days] == [2000, 2000, 2400, 2400, 1800, 1800]
    assert days[0]["targets"]["steps"] == 8000
    assert client.get("/api/days/2026-11-04").json()["targets"]["kcal"] == 2400

    # reset to a single value for all history
    r = client.put("/api/targets/kcal", json={"periods": [{"start": None, "value": 2100}]})
    assert r.json()["periods"] == [{"start": None, "value": 2100}]
    assert client.get("/api/days/2026-11-06").json()["targets"]["kcal"] == 2100


@pytest.mark.parametrize(
    ("key", "periods"),
    [
        ("kcal", []),
        ("kcal", [{"start": None, "value": 0}]),
        ("kcal", [{"start": None, "value": -5}]),
        ("kcal", [{"start": None, "value": 2000.5}]),  # integers only
        ("kcal", [{"start": "2026-01-01", "value": 1}]),  # first must be open-ended
        ("kcal", [{"start": None, "value": 1}, {"start": None, "value": 2}]),
        (
            "kcal",
            [
                {"start": None, "value": 1},
                {"start": "2026-02-01", "value": 2},
                {"start": "2026-01-01", "value": 3},
            ],
        ),
        (
            "kcal",
            [
                {"start": None, "value": 1},
                {"start": "2026-01-01", "value": 2},
                {"start": "2026-01-01", "value": 3},
            ],
        ),
        ("sleep_h", [{"start": None, "value": 25}]),
    ],
)
def test_target_validation(client, key, periods):
    assert client.put(f"/api/targets/{key}", json={"periods": periods}).status_code == 422


def test_target_unknown_key(client):
    body = {"periods": [{"start": None, "value": 1}]}
    assert client.put("/api/targets/beers", json=body).status_code == 404
    assert (
        client.put(
            "/api/targets/sleep_h", json={"periods": [{"start": None, "value": 24}]}
        ).status_code
        == 200
    )


# --- clearing a day and the Danger Zone --------------------------------------


def _fill_day(client, day, oats):
    entry = {"day": day, "meal": "Lunch", "food_id": oats["id"], "quantity": 50}
    client.post("/api/entries", json=entry)
    run = {"day": day, "type": "Running", "duration_min": 20, "kcal": 200}
    client.post("/api/activities", json=run)
    client.put(f"/api/days/{day}/metrics", json={"steps": 5000, "mood": 4})
    client.put(f"/api/days/{day}/note", json={"text": "good day"})


def test_clear_day_only_touches_that_day(client, oats):
    other = "2026-11-08"
    _fill_day(client, DAY, oats)
    _fill_day(client, other, oats)
    r = client.delete(f"/api/days/{DAY}")
    assert r.status_code == 200
    assert r.json()["counts"] == {"food_log": 1, "activities": 1, "checkins": 1, "notes": 1}
    d = client.get(f"/api/days/{DAY}").json()
    assert d["entries"] == [] and d["activities"] == []
    assert d["metrics"]["steps"] is None and d["metrics"]["mood"] is None
    assert client.get(f"/api/days/{DAY}/note").json()["text"] == ""
    kept = client.get(f"/api/days/{other}").json()
    assert len(kept["entries"]) == 1 and kept["metrics"]["steps"] == 5000
    # the catalog is untouched; clearing an empty day is fine
    assert client.get(f"/api/foods/{oats['id']}").status_code == 200
    assert client.delete(f"/api/days/{DAY}").json()["counts"]["food_log"] == 0


def test_wipe_selected_kinds(client, oats):
    _fill_day(client, DAY, oats)
    meal = {"name": "m", "items": [{"food_id": oats["id"], "quantity": 10}]}
    client.post("/api/saved-meals", json=meal)
    r = client.post("/api/wipe", json={"what": ["activities", "notes"]})
    assert r.json()["counts"] == {"activities": 1, "notes": 1}
    d = client.get(f"/api/days/{DAY}").json()
    assert d["activities"] == [] and len(d["entries"]) == 1 and d["metrics"]["steps"] == 5000

    # wiping the catalog keeps logged entries, and drops saved meals left empty
    r = client.post("/api/wipe", json={"what": ["foods"]})
    assert r.json()["counts"] == {"foods": 1, "saved_meals": 1}
    d = client.get(f"/api/days/{DAY}").json()
    assert d["entries"][0]["food_id"] is None and d["entries"][0]["kcal"] > 0
    assert client.get("/api/saved-meals").json() == []


def test_wipe_everything_and_validation(client, oats):
    _fill_day(client, DAY, oats)
    keys = [t["key"] for t in client.get("/api/vocab").json()["wipe_targets"]]
    assert client.post("/api/wipe", json={"what": keys}).status_code == 200
    d = client.get(f"/api/days/{DAY}").json()
    assert d["entries"] == [] and d["activities"] == [] and d["metrics"]["steps"] is None
    assert client.get("/api/foods").json() == []
    # settings survive: targets and exercise types
    assert client.get("/api/activity-types").json()
    assert client.post("/api/wipe", json={"what": []}).status_code == 422
    assert client.post("/api/wipe", json={"what": ["profile"]}).status_code == 422
