from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pamela.app import create_app
from pamela.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(local_dir=tmp_path / "local", info_dir=tmp_path / "info")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def oats(client: TestClient) -> dict:
    r = client.post(
        "/api/foods",
        json={
            "name": "Rolled oats",
            "brand": "Acme",
            "basis_qty": 100,
            "unit": "g",
            "kcal": 380,
            "protein_g": 13,
            "carbs_g": 60,
            "fat_g": 7,
            "fiber_g": 10,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
