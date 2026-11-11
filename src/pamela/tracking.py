"""Pure calculation helpers (no I/O)."""

from __future__ import annotations

from collections.abc import Mapping

from .schemas import MACRO_FIELDS


def scale_macros(food: Mapping[str, float | None], quantity: float) -> dict[str, float]:
    """Macros for ``quantity`` of a food whose values are given per ``basis_qty``.
    A value not entered yet (None, e.g. a food's unknown kcal) counts as 0."""
    factor = quantity / food["basis_qty"]
    return {k: (food[k] or 0) * factor for k in MACRO_FIELDS}


def target_on(periods: list[tuple[str | None, int]], day: str) -> int | None:
    """The value in force on ``day`` (ISO date), given ``(start_day, value)`` pairs
    sorted by start day with the open-ended first period (start ``None``) first."""
    value = None
    for start, v in periods:
        if start is None or start <= day:
            value = v
        else:
            break
    return value


def estimate_kcal(met: float, weight_kg: float, duration_min: float) -> float:
    """Calories burned: MET x body weight (kg) x hours."""
    return met * weight_kg * duration_min / 60
