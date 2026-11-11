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


def product_to_draft(code: str, product: dict[str, Any]) -> dict[str, Any]:
    """Food fields (per 100 g/ml) prefilled from an Open Food Facts product.

    Diet tags are only set when the product says so (labels or ingredient
    analysis) and its allergens don't contradict it; the user reviews the
    result before saving it."""
    n = product.get("nutriments") or {}
    kcal = _num(n.get("energy-kcal_100g"))
    if kcal is None and (kj := _num(n.get("energy_100g"))) is not None:
        kcal = kj / 4.184  # energy_100g is in kJ

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

    return {
        "ean": code,
        "name": (product.get("product_name") or product.get("generic_name") or "").strip(),
        "brand": (product.get("brands") or "").split(",")[0].strip(),
        "basis_qty": 100,
        "unit": unit,
        "kcal": None if kcal is None else r(kcal),  # missing = unknown, not 0
        "protein_g": r(_num(n.get("proteins_100g"))),
        "carbs_g": r(_num(n.get("carbohydrates_100g"))),
        "fat_g": r(_num(n.get("fat_100g"))),
        "fiber_g": r(_num(n.get("fiber_100g"))),
        "serving_qty": _num(product.get("serving_quantity")) or None,
        "package_qty": _num(product.get("product_quantity")) or None,
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
