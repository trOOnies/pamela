"""Barcodes (EAN/UPC/GTIN) and product lookup on Open Food Facts.

Open Food Facts (https://world.openfoodfacts.org) is a free, collaborative
database of food products. Only the barcode is sent; nothing about the user.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import __version__

OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
# "quantity" must be asked for: without it, product_quantity is left out whenever
# nutriments are requested too.
OFF_FIELDS = (
    "code,product_name,generic_name,brands,nutriments,quantity,product_quantity,"
    "product_quantity_unit,serving_quantity,serving_quantity_unit,labels_tags,"
    "ingredients_analysis_tags,allergens_tags"
)
USER_AGENT = f"pamela/{__version__} (personal food tracker)"
TIMEOUT_S = 8


class LookupUnavailable(Exception):
    """Open Food Facts could not be reached or answered with an error."""


def normalize_ean(raw: str) -> str:
    """Digits only, with a valid check digit. UPC-A (12 digits) becomes EAN-13.

    Raises ValueError with a readable message otherwise."""
    code = re.sub(r"[\s-]", "", raw)
    if not code.isdigit():
        raise ValueError("a barcode has digits only")
    if len(code) not in (8, 12, 13, 14):
        raise ValueError("a barcode has 8, 12, 13 or 14 digits")
    body, check = code[:-1], int(code[-1])
    # GTIN check digit: weights 3,1,3,1... from the right, excluding the check digit
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    if (10 - total % 10) % 10 != check:
        raise ValueError("the barcode's check digit doesn't match; check for a typo")
    if len(code) == 12:
        code = "0" + code
    return code


def fetch_product(code: str) -> dict[str, Any] | None:
    """The Open Food Facts product for ``code``, or None if it isn't there."""
    url = OFF_PRODUCT_URL.format(code=code) + "?" + urllib.parse.urlencode({"fields": OFF_FIELDS})
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
            data = json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LookupUnavailable(f"Open Food Facts answered {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LookupUnavailable(f"couldn't reach Open Food Facts ({e})") from e
    if data.get("status") != 1:
        return None
    return data.get("product") or None


def _num(v: Any) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _has_tag(tags: list[str], *needles: str) -> bool:
    return any(any(n in t for n in needles) for t in tags)


_ENERGY = ("energy-kcal", "energy")
_MACROS = ("proteins", "carbohydrates", "fat", "fiber")


def product_to_draft(code: str, product: dict[str, Any]) -> dict[str, Any]:
    """Food fields prefilled from an Open Food Facts product.

    The values are per serving when the product has them (as on the label, where
    they're easiest to check), else per 100 g/ml; the form converts them to per
    100 g/ml when the food is saved. Diet tags are only set when the product says so (labels or ingredient
    analysis) and its allergens don't contradict it; the user reviews the
    result before saving it."""
    n = product.get("nutriments") or {}
    # alcohol_100g is the alcohol content in % vol; under 0.5 % counts as alcohol-free
    abv = _num(n.get("alcohol_100g"))
    alcoholic = abv is not None and abv >= 0.5

    serving = _num(product.get("serving_quantity")) or None
    per_serving = (
        serving is not None
        and not alcoholic  # entered by alcohol content, per 100 ml
        and any(_num(n.get(f"{k}_serving")) is not None for k in _ENERGY + _MACROS)
    )
    per = "_serving" if per_serving else "_100g"
    kcal = _num(n.get(f"energy-kcal{per}"))
    if kcal is None and (kj := _num(n.get(f"energy{per}"))) is not None:
        kcal = kj / 4.184  # energy is in kJ

    units = {
        str(product.get(k) or "").lower()
        for k in ("product_quantity_unit", "serving_quantity_unit")
    }
    unit = "ml" if units & {"ml", "cl", "l"} else "g"

    labels = [str(t).lower() for t in product.get("labels_tags") or []]
    analysis = [str(t).lower() for t in product.get("ingredients_analysis_tags") or []]
    allergens = [str(t).lower() for t in product.get("allergens_tags") or []]

    vegan = "en:vegan" in labels or "en:vegan" in analysis
    vegetarian = vegan or "en:vegetarian" in labels or "en:vegetarian" in analysis

    def r(v: float | None) -> float:
        return round(v or 0, 2)

    def micro(key: str, scale: float) -> float | None:
        """An optional value, which Open Food Facts keeps in grams; missing = unknown."""
        v = None if alcoholic else _num(n.get(f"{key}{per}"))
        return None if v is None else round(v * scale, 2)

    return {
        "ean": code,
        "name": (product.get("product_name") or product.get("generic_name") or "").strip(),
        "brand": (product.get("brands") or "").split(",")[0].strip(),
        "basis_qty": serving if per_serving else 100,
        "unit": unit,
        "kcal": None if kcal is None else r(kcal),  # missing = unknown, not 0
        "protein_g": r(_num(n.get(f"proteins{per}"))),
        "carbs_g": r(_num(n.get(f"carbohydrates{per}"))),
        "fat_g": r(_num(n.get(f"fat{per}"))),
        "fiber_g": r(_num(n.get(f"fiber{per}"))),
        "b12_ug": micro("vitamin-b12", 1e6),
        "vit_d_ug": micro("vitamin-d", 1e6),
        "caffeine_mg": micro("caffeine", 1e3),
        "serving_qty": serving,
        "package_qty": _num(product.get("product_quantity")) or None,
        "food_group": "alcoholic" if alcoholic else "",
        "abv_pct": abv if alcoholic else None,
        "pescatarian": vegetarian,  # implied, as in FoodIn
        "ovolactovegetarian": vegetarian,
        "vegetarian": vegetarian,
        "vegan": vegan,
        "kosher": _has_tag(labels, "kosher"),
        "lactose_free": _has_tag(labels, "lactose-free", "no-lactose"),
        "peanut_free": _has_tag(labels, "peanut-free", "no-peanuts")
        and "en:peanuts" not in allergens,
        "tacc_free": _has_tag(labels, "gluten-free", "no-gluten", "sin-tacc")
        and "en:gluten" not in allergens,
    }
