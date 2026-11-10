from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from pamela import seed
from pamela.app import create_app


def test_seed_fills_an_empty_database(settings, monkeypatch, capsys):
    monkeypatch.setenv("PAMELA_LOCAL_DIR", str(settings.local_dir))
    monkeypatch.setenv("PAMELA_INFO_DIR", str(settings.info_dir))

    assert seed.main(["--days", "30"]) == 0
    assert "Seeded" in capsys.readouterr().out

    # The app reads every seeded row through its own models.
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/foods").json()) == len(seed.FOODS)
        assert len(client.get("/api/saved-meals").json()) == len(seed.SAVED_MEALS)
        today = dt.date.today()
        start = today - dt.timedelta(days=29)
        history = client.get(
            "/api/history", params={"start": start.isoformat(), "end": today.isoformat()}
        )
        assert history.status_code == 200, history.text
        assert client.get(f"/api/days/{today.isoformat()}").status_code == 200
        kcal = next(t for t in client.get("/api/targets").json() if t["key"] == "kcal")
        assert [p["value"] for p in kcal["periods"]] == [2300, 2100]

    # A second run leaves the data alone.
    assert seed.main([]) == 1
    assert "already has data" in capsys.readouterr().err
