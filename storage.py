"""JSON-backed persistence for vinted-alert.

Two flat JSON files replace the original project's SQLite DB:
  - price_history.json : prices observed per (brand, size, status), used to
    compute the price stats the scorer needs (median/p25/p75).
  - seen_items.json     : IDs of items already processed, so an item is only
    ever scored/notified once across runs.

Both files are written atomically (write to .tmp then os.replace) so a job
killed mid-write (e.g. GitHub Actions timeout) never leaves corrupt JSON.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

ABSOLUTE_PRICE_FLOOR = 3.0
IQR_K = 1.5
MIN_COUNT = 5

MAX_PRICES_PER_KEY = 500
MAX_SEEN_ITEMS = 5000


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _atomic_write_json(path: str, data: Any) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


# ─── extract_fields ──────────────────────────────────────────────────────


def extract_fields(item_raw: dict, search_name: str) -> dict:
    price = item_raw.get("price")
    if isinstance(price, dict):
        price_amount = _safe_float(price.get("amount"))
        currency = price.get("currency_code")
    else:
        price_amount = _safe_float(price)
        currency = None

    photo = item_raw.get("photo")
    if isinstance(photo, dict):
        photo_url = photo.get("url") or photo.get("full_size_url")
    else:
        photo_url = None

    user = item_raw.get("user")
    if not isinstance(user, dict):
        user = {}

    return {
        "item_id": _safe_int(item_raw.get("id")),
        "title": item_raw.get("title"),
        "brand": item_raw.get("brand_title"),
        "price": price_amount,
        "currency": currency,
        "size": item_raw.get("size_title"),
        "status": item_raw.get("status"),
        "url": item_raw.get("url"),
        "photo_url": photo_url,
        "favourite_count": _safe_int(item_raw.get("favourite_count")),
        "seller_login": user.get("login"),
        "search_name": search_name,
    }


# ─── price_history.json ──────────────────────────────────────────────────


def load_price_history(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("price_history.json illisible (%s), repart de zéro", exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_price_history(path: str, data: dict) -> None:
    _atomic_write_json(path, data)


def _price_key(brand: Optional[str], size: Optional[str], status: Optional[str]) -> str:
    return f"{brand}||{size or ''}||{status or ''}"


def record_price(
    data: dict,
    brand: Optional[str],
    size: Optional[str],
    status: Optional[str],
    price: Optional[float],
) -> None:
    if price is None or brand is None:
        return
    key = _price_key(brand, size, status)
    prices = data.setdefault(key, [])
    prices.append(float(price))
    if len(prices) > MAX_PRICES_PER_KEY:
        del prices[: len(prices) - MAX_PRICES_PER_KEY]


def _percentile(sorted_list: list[float], pct: float) -> Optional[float]:
    """Type 7 percentile (NumPy default), linear interpolation."""
    n = len(sorted_list)
    if n == 0:
        return None
    if n == 1:
        return sorted_list[0]
    k = (n - 1) * pct
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return sorted_list[f]
    return sorted_list[f] + (sorted_list[c] - sorted_list[f]) * (k - f)


def get_price_stats(
    data: dict,
    brand: Optional[str],
    size: Optional[str],
    status: Optional[str],
) -> dict:
    """Median, P25, P75 and counts, with two-pass outlier filtering.

      1. Hard floor: drop everything < ABSOLUTE_PRICE_FLOOR (3 €).
      2. IQR filter (Tukey, k=1.5) on the floor-filtered set.
    `count` reports the post-floor set, `count_filtered` the post-IQR set.
    Returns Nones for the three percentiles when either count falls below 5.
    """
    empty = {"median": None, "p25": None, "p75": None, "count": 0, "count_filtered": 0}
    if brand is None:
        return empty

    key = _price_key(brand, size, status)
    prices = sorted(p for p in data.get(key, []) if p >= ABSOLUTE_PRICE_FLOOR)
    count_raw = len(prices)

    if count_raw < MIN_COUNT:
        return {
            "median": None,
            "p25": None,
            "p75": None,
            "count": count_raw,
            "count_filtered": count_raw,
        }

    p25_raw = _percentile(prices, 0.25)
    p75_raw = _percentile(prices, 0.75)
    iqr = p75_raw - p25_raw
    lower = max(ABSOLUTE_PRICE_FLOOR, p25_raw - IQR_K * iqr)
    upper = p75_raw + IQR_K * iqr

    filtered = [p for p in prices if lower <= p <= upper]
    count_filtered = len(filtered)

    if count_filtered < MIN_COUNT:
        return {
            "median": None,
            "p25": None,
            "p75": None,
            "count": count_raw,
            "count_filtered": count_filtered,
        }

    return {
        "median": _percentile(filtered, 0.50),
        "p25": _percentile(filtered, 0.25),
        "p75": _percentile(filtered, 0.75),
        "count": count_raw,
        "count_filtered": count_filtered,
    }


# ─── seen_items.json ──────────────────────────────────────────────────────


def load_seen_items(path: str) -> list[int]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("seen_items.json illisible (%s), repart de zéro", exc)
        return []
    ids = data.get("ids") if isinstance(data, dict) else None
    return [i for i in ids if isinstance(i, int)] if isinstance(ids, list) else []


def save_seen_items(path: str, ids: list[int]) -> None:
    trimmed = ids[-MAX_SEEN_ITEMS:]
    _atomic_write_json(path, {"ids": trimmed})
