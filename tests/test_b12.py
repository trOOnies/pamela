from __future__ import annotations


def test_b12_is_optional_and_kept(client, oats):
    assert oats["b12_ug"] is None  # not entered yet
    body = {k: oats[k] for k in ("name", "brand", "basis_qty", "unit", "kcal")}
    upd = client.put(f"/api/foods/{oats['id']}", json=body | {"b12_ug": 0.45})
    assert upd.status_code == 200 and upd.json()["b12_ug"] == 0.45
    assert client.put(f"/api/foods/{oats['id']}", json=body | {"b12_ug": -1}).status_code == 422
    # editing without it clears it back to unknown
    assert client.put(f"/api/foods/{oats['id']}", json=body).json()["b12_ug"] is None
