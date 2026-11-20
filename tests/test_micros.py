from __future__ import annotations

import pytest

from pamela import barcode

MICROS = ("b12_ug", "vit_d_ug", "caffeine_mg")


@pytest.mark.parametrize("key", MICROS)
def test_micro_is_optional_and_kept(client, oats, key):
    assert oats[key] is None  # not entered yet
    body = {k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "kcal")}
    upd = client.put(f"/api/foods/{oats['id']}", json=body | {key: 0.45})
    assert upd.status_code == 200 and upd.json()[key] == 0.45
    assert client.put(f"/api/foods/{oats['id']}", json=body | {key: -1}).status_code == 422
    # editing without it clears it back to unknown
    assert client.put(f"/api/foods/{oats['id']}", json=body).json()[key] is None


def test_protein_per_100kcal(client, oats):
    assert oats["protein_per_100kcal"] == pytest.approx(oats["protein_g"] / oats["kcal"] * 100)
    body = {k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "protein_g")}
    # unknown or no kcal: no ratio
    assert client.put(f"/api/foods/{oats['id']}", json=body).json()["protein_per_100kcal"] is None
    assert client.put(f"/api/foods/{oats['id']}", json=body | {"kcal": 0}).json()["protein_per_100kcal"] is None


def test_barcode_draft_micros():
    product = {
        "product_name": "Cold brew",
        "nutriments": {"energy-kcal_100g": 2, "caffeine_100g": 0.06, "vitamin-d_100g": 0.0000025},
    }
    d = barcode.product_to_draft("4006381333931", product)
    assert d["caffeine_mg"] == pytest.approx(60)
    assert d["vit_d_ug"] == pytest.approx(2.5)
    assert d["b12_ug"] is None  # missing = unknown
