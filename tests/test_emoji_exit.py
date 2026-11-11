"""Exercise type emojis, and "Save & close"."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from pamela import db
from pamela.app import create_app


def _types(client) -> dict[str, dict]:
    return {t["name"]: t for t in client.get("/api/activity-types").json()}


def test_built_in_types_have_emojis(client):
    types = _types(client)
    assert types["Padel"]["emoji"] == "🎾"
    assert types["Swimming"]["icon"] == "🏊"
    assert types["Walking"]["category_icon"] == db.CATEGORY_EMOJI["Cardio"]
    # every built-in type but "Other" got its own
    assert [n for n, t in types.items() if not t["emoji"]] == ["Other"]
    assert types["Other"]["icon"] == db.CATEGORY_EMOJI["Other"]
    # every built-in group has a default of its own
    assert {t["category"] for t in types.values()} <= set(db.CATEGORY_EMOJI)


def test_type_emoji_set_cleared_and_inherited(client):
    r = client.post("/api/activity-types", json={"name": "Pogo", "category": "Fun", "met": 6})
    t = r.json()
    assert (t["emoji"], t["icon"], t["category_icon"]) == ("", "💪", "💪")

    body = {"name": "Pogo", "category": "Sports", "met": 6, "emoji": " 🦘 "}
    t = client.put(f"/api/activity-types/{t['id']}", json=body).json()
    assert (t["emoji"], t["icon"], t["category_icon"]) == ("🦘", "🦘", "🏅")
    # ZWJ sequences are several code points
    body["emoji"] = "🏃‍♀️‍➡️"
    assert client.put(f"/api/activity-types/{t['id']}", json=body).status_code == 200

    body["emoji"] = ""
    t = client.put(f"/api/activity-types/{t['id']}", json=body).json()
    assert (t["emoji"], t["icon"]) == ("", "🏅")
    body["emoji"] = "x" * 17
    assert client.put(f"/api/activity-types/{t['id']}", json=body).status_code == 422


def test_shutdown_stops_after_responding(settings):
    calls = []
    app = create_app(settings)
    app.state.request_exit = lambda: calls.append("exit")
    with TestClient(app) as client:
        assert client.put("/api/days/2026-11-09/metrics", json={"steps": 1234}).status_code == 200
        r = client.post("/api/shutdown")
        assert r.status_code == 202
        assert calls == ["exit"]
    # the lifespan shutdown folded the WAL into the database file
    wal = settings.db_path.with_name(settings.db_path.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT steps FROM day_metrics").fetchone() == (1234,)
