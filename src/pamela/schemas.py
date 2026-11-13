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

# What kind of food it is: key -> (label, emoji). One group per food, optional.
FOOD_GROUPS = {
    "carbs": ("Carbs (bread, pasta, rice, grains)", "🍞"),
    "legumes": ("Legumes", "🫘"),
    "vegetables": ("Vegetables", "🥦"),
    "fruits": ("Fruits", "🍎"),
    "fish": ("Fish & seafood", "🐟"),
    "meat": ("Meat", "🥩"),
    "chicken": ("Chicken & poultry", "🍗"),
    "eggs": ("Eggs", "🥚"),
    "dairy": ("Dairy", "🧀"),
    "nuts_seeds": ("Nuts & seeds", "🥜"),
    "oils_fats": ("Oils & fats", "🫒"),
    "sweets": ("Sweets", "🍫"),
    "cookies": ("Cookies", "🍪"),
    "snacks": ("Snacks", "🍿"),
    "drinks": ("Drinks", "🥤"),
    "alcoholic": ("Alcoholic drinks", "🍷"),
    "sweeteners": ("Sweeteners", "🍯"),
    "seasoning": ("Seasoning & spices", "🧂"),
    "sauces": ("Sauces & spreads", "🥫"),
    "base": ("Base ingredients (flour, premixes)", "🥣"),
    "prepared": ("Prepared meals", "🍱"),
    "supplements": ("Supplements", "💊"),
    "other": ("Other", "✨"),
}
FoodGroup = Literal[tuple(FOOD_GROUPS)]  # type: ignore[valid-type]

# Suggested units; any other is fine too. "u" is one piece of a pack (an egg from
# a carton, a cookie), "whole" one whole item (an apple).
UNITS = ("g", "ml", "u", "whole", "slice", "serving", "cup", "tbsp")
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

# Weight references: six brackets split by five BMI cutoffs (the lower bound of
# each bracket after the first). The defaults follow a stereotypical Western idea
# of body shapes, per gender group; the user can set their own cutoffs.
BODY_BRACKETS = {
    "underweight": "Underweight",
    "slim": "Slim",
    "average": "Average",
    "overweight": "Overweight",
    "obese": "Obese",
    "severely_obese": "Severely obese",
}
BODY_TYPES = {
    "male": ("Skinny", "Lean", "Average build", "Stocky", "Heavyset", "Very heavyset"),
    "female": ("Skinny", "Slender", "Average build", "Curvy", "Full-figured", "Plus-size"),
    "other": ("Skinny", "Slim", "Average build", "Sturdy", "Heavy", "Very heavy"),
}
BMI_DEFAULTS = {
    "male": (18.5, 21.0, 25.0, 30.0, 35.0),
    "female": (18.5, 20.0, 24.0, 28.0, 33.0),
    "other": (18.5, 20.5, 24.5, 29.0, 34.0),
}
BMI_CUTOFFS = len(BODY_BRACKETS) - 1


def gender_group(gender: str) -> str:
    """"male", "female" or "other", for the weight references."""
    if gender.startswith("male"):
        return "male"
    if gender.startswith("female"):
        return "female"
    return "other"

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
    food_group: FoodGroup | Literal[""] = Field("", description="'' = no group")

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
    food_group: str = ""
    uses: int = 0
    in_stock: float | None = Field(
        None, description="What's left in Groceries, in `unit`; null if never bought there"
    )

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
    from_stock: float = Field(0, description="How much of it was taken from Groceries")


class EntryBatchIn(_In):
    """Several catalog foods logged at once, e.g. a saved meal after editing it."""

    day: dt.date
    meal: str = Field(min_length=1)
    items: list[SavedMealItemIn] = Field(min_length=1, max_length=100)


# --- groceries ---------------------------------------------------------------

STORE_MAX = 100


