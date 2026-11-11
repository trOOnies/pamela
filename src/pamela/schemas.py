"""Request/response models for the HTTP API."""

from __future__ import annotations

import datetime as dt
from itertools import pairwise
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .barcode import normalize_ean

MACRO_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g")

# key -> label. "TACC-free" (sin TACC) means no wheat, oats, barley or rye, i.e. gluten-free.
# The first four form a fork (see DIET_IMPLIES): vegan (nothing of animal origin)
# -> vegetarian (no animals, dairy ok, no eggs), which then splits into pescatarian
# (vegetarian plus fish) and ovolactovegetarian (vegetarian plus eggs). Neither
# branch implies the other. The Help tab has the full definitions.
DIET_TAGS = {
    "pescatarian": "Pescatarian",
    "ovolactovegetarian": "Ovolactovegetarian",
    "vegetarian": "Vegetarian",
    "vegan": "Vegan",
    "kosher": "Kosher",
    "lactose_free": "Lactose-free",
    "peanut_free": "Peanut-free",
    "tacc_free": "TACC-free",
}
DIET_FIELDS = tuple(DIET_TAGS)
# tag -> the broader tags it implies (applied transitively).
DIET_IMPLIES: dict[str, tuple[str, ...]] = {
    "vegan": ("vegetarian",),
    "vegetarian": ("pescatarian", "ovolactovegetarian"),
}
# Tags derived from the values, never set by hand: Calorie-free <=> kcal == 0 (a
# kcal left empty is unknown, not zero).
AUTO_TAGS = {"calorie_free": "Calorie-free"}


def close_diet_tags(tags: set[str]) -> set[str]:
    """``tags`` plus every tag they imply."""
    out = set(tags)
    for tag in DIET_IMPLIES:  # ordered strictest first, so one pass is enough
        if tag in out:
            out.update(DIET_IMPLIES[tag])
    return out

# Overall mood on the common 5-point scale, plus optional feelings.
MOODS = {1: "Awful", 2: "Bad", 3: "Okay", 4: "Good", 5: "Great"}
# Feelings come in groups of related ones; the Day view shows one group per row.
FEELING_GROUPS = {
    "Content": {"happy": "Happy", "calm": "Calm", "grateful": "Grateful"},
    "Driven": {"energetic": "Energetic", "motivated": "Motivated", "focused": "Focused"},
    "Tense": {"stressed": "Stressed", "anxious": "Anxious", "irritable": "Irritable"},
    "Down": {"sad": "Sad", "lonely": "Lonely", "bored": "Bored"},
    "Drained": {"tired": "Tired", "sick": "Unwell"},
}
FEELINGS = {k: label for group in FEELING_GROUPS.values() for k, label in group.items()}

# Stored for the profile only; no calculation uses it.
GENDERS = {
    "male_cis": "Male (cis)",
    "female_cis": "Female (cis)",
    "male_trans": "Male (trans)",
    "female_trans": "Female (trans)",
    "other": "Other",
    "unspecified": "Prefer not to say",
}

NOTE_MAX = 2000

