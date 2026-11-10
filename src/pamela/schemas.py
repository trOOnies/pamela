"""Request/response models for the HTTP API."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .barcode import normalize_ean

MACRO_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")

# key -> label. "TACC-free" (sin TACC) means no wheat, oats, barley or rye, i.e. gluten-free.
DIET_TAGS = {
    "vegetarian": "Vegetarian",
    "vegan": "Vegan",
    "kosher": "Kosher",
    "lactose_free": "Lactose-free",
    "peanut_free": "Peanut-free",
    "tacc_free": "TACC-free",
}
DIET_FIELDS = tuple(DIET_TAGS)

# Overall mood on the common 5-point scale, plus optional feelings.
MOODS = {1: "Awful", 2: "Bad", 3: "Okay", 4: "Good", 5: "Great"}
FEELINGS = {
    "happy": "Happy",
    "calm": "Calm",
    "grateful": "Grateful",
    "energetic": "Energetic",
    "motivated": "Motivated",
    "focused": "Focused",
    "tired": "Tired",
    "stressed": "Stressed",
    "anxious": "Anxious",
    "sad": "Sad",
    "irritable": "Irritable",
    "bored": "Bored",
    "lonely": "Lonely",
    "sick": "Unwell",
}

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


class DietTags(BaseModel):
    vegetarian: bool = False
    vegan: bool = False
    kosher: bool = False
    lactose_free: bool = False
    peanut_free: bool = False
    tacc_free: bool = False


class FoodIn(DietTags, _In):
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field("", max_length=200)
    ean: str | None = Field(None, description="EAN-8/13, UPC-A or GTIN-14 barcode")
    basis_qty: float = Field(100, gt=0)
    unit: str = Field("g", min_length=1, max_length=20)
    kcal: float = NonNeg
    protein_g: float = NonNeg
    carbs_g: float = NonNeg
    fat_g: float = NonNeg
    fiber_g: float = NonNeg
    serving_qty: float | None = Field(None, gt=0, description="One serving, in `unit`")
    package_qty: float | None = Field(None, gt=0, description="Whole package, in `unit`")

    @field_validator("ean")
    @classmethod
    def _ean(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return normalize_ean(v)

    @model_validator(mode="after")
    def _vegan_is_vegetarian(self) -> FoodIn:
        if self.vegan:
            self.vegetarian = True
        return self


class Food(Macros, DietTags):
    id: int
    name: str
    brand: str
    ean: str | None = None
    basis_qty: float
    unit: str
    serving_qty: float | None = None
    package_qty: float | None = None
    uses: int = 0


class FoodDraft(Macros, DietTags):
    """Prefilled food fields from a barcode lookup; not saved yet."""

    ean: str
    name: str
    brand: str
    basis_qty: float
    unit: str
    serving_qty: float | None = None
    package_qty: float | None = None


class BarcodeLookup(BaseModel):
    ean: str
    source: Literal["catalog", "openfoodfacts"] | None = Field(
        description="Where the product was found; null if nowhere"
    )
    food: Food | None = None
    draft: FoodDraft | None = None


# --- saved meals -------------------------------------------------------------


class SavedMealItemIn(_In):
    food_id: int
    quantity: float = Field(gt=0)


class SavedMealIn(_In):
    name: str = Field(min_length=1, max_length=200)
    default_meal: str = Field("", max_length=100)
    items: list[SavedMealItemIn] = Field(min_length=1, max_length=100)


class SavedMealItem(Macros):
    food_id: int
    name: str
    brand: str
    quantity: float
    unit: str
    basis_qty: float
    serving_qty: float | None = None
    package_qty: float | None = None


class SavedMeal(BaseModel):
    id: int
    name: str
    default_meal: str
    items: list[SavedMealItem]
    totals: Macros
    tags: list[str] = Field(description="Diet tags shared by every item")


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


class EntryBatchIn(_In):
    """Several catalog foods logged at once, e.g. a saved meal after editing it."""

    day: dt.date
    meal: str = Field(min_length=1)
    items: list[SavedMealItemIn] = Field(min_length=1, max_length=100)


# --- activities --------------------------------------------------------------


class ActivityTypeIn(_In):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field("Other", min_length=1, max_length=60)
    met: float = Field(gt=0, le=30, description="kcal per kg of body weight per hour")
    distance: bool = False


class ActivityType(BaseModel):
    id: int
    name: str
    category: str
    met: float
    distance: bool
    uses: int = Field(0, description="Times logged in the last 90 days")


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


# --- daily metrics -----------------------------------------------------------


class DayMetricsIn(_In):
    steps: int | None = Field(None, ge=0, le=200_000)
    sleep_min: float | None = Field(None, ge=0, le=24 * 60)
    mood: int | None = Field(None, ge=1, le=5, description="1 awful ... 5 great")
    feelings: list[str] = Field(default_factory=list, max_length=len(FEELINGS))

    @field_validator("feelings")
    @classmethod
    def _known_feelings(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in FEELINGS]
        if unknown:
            raise ValueError(f"unknown feelings: {', '.join(unknown)}")
        return [f for f in FEELINGS if f in v]  # canonical order, no duplicates


class DayMetrics(BaseModel):
    steps: int | None = None
    sleep_min: float | None = None
    mood: int | None = None
    feelings: list[str] = Field(default_factory=list)


# --- aggregates --------------------------------------------------------------


class Day(BaseModel):
    day: dt.date
    entries: list[Entry]
    activities: list[Activity]
    totals: Macros
    burned_kcal: float
    active_min: float
    metrics: DayMetrics


class HistoryDay(Macros):
    day: dt.date
    burned_kcal: float = 0
    active_min: float = 0
    entry_count: int = 0
    steps: int | None = None
    sleep_min: float | None = None
    mood: int | None = None


class Choice(BaseModel):
    key: str
    label: str


class Vocabulary(BaseModel):
    """Fixed choices the frontend shows (labels live here, in one place)."""

    diet_tags: list[Choice]
    moods: list[Choice]
    feelings: list[Choice]
