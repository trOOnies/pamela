"""Request/response models for the HTTP API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

MACRO_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")

NonNeg = Field(0, ge=0)
OptNonNeg = Field(None, ge=0)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Macros(BaseModel):
    kcal: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0


# --- foods -------------------------------------------------------------------


class FoodIn(_In):
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field("", max_length=200)
    basis_qty: float = Field(100, gt=0)
    unit: str = Field("g", min_length=1, max_length=20)
    kcal: float = NonNeg
    protein_g: float = NonNeg
    carbs_g: float = NonNeg
    fat_g: float = NonNeg
    fiber_g: float = NonNeg


class Food(Macros):
    id: int
    name: str
    brand: str
    basis_qty: float
    unit: str
    uses: int = 0


# --- food entries ------------------------------------------------------------


class EntryIn(_In):
    """Either ``food_id`` + ``quantity`` (macros are computed from the food),
    or a quick-add with ``name`` and the macros given directly."""

    day: dt.date
    meal: str = Field(min_length=1)
    food_id: int | None = None
    quantity: float | None = Field(None, gt=0)
    name: str | None = Field(None, max_length=200)
    kcal: float | None = OptNonNeg
    protein_g: float | None = OptNonNeg
    carbs_g: float | None = OptNonNeg
    fat_g: float | None = OptNonNeg
    fiber_g: float | None = OptNonNeg

    @model_validator(mode="after")
    def _food_or_quick(self) -> EntryIn:
        if self.food_id is not None:
            if self.quantity is None:
                raise ValueError("quantity is required when logging a food")
        elif not self.name:
            raise ValueError("either food_id or name is required")
        return self


class Entry(Macros):
    id: int
    day: dt.date
    meal: str
    food_id: int | None
    name: str
    quantity: float | None
    unit: str


# --- activities --------------------------------------------------------------


class ActivityIn(_In):
    day: dt.date
    type: str = Field(min_length=1, max_length=100)
    duration_min: float = Field(gt=0, le=24 * 60)
    distance_km: float | None = OptNonNeg
    kcal: float | None = Field(None, ge=0, description="Leave empty to estimate from MET")
    notes: str = Field("", max_length=1000)


class Activity(BaseModel):
    id: int
    day: dt.date
    type: str
    duration_min: float
    distance_km: float | None
    kcal: float
    kcal_estimated: bool
    notes: str


# --- aggregates --------------------------------------------------------------


class Day(BaseModel):
    day: dt.date
    entries: list[Entry]
    activities: list[Activity]
    totals: Macros
    burned_kcal: float
    active_min: float


class HistoryDay(Macros):
    day: dt.date
    burned_kcal: float = 0
    active_min: float = 0
    entry_count: int = 0