# Daily targets: key -> (label, unit, max). Values are positive integers.
TARGETS = {
    "kcal": ("Calories", "kcal", None),
    "protein_g": ("Protein", "g", None),
    "carbs_g": ("Carbs", "g", None),
    "fat_g": ("Fat", "g", None),
    "fiber_g": ("Fiber", "g", None),
    "steps": ("Steps", "steps", None),
    "sleep_h": ("Sleep", "h", 24),
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
    pescatarian: bool = False
    ovolactovegetarian: bool = False
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
    kcal: float | None = Field(
        None, ge=0, description="Empty = not known yet (counted as 0); 0 = calorie-free"
    )
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
    def _implied_tags(self) -> FoodIn:
        for tag in close_diet_tags({t for t in DIET_IMPLIES if getattr(self, t)}):
            setattr(self, tag, True)
        return self


class Food(Macros, DietTags):
    id: int
    kcal: float | None = Field(description="null = not entered yet; counted as 0")
    name: str
    brand: str
    ean: str | None = None
    basis_qty: float
    unit: str
    serving_qty: float | None = None
    package_qty: float | None = None
    uses: int = 0

    @computed_field
    @property
    def calorie_free(self) -> bool:
        return self.kcal == 0


class FoodDraft(Macros, DietTags):
    """Prefilled food fields from a barcode lookup; not saved yet."""

    ean: str
    kcal: float | None = None
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
    kcal_missing: bool = Field(False, description="The food has no kcal yet (counted as 0)")


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
    # Emoji may be several code points (skin tones, ZWJ sequences); '' = group default.
    emoji: str = Field("", max_length=16)


class ActivityType(BaseModel):
    id: int
    name: str
    category: str
    met: float
    distance: bool
    emoji: str = Field("", description="The type's own emoji; '' when it uses its group's")
    icon: str = Field("", description="The emoji to show: its own, or its group's default")
    category_icon: str = Field("", description="The group's default emoji")
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
    weight_kg: float | None = Field(None, gt=0, le=500)
    body_fat_pct: float | None = Field(None, gt=0, lt=100)

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
    weight_kg: float | None = None
    body_fat_pct: float | None = None


class DayNoteIn(_In):
    text: str = Field("", max_length=NOTE_MAX, description="Empty deletes the note")


class DayNote(BaseModel):
    text: str = ""


class LastWeight(BaseModel):
    day: dt.date
    weight_kg: float


# --- profile -----------------------------------------------------------------


class ProfileIn(_In):
    gender: str = Field("unspecified", description=f"One of: {', '.join(GENDERS)}")
    height_cm: float | None = Field(None, ge=50, le=280)

    @field_validator("gender")
    @classmethod
    def _known_gender(cls, v: str) -> str:
        if v not in GENDERS:
            raise ValueError(f"unknown gender {v!r}")
        return v


class Profile(BaseModel):
    gender: str
    height_cm: float | None
    last_weight: LastWeight | None = Field(
        description="The latest weight logged in a check-in, if any"
    )
    estimate_weight_kg: float = Field(
        description="Weight used for calorie estimates today: the latest logged one, "
        "else the one in info/config.toml"
    )


# --- aggregates --------------------------------------------------------------


class Day(BaseModel):
    day: dt.date
    entries: list[Entry]
    activities: list[Activity]
    totals: Macros
    burned_kcal: float
    active_min: float
    metrics: DayMetrics
    note: str = ""
    previous_weight: LastWeight | None = Field(
        None, description="The latest weight logged before this day"
    )
    estimate_weight_kg: float = Field(description="Weight used for calorie estimates this day")
    targets: dict[str, int | None] = Field(description="Targets in force on this day")


class HistoryDay(Macros):
    day: dt.date
    burned_kcal: float = 0
    active_min: float = 0
    entry_count: int = 0
    steps: int | None = None
    sleep_min: float | None = None
    mood: int | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    has_note: bool = False
    targets: dict[str, int | None] = Field(default_factory=dict)


class Measurement(BaseModel):
    day: dt.date
    value: float


class BodyBaseline(BaseModel):
    """The latest measurements before a period, to compare the period's latest with."""

    weight_kg: Measurement | None = None
    body_fat_pct: Measurement | None = None


# --- targets -----------------------------------------------------------------


class TargetPeriod(_In):
    start: dt.date | None = Field(
        None, description="First day this value applies; null for the very first period"
    )
    value: int = Field(gt=0)


class TargetIn(_In):
    """Either one period (a single value for all history) or several, each in force
    from its start day until the next one starts."""

    periods: list[TargetPeriod] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _ordered(self) -> TargetIn:
        first, *rest = self.periods
        if first.start is not None:
            raise ValueError("the first period must start at the beginning (start: null)")
        starts = [p.start for p in rest]
        if any(s is None for s in starts):
            raise ValueError("only the first period can have no start day")
        if any(a >= b for a, b in pairwise(starts)):
            raise ValueError("periods must be in order, with different start days")
        return self


class Target(BaseModel):
    key: str
    label: str
    unit: str
    max: int | None
    periods: list[TargetPeriod]


class Choice(BaseModel):
    key: str
    label: str
    group: str | None = None


class Vocabulary(BaseModel):
    """Fixed choices the frontend shows (labels live here, in one place)."""

    diet_tags: list[Choice]
    diet_implies: dict[str, list[str]] = Field(description="tag -> the broader tags it implies")
    auto_tags: list[Choice] = Field(description="Tags derived from the values; not settable")
    moods: list[Choice]
    feelings: list[Choice]
    genders: list[Choice]
