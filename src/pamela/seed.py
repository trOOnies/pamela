"""Fill an empty database with mock data: ``python -m pamela.seed`` (or ``make seed``).

Meant for a first look around the app before logging real data. It refuses to touch a
database that already holds foods, log entries, activities, check-ins or saved meals.
The data is the same on every run (fixed random seed), ending today.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sqlite3
import sys

from . import db
from .app import prepare
from .config import ConfigStore, Settings
from .schemas import DIET_FIELDS, FEELING_GROUPS
from .tracking import estimate_kcal, scale_macros

USER_TABLES = ("foods", "food_entries", "activities", "day_metrics", "day_notes", "saved_meals")

# name, brand, basis_qty, unit, kcal, protein, carbs, fat, fiber, serving, package, tags
FOODS = [
    ("Rolled oats", "Granja Sol", 100, "g", 380, 13, 60, 7, 10, 40, 500,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free"}),
    ("Whole milk", "La Vaquita", 100, "ml", 62, 3.1, 4.8, 3.3, 0, 200, 1000,
     {"vegetarian", "kosher", "peanut_free", "tacc_free"}),
    ("Greek yogurt, plain", "La Vaquita", 100, "g", 97, 9, 4, 5, 0, 170, 170,
     {"vegetarian", "kosher", "peanut_free", "tacc_free"}),
    ("Banana", "", 1, "unit", 105, 1.3, 27, 0.4, 3.1, None, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Apple", "", 1, "unit", 95, 0.5, 25, 0.3, 4.4, None, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Egg", "", 1, "unit", 72, 6.3, 0.4, 4.8, 0, None, 12,
     {"vegetarian", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Wholemeal bread", "Panadería Norte", 1, "slice", 80, 4, 13, 1.1, 2, None, 20,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free"}),
    ("Peanut butter", "Maní Feliz", 100, "g", 588, 25, 20, 50, 6, 15, 380,
     {"vegetarian", "vegan", "kosher", "lactose_free", "tacc_free"}),
    ("Chicken breast", "", 100, "g", 165, 31, 0, 3.6, 0, 150, None,
     {"lactose_free", "peanut_free", "tacc_free"}),
    ("Lean ground beef", "", 100, "g", 176, 20, 0, 10, 0, 150, 500,
     {"lactose_free", "peanut_free", "tacc_free"}),
    ("Salmon fillet", "", 100, "g", 208, 20, 0, 13, 0, 150, None,
     {"kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Canned tuna in water", "Mar Azul", 100, "g", 116, 26, 0, 1, 0, 120, 120,
     {"kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("White rice, cooked", "", 100, "g", 130, 2.7, 28, 0.3, 0.4, 180, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Pasta, cooked", "", 100, "g", 158, 5.8, 31, 0.9, 1.8, 200, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free"}),
    ("Potato, boiled", "", 100, "g", 87, 1.9, 20, 0.1, 1.8, 200, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Lentils, cooked", "", 100, "g", 116, 9, 20, 0.4, 7.9, 200, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Mixed salad", "", 100, "g", 20, 1.4, 3.5, 0.2, 1.8, 150, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Broccoli", "", 100, "g", 34, 2.8, 7, 0.4, 2.6, 150, None,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Olive oil", "Olivar", 100, "ml", 884, 0, 0, 100, 0, 10, 500,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Cheddar cheese", "La Vaquita", 100, "g", 403, 25, 1.3, 33, 0, 30, 200,
     {"vegetarian", "peanut_free", "tacc_free"}),
    ("Whey protein", "PowerUp", 100, "g", 400, 78, 8, 6, 0, 30, 1000,
     {"vegetarian", "peanut_free", "tacc_free"}),
    ("Almonds", "", 100, "g", 579, 21, 22, 50, 12.5, 30, 250,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Dark chocolate 70%", "Cacao Sur", 100, "g", 598, 7.8, 46, 43, 11, 25, 100,
     {"vegetarian", "vegan", "kosher", "lactose_free"}),
    ("Rice cakes", "Crocante", 1, "unit", 35, 0.7, 7.3, 0.3, 0.4, None, 18,
     {"vegetarian", "vegan", "kosher", "lactose_free", "peanut_free", "tacc_free"}),
    ("Pizza slice, mozzarella", "", 1, "slice", 285, 12, 36, 10, 2.5, None, 8,
     {"vegetarian"}),
]

# Typical plates per meal slot: (food name, quantity, ±random spread as a fraction).
PLATES = {
    "breakfast": [
        [("Rolled oats", 50, 0.2), ("Whole milk", 200, 0.2), ("Banana", 1, 0)],
        [("Wholemeal bread", 2, 0), ("Egg", 2, 0), ("Whole milk", 150, 0.2)],
        [("Greek yogurt, plain", 170, 0), ("Rolled oats", 30, 0.2), ("Apple", 1, 0)],
        [("Wholemeal bread", 2, 0), ("Peanut butter", 20, 0.3), ("Banana", 1, 0)],
    ],
    "lunch": [
        [("Chicken breast", 160, 0.2), ("White rice, cooked", 200, 0.2),
         ("Mixed salad", 150, 0.3), ("Olive oil", 10, 0.3)],
        [("Lean ground beef", 150, 0.2), ("Pasta, cooked", 220, 0.2)],
        [("Lentils, cooked", 250, 0.2), ("White rice, cooked", 120, 0.2),
         ("Mixed salad", 100, 0.3)],
        [("Canned tuna in water", 120, 0), ("Potato, boiled", 200, 0.2),
         ("Egg", 1, 0), ("Olive oil", 10, 0.3)],
    ],
    "snack": [
        [("Apple", 1, 0), ("Almonds", 25, 0.3)],
        [("Whey protein", 30, 0), ("Whole milk", 250, 0.2)],
        [("Rice cakes", 3, 0), ("Peanut butter", 15, 0.3)],
        [("Greek yogurt, plain", 170, 0), ("Dark chocolate 70%", 15, 0.4)],
    ],
    "dinner": [
        [("Salmon fillet", 150, 0.2), ("Potato, boiled", 200, 0.2), ("Broccoli", 150, 0.2)],
        [("Chicken breast", 150, 0.2), ("Broccoli", 150, 0.2), ("Olive oil", 10, 0.3)],
        [("Pasta, cooked", 200, 0.2), ("Cheddar cheese", 30, 0.3), ("Mixed salad", 120, 0.3)],
        [("Pizza slice, mozzarella", 3, 0)],
    ],
}
SLOTS = list(PLATES)

SAVED_MEALS = [
    ("Usual breakfast", "breakfast", PLATES["breakfast"][0]),
    ("Post-workout shake", "snack", PLATES["snack"][1]),
    ("Chicken & rice", "lunch", PLATES["lunch"][0]),
]

# type, minutes, km per minute (None = no distance), days of the week (0 = Monday)
WORKOUTS = [
    ("Running", 35, 0.17, {1, 5}),
    ("Strength training", 55, None, {0, 3}),
    ("Yoga", 40, None, {2}),
    ("Cycling", 70, 0.4, {6}),
    ("Walking the dog", 30, 0.08, {0, 1, 2, 3, 4, 5, 6}),
]


# A few words on the day, picked by mood (1 awful ... 5 great).
NOTES = {
    5: ["Great day, lots of energy.", "Hit a new best on my run!", "Lovely dinner with friends."],
    4: ["Good day overall.", "Workout felt easy today.", "Productive at work, nice walk after."],
    3: ["Normal day, nothing special.", "A bit busy, ate on the go.", "Rainy, stayed in."],
    2: ["Stressful deadline at work.", "Slept badly, dragged through the day."],
    1: ["Felt unwell, rested most of the day.", "Rough day."],
}


def _is_empty(conn: sqlite3.Connection) -> bool:
    return not any(
        conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in USER_TABLES
    )


def _slot(meal_names: list[str], index: int) -> str:
    """The plate slot for the meal at ``index``: matched by name, else by position."""
    name = meal_names[index].lower()
    for slot in SLOTS:
        if slot in name:
            return slot
    return SLOTS[min(index, len(SLOTS) - 1)]


def _amount(rng: random.Random, qty: float, spread: float, unit: str) -> float:
    value = qty * rng.uniform(1 - spread, 1 + spread)
    if unit not in ("unit", "slice"):
        value *= 1.25  # the plates above are on the light side
    return round(value) if unit in ("unit", "slice") else round(value / 5) * 5 or qty


def seed(conn: sqlite3.Connection, meal_names: list[str], weight_kg: float,
         days: int, today: dt.date) -> dict[str, int]:
    rng = random.Random(42)
    start = today - dt.timedelta(days=days - 1)

    foods: dict[str, dict] = {}
    for name, brand, basis, unit, kcal, p, c, f, fib, serving, package, tags in FOODS:
        tag_values = [int(t in tags) for t in DIET_FIELDS]
        cur = conn.execute(
            f"""INSERT INTO foods (name, brand, basis_qty, unit, kcal, protein_g, carbs_g,
                  fat_g, fiber_g, serving_qty, package_qty, {", ".join(DIET_FIELDS)})
                VALUES ({", ".join("?" * (11 + len(DIET_FIELDS)))})""",
            (name, brand, basis, unit, kcal, p, c, f, fib, serving, package, *tag_values),
        )
        foods[name] = conn.execute("SELECT * FROM foods WHERE id = ?", (cur.lastrowid,)).fetchone()

    for name, slot, plate in SAVED_MEALS:
        default = next((m for i, m in enumerate(meal_names) if _slot(meal_names, i) == slot), "")
        meal_id = conn.execute(
            "INSERT INTO saved_meals (name, default_meal) VALUES (?, ?)", (name, default)
        ).lastrowid
        conn.executemany(
            "INSERT INTO saved_meal_items (saved_meal_id, food_id, quantity, position) "
            "VALUES (?, ?, ?, ?)",
            [(meal_id, foods[f]["id"], qty, pos) for pos, (f, qty, _s) in enumerate(plate)],
        )

    mets = {r["name"]: r["met"] for r in conn.execute("SELECT name, met FROM activity_types")}
    feelings_by_mood = {
        5: ["happy", "energetic", "grateful", "motivated", "calm"],
        4: ["calm", "focused", "happy", "motivated"],
        3: ["tired", "focused", "bored", "calm"],
        2: ["stressed", "tired", "anxious", "irritable"],
        1: ["sad", "sick", "tired", "lonely"],
    }
    known_feelings = {k for group in FEELING_GROUPS.values() for k in group}

    counts = dict.fromkeys(
        ("foods", "saved meals", "entries", "activities", "check-ins", "weigh-ins", "notes"), 0
    )
    logged_weight = weight_kg  # what calorie estimates use until the first weigh-in
    counts["foods"], counts["saved meals"] = len(foods), len(SAVED_MEALS)

    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        iso = day.isoformat()
        is_today = day == today
        if not is_today and rng.random() < 0.05:
            continue  # a day off from logging, as happens

        # Weight drifts down slowly and is logged most mornings; body fat on Mondays.
        checkin = rng.random() >= 0.1
        weight = body_fat = None
        if checkin and (is_today or rng.random() < 0.6):
            weight = round(82.0 - 0.035 * offset + rng.gauss(0, 0.35), 1)
            logged_weight = weight
            counts["weigh-ins"] += 1
        if checkin and day.weekday() == 0:
            body_fat = round(24.5 - 0.02 * offset + rng.gauss(0, 0.3), 1)

        # Today only has the first meals, as if it were midday.
        names = meal_names[:2] if is_today else meal_names
        for i, meal in enumerate(names):
            slot = _slot(meal_names, i)
            if slot == "snack" and rng.random() < 0.15:
                continue
            for food_name, qty, spread in rng.choice(PLATES[slot]):
                food = foods[food_name]
                amount = _amount(rng, qty, spread, food["unit"])
                macros = scale_macros(food, amount)
                conn.execute(
                    """INSERT INTO food_entries (day, meal, food_id, name, quantity, unit,
                         kcal, protein_g, carbs_g, fat_g, fiber_g)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (iso, meal, food["id"], food["name"], amount, food["unit"],
                     *(macros[k] for k in ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"))),
                )
                counts["entries"] += 1

        active = False
        for wtype, minutes, km_per_min, weekdays in WORKOUTS:
            chance = 0.5 if wtype == "Walking the dog" else 0.8
            if day.weekday() not in weekdays or rng.random() > chance or is_today:
                continue
            duration = round(minutes * rng.uniform(0.8, 1.25))
            distance = None
            if km_per_min:
                distance = round(duration * km_per_min * rng.uniform(0.9, 1.1), 1)
            conn.execute(
                """INSERT INTO activities (day, type, duration_min, distance_km, kcal,
                     kcal_estimated) VALUES (?, ?, ?, ?, ?, 1)""",
                (iso, wtype, duration, distance,
                 estimate_kcal(mets[wtype], logged_weight, duration)),
            )
            counts["activities"] += 1
            active = active or wtype != "Walking the dog"

        if not checkin:
            continue
        sleep_min = round(rng.gauss(445, 45) / 5) * 5
        steps = max(1500, round(rng.gauss(9500 if active else 6500, 2200)))
        mood = round(3.2 + (sleep_min - 445) / 60 + (0.5 if active else 0) + rng.gauss(0, 0.7))
        mood = min(5, max(1, mood))
        feelings = rng.sample(feelings_by_mood[mood], k=rng.randint(0, 2))
        feelings = [f for f in feelings if f in known_feelings]
        conn.execute(
            "INSERT INTO day_metrics (day, steps, sleep_min, mood, feelings, weight_kg, "
            "body_fat_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (iso, None if is_today else steps, sleep_min, mood, ",".join(feelings), weight,
             body_fat),
        )
        counts["check-ins"] += 1
        if not is_today and rng.random() < 0.3:
            conn.execute(
                "INSERT INTO day_notes (day, text) VALUES (?, ?)", (iso, rng.choice(NOTES[mood]))
            )
            counts["notes"] += 1

    # A height, so BMI shows up; gender stays "Prefer not to say".
    conn.execute("UPDATE profile SET height_cm = 178 WHERE id = 1 AND height_cm IS NULL")

    # One target with a mid-history change, so the chart target line steps.
    change = (start + dt.timedelta(days=days // 2)).isoformat()
    conn.execute("DELETE FROM target_periods WHERE key = 'kcal'")
    conn.executemany(
        "INSERT INTO target_periods (key, start_day, value) VALUES ('kcal', ?, ?)",
        [(None, 2300), (change, 2100)],
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pamela.seed", description="Fill an empty Pamela database with mock data."
    )
    parser.add_argument("--days", type=int, default=60, help="days of history (default 60)")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")

    settings = Settings.from_env()
    store = ConfigStore(settings.config_path)
    prepare(settings, store)
    config = store.get()  # raises with a readable message if info/config.toml is broken

    with db.session(settings.db_path) as conn:
        if not _is_empty(conn):
            print(
                f"{settings.db_path} already has data; not seeding.\n"
                "To start over with mock data, move or delete that file first.",
                file=sys.stderr,
            )
            return 1
        counts = seed(
            conn, config.meals.names, config.profile.weight_kg, args.days, dt.date.today()
        )

    summary = ", ".join(f"{n} {what}" for what, n in counts.items())
    print(f"Seeded {settings.db_path}: {summary}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
