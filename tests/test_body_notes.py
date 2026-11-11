from __future__ import annotations

import datetime as dt

import pytest

DAY = "2026-11-09"
TOMORROW = (dt.date.today() + dt.timedelta(days=1)).isoformat()


def test_day_note_roundtrip(client):
    assert client.get(f"/api/days/{DAY}").json()["note"] == ""
    r = client.put(f"/api/days/{DAY}/note", json={"text": "  Long walk, slept well.  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "Long walk, slept well."}
    assert client.get(f"/api/days/{DAY}").json()["note"] == "Long walk, slept well."

    days = client.get("/api/history", params={"start": DAY, "end": "2026-11-10"}).json()
    assert [d["has_note"] for d in days] == [True, False]

    # empty text deletes it
    assert client.put(f"/api/days/{DAY}/note", json={"text": ""}).json() == {"text": ""}
    assert client.get(f"/api/days/{DAY}/note").json() == {"text": ""}
    assert client.put(f"/api/days/{DAY}/note", json={"text": "x" * 2001}).status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/entries", {"day": TOMORROW, "meal": "Lunch", "name": "x", "kcal": 1}),
        ("post", "/api/activities", {"day": TOMORROW, "type": "Running", "duration_min": 10}),
        ("put", f"/api/days/{TOMORROW}/metrics", {"steps": 1000}),
        ("put", f"/api/days/{TOMORROW}/note", {"text": "hello"}),
    ],
)
def test_future_days_cannot_be_logged(client, method, path, body):
    r = getattr(client, method)(path, json=body)
    assert r.status_code == 422
    assert "future" in r.json()["detail"]


def test_today_can_be_logged(client):
    today = dt.date.today().isoformat()
    r = client.post("/api/entries", json={"day": today, "meal": "Lunch", "name": "x", "kcal": 1})
    assert r.status_code == 201, r.text


def test_weight_and_body_fat(client):
    r = client.put(f"/api/days/{DAY}/metrics", json={"weight_kg": 81.4, "body_fat_pct": 22.5})
    assert r.status_code == 200, r.text
    assert (r.json()["weight_kg"], r.json()["body_fat_pct"]) == (81.4, 22.5)

    day = client.get("/api/days/2026-11-10").json()
    assert day["previous_weight"] == {"day": DAY, "weight_kg": 81.4}
    assert day["estimate_weight_kg"] == 81.4
    same = client.get(f"/api/days/{DAY}").json()
    assert same["previous_weight"] is None  # only earlier days count
    assert same["estimate_weight_kg"] == 81.4
    before = client.get("/api/days/2026-11-08").json()
    assert before["estimate_weight_kg"] == 75  # info/config.toml

    days = client.get("/api/history", params={"start": DAY, "end": DAY}).json()
    assert (days[0]["weight_kg"], days[0]["body_fat_pct"]) == (81.4, 22.5)

    # estimates use the weight in force on the activity's day
    later = client.post(
        "/api/activities", json={"day": "2026-11-10", "type": "Running", "duration_min": 60}
    ).json()
    assert later["kcal"] == pytest.approx(9.8 * 81.4)
    earlier = client.post(
        "/api/activities", json={"day": "2026-11-08", "type": "Running", "duration_min": 60}
    ).json()
    assert earlier["kcal"] == pytest.approx(9.8 * 75)


@pytest.mark.parametrize(
    "bad", [{"weight_kg": 0}, {"weight_kg": 501}, {"body_fat_pct": 0}, {"body_fat_pct": 100}]
)
def test_weight_and_body_fat_validation(client, bad):
    assert client.put(f"/api/days/{DAY}/metrics", json=bad).status_code == 422


def test_profile(client):
    p = client.get("/api/profile").json()
    assert p == {
        "gender": "unspecified",
        "height_cm": None,
        "last_weight": None,
        "estimate_weight_kg": 75,
    }
    r = client.put("/api/profile", json={"gender": "female_trans", "height_cm": 168})
    assert r.status_code == 200, r.text
    assert (r.json()["gender"], r.json()["height_cm"]) == ("female_trans", 168)
    assert client.get("/api/profile").json()["gender"] == "female_trans"

    assert client.put("/api/profile", json={"gender": "robot"}).status_code == 422
    assert client.put("/api/profile", json={"height_cm": 20}).status_code == 422

    genders = [g["key"] for g in client.get("/api/vocab").json()["genders"]]
    assert genders == [
        "male_cis", "female_cis", "male_trans", "female_trans", "other", "unspecified"
    ]


def test_history_baseline_is_latest_before_period(client):
    put = lambda day, body: client.put(f"/api/days/{day}/metrics", json=body)  # noqa: E731
    assert put("2026-10-01", {"weight_kg": 80, "body_fat_pct": 20}).status_code == 200
    put("2026-10-05", {"weight_kg": 81})
    put("2026-10-10", {"weight_kg": 79})  # inside the period: not a baseline
    r = client.get("/api/history/baseline", params={"before": "2026-10-10"}).json()
    assert r["weight_kg"] == {"day": "2026-10-05", "value": 81}
    assert r["body_fat_pct"] == {"day": "2026-10-01", "value": 20}
    r = client.get("/api/history/baseline", params={"before": "2026-10-01"}).json()
    assert r == {"weight_kg": None, "body_fat_pct": None}


def test_body_references_defaults_follow_gender(client):
    r = client.get("/api/body-references").json()
    assert r["gender_group"] == "other" and r["custom"] is False
    assert r["cutoffs"] == r["defaults"]["other"]
    assert [b["key"] for b in r["brackets"]][0] == "underweight"
    assert r["brackets"][0]["min_bmi"] is None and r["brackets"][-1]["max_bmi"] is None
    assert r["brackets"][1]["min_bmi"] == r["cutoffs"][0]

    client.put("/api/profile", json={"gender": "female_trans", "height_cm": 165})
    r = client.get("/api/body-references").json()
    assert (r["gender_group"], r["cutoffs"]) == ("female", r["defaults"]["female"])
    assert r["brackets"][3]["body_type"] == "Curvy"


def test_body_references_custom_and_reset(client):
    cut = [17, 19.5, 23, 27.5, 31]
    r = client.put("/api/body-references", json={"cutoffs": cut}).json()
    assert (r["cutoffs"], r["custom"]) == (cut, True)
    # a gender change keeps the user's own cutoffs
    client.put("/api/profile", json={"gender": "male_cis"})
    assert client.get("/api/body-references").json()["cutoffs"] == cut
    r = client.put("/api/body-references", json={"cutoffs": None}).json()
    assert (r["cutoffs"], r["custom"]) == (r["defaults"]["male"], False)


@pytest.mark.parametrize(
    "bad",
    [
        [18, 20, 25, 30],  # too few
        [0, 20, 25, 30, 35],  # not positive
        [-1, 20, 25, 30, 35],
        [18, 20, 20, 30, 35],  # not strictly increasing
        [18, 25, 20, 30, 35],
    ],
)
def test_body_references_validation(client, bad):
    assert client.put("/api/body-references", json={"cutoffs": bad}).status_code == 422