def _expiry_after_purchase(bought_on: dt.date, expires_on: dt.date | None) -> None:
    if expires_on is not None and expires_on < bought_on:
        raise ValueError("the expiry date can't be before the day it was bought")


class CartItemIn(_In):
    id: int | None = Field(None, description="The item, when changing a cart; null = new")
    food_id: int
    quantity: float = Field(gt=0, description="In the food's unit")
    expires_on: dt.date | None = None
    price: float | None = Field(None, ge=0, description="What this item cost in total")


class CartExtraIn(_In):
    """Something in the cart that isn't food: it only counts towards the total."""

    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(1, gt=0)
    unit: str = Field("u", min_length=1, max_length=20)
    price: float | None = Field(None, ge=0, description="What it cost in total")


class CartIn(_In):
    """One trip to the shops: the foods bought that day, maybe at one store, plus any
    other items, and a discount on the subtotal."""

    bought_on: dt.date
    store: str = Field("", max_length=STORE_MAX)
    items: list[CartItemIn] = Field(default_factory=list, max_length=200)
    extras: list[CartExtraIn] = Field(default_factory=list, max_length=200)
    discount: float | None = Field(None, gt=0, description="An amount off the subtotal")
    discount_pct: float | None = Field(
        None, gt=0, le=100, description="A percentage off the subtotal"
    )
    delivery_fee: float | None = Field(
        None, ge=0, description="Added to the total, after the discount; null = none"
    )

    @model_validator(mode="after")
    def _check(self) -> CartIn:
        if not self.items and not self.extras:
            raise ValueError("a cart needs at least one item")
        if self.discount is not None and self.discount_pct is not None:
            raise ValueError("give the discount as an amount or as a percentage, not both")
        for it in self.items:
            _expiry_after_purchase(self.bought_on, it.expires_on)
        return self


class ExpiredIn(_In):
    day: dt.date = Field(description="When it expired or was thrown out")
    quantity: float | None = Field(None, gt=0, description="null = all that's left")


class Lot(BaseModel):
    """One item of a cart, with what's left of it."""

    id: int
    cart_id: int
    food_id: int
    quantity: float = Field(description="How much was bought")
    remaining: float
    eaten: float = Field(description="Taken by logged food entries")
    expired: float = Field(description="Thrown out")
    bought_on: dt.date
    expires_on: dt.date | None = None
    price: float | None = None
    store: str = ""


class StockItem(BaseModel):
    """A food that was ever bought, with what's left of it."""

    food_id: int
    name: str
    brand: str
    unit: str
    serving_qty: float | None = None
    package_qty: float | None = None
    food_group: str = ""
    in_stock: float
    next_expiry: dt.date | None = Field(description="Earliest expiry among what's left")
    last_bought: dt.date
    last_quantity: float = Field(description="How much was bought the last time")
    lots: list[Lot] = Field(description="Purchases with something left, first to use first")


class CartItem(Lot):
    name: str
    brand: str
    unit: str
    package_qty: float | None = None
    food_group: str = ""


class CartExtra(BaseModel):
    id: int
    name: str
    quantity: float
    unit: str
    price: float | None = None


class Cart(BaseModel):
    id: int
    bought_on: dt.date
    store: str
    items: list[CartItem] = Field(description="Foods, which go into the stock")
    extras: list[CartExtra] = Field(description="Other items: only part of the total")
    subtotal: float | None = Field(description="Sum of the prices given; null if none")
    discount: float | None = Field(description="The discount, if given as an amount")
    discount_pct: float | None = Field(description="The discount, if given as a percentage")
    discount_amount: float = Field(0, description="What the discount takes off")
    delivery_fee: float | None = None
    total_price: float | None = Field(
        description="Subtotal minus the discount plus the delivery fee; null if no prices"
    )


class Expiry(BaseModel):
    id: int
    lot_id: int
    cart_id: int
    day: dt.date
    food_id: int
    name: str
    brand: str
    unit: str
    food_group: str = ""
    quantity: float


