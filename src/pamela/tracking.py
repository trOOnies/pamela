"""Pure calculation helpers (no I/O)."""

from __future__ import annotations

from collections.abc import Mapping

from .schemas import MACRO_FIELDS


def scale_macros(food: Mapping[str, float], quantity: float) -> dict[str, float]:
    """Macros for ``quantity`` of a food whose values are given per ``basis_qty``."""
    factor = quantity / food["basis_qty"]
    return {k: food[k] * factor for k in MACRO_FIELDS}


def estimate_kcal(met: float, weight_kg: float, duration_min: float) -> float:
    """Calories burned: MET x body weight (kg) x hours."""
    return met * weight_kg * duration_min / 60