class Groceries(BaseModel):
    items: list[StockItem]
    carts: list[Cart] = Field(description="Newest first")
    expired: list[Expiry] = Field(description="What expired lately, newest first")


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
    # Optional conditions
    start_time: str | None = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="Time of day, HH:MM"
    )
    temp_c: float | None = Field(None, ge=-60, le=60, description="Temperature, °C")
    humidity_pct: float | None = Field(None, ge=0, le=100)
    wind_kmh: float | None = Field(None, ge=0, le=300)
    comfort: int | None = Field(None, ge=1, le=5, description="How it felt, 1 to 5 stars")


class Activity(BaseModel):
    id: int
    day: dt.date
    type: str
    duration_min: float
    distance_km: float | None
    kcal: float
    kcal_estimated: bool
    notes: str
    start_time: str | None = None
    temp_c: float | None = None
    humidity_pct: float | None = None
    wind_kmh: float | None = None
    comfort: int | None = None


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


class BodyReferencesIn(_In):
    cutoffs: list[float] | None = Field(
        description="BMI cutoffs between the brackets; null = the defaults for the gender",
    )

    @field_validator("cutoffs")
    @classmethod
    def _increasing(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        if len(v) != BMI_CUTOFFS:
            raise ValueError(f"exactly {BMI_CUTOFFS} cutoffs are needed")
        if any(not 0 < c <= 200 for c in v):
            raise ValueError("cutoffs must be above 0 (and at most 200)")
        if any(a >= b for a, b in pairwise(v)):
            raise ValueError("each cutoff must be higher than the one before")
        return v


class BodyBracket(BaseModel):
    key: str
    label: str
    body_type: str
    min_bmi: float | None = Field(description="null for the first bracket")
    max_bmi: float | None = Field(description="null for the last bracket")


class BodyReferences(BaseModel):
    gender_group: Literal["male", "female", "other"]
    cutoffs: list[float]
    custom: bool = Field(description="False while the defaults for the gender are used")
    defaults: dict[str, list[float]]
    brackets: list[BodyBracket]


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


# --- wiping data --------------------------------------------------------------

# What the Danger Zone can wipe: key -> (label, what it means).
WIPE_TARGETS = {
    "food_log": ("Food log", "Every food entry logged on any day"),
    "activities": ("Activities", "Every activity logged on any day"),
    "checkins": ("Check-ins", "Steps, sleep, mood, feelings, weight and body fat of every day"),
    "notes": ("Day notes", "The note of every day"),
    "saved_meals": ("Saved meals", "All your saved meals"),
    "groceries": (
        "Groceries",
        "Every cart and expiry in Groceries. Logged days stay as they are",
    ),
    "foods": (
        "Food catalog",
        "Every food in Foods. Logged days keep their values; saved meals and groceries lose "
        "those foods",
    ),
}


class WipeIn(_In):
    what: list[Literal[tuple(WIPE_TARGETS)]] = Field(  # type: ignore[valid-type]
        min_length=1, description="What to delete for good"
    )


class Deleted(BaseModel):
    """How many rows went, per kind."""

    counts: dict[str, int]


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


class WipeChoice(BaseModel):
    key: str
    label: str
    hint: str


class FoodGroupChoice(BaseModel):
    key: str
    label: str
    emoji: str


class Vocabulary(BaseModel):
    """Fixed choices the frontend shows (labels live here, in one place)."""

    diet_tags: list[Choice]
    diet_implies: dict[str, list[str]] = Field(description="tag -> the broader tags it implies")
    auto_tags: list[Choice] = Field(description="Tags derived from the values; not settable")
    food_groups: list[FoodGroupChoice]
    wipe_targets: list[WipeChoice] = Field(description="What the Danger Zone can wipe")
    units: list[str] = Field(description="Suggested food units")
    moods: list[Choice]
    feelings: list[Choice]
    genders: list[Choice]
