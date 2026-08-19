"""Scoring logic for Vinted items.

Pure functions: no I/O, no DB, no network. Each component is independently
testable. The aggregated `score_item` returns a 0-100 score plus a list of
reasons sorted by descending contribution (positives first, penalties last).
"""

from __future__ import annotations

import re
from typing import Optional

MAX_PRICE_POINTS = 60
MAX_TEXTUAL_POINTS = 20
MAX_ROUND_PRICE_POINTS = 5
MIN_PRICE_STATS_COUNT = 5

# weights per keyword — sums then cap at MAX_TEXTUAL_POINTS
# Multi-word keys must be sorted longest-first within their semantic family
# so that re.search hits the more specific phrase first (e.g. "trop petit
# pour moi" is +6, "trop petit" alone is +5; both can match the same title
# and the points stack, which is the desired behaviour).
TEXTUAL_SIGNALS: dict[str, int] = {
    # Génériques "vendeur pressé"
    "vide dressing": 5,
    "doit partir": 5,
    "déménagement": 5,
    "déménage": 5,
    "jamais porté": 5,
    "jamais mis": 5,
    "jamais servi": 5,
    "jamais porté étiquette": 7,
    "cadeau": 4,
    "trop petit pour moi": 6,
    "trop petit": 5,
    "trop grand": 4,
    "ne me va pas": 5,
    "héritage": 5,
    "grenier": 5,
    "urgent": 4,
    "rapide": 3,
    # Premium FR (vendeuses urbaines impulsives)
    "porté qu'une seule fois": 6,
    "porté qu'une fois": 6,
    "porté 2 fois": 5,
    "étiquette": 3,
    "neuf": 3,
    "rangement": 4,
    "tri d'armoire": 5,
    "tri armoire": 5,
    "tri": 4,
    "petit prix": 4,
    "à saisir": 4,
    "achat impulsif": 6,
    "erreur taille": 5,
    "coup de coeur raté": 5,
}


def _score_price(price, stats: dict) -> tuple[float, Optional[str]]:
    count = stats.get("count", 0) or 0
    if count < MIN_PRICE_STATS_COUNT:
        return 0.0, f"Données prix insuffisantes ({count} obs)"
    median = stats.get("median")
    if median is None or price is None or median <= 0:
        return 0.0, None
    try:
        price = float(price)
        median = float(median)
    except (TypeError, ValueError):
        return 0.0, None
    discount = (median - price) / median
    if discount <= 0:
        return 0.0, None
    points = max(0.0, min(float(MAX_PRICE_POINTS), discount * 120.0))
    pct = int(round(discount * 100))
    if discount >= 0.40:
        label = "énorme"
    elif discount >= 0.25:
        label = "bon"
    elif discount >= 0.10:
        label = "correct"
    else:
        label = "léger"
    return points, f"Prix -{pct}% vs médian ({label})"


def _score_text(title: Optional[str]) -> tuple[float, Optional[str]]:
    if not title:
        return 0.0, None
    # Normalize curly apostrophes (U+2019) common in Vinted titles so the
    # `qu'une` family of patterns matches consistently.
    title_norm = title.replace("’", "'")
    matched: list[str] = []
    total = 0
    for keyword, weight in TEXTUAL_SIGNALS.items():
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, title_norm, re.IGNORECASE):
            matched.append(keyword)
            total += weight
    if not matched:
        return 0.0, None
    capped = float(min(MAX_TEXTUAL_POINTS, total))
    return capped, f"Mot-clés titre : {' + '.join(matched)}"


def _score_round_price(price) -> tuple[float, Optional[str]]:
    if price is None:
        return 0.0, None
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return 0.0, None
    if 0 < price_f < 30 and price_f == int(price_f) and int(price_f) % 5 == 0:
        return float(MAX_ROUND_PRICE_POINTS), "Prix rond bas (vente rapide)"
    return 0.0, None


def _penalty_visibility(item_fields: dict) -> tuple[float, Optional[str]]:
    fav = item_fields.get("favourite_count")
    if fav is None:
        return 0.0, None
    if fav >= 20:
        return -15.0, f"Déjà très consulté ({fav} favoris) — arbitrage perdu"
    if fav >= 10:
        return -8.0, f"Déjà consulté ({fav} favoris)"
    return 0.0, None


def score_item(item_fields: dict, price_stats: dict) -> tuple[float, list[str]]:
    """Compute the 0-100 score with sorted reasons.

    Reasons are sorted by descending point contribution: top boosters first,
    informational zeros next, penalties last.
    """
    components: list[tuple[float, Optional[str]]] = [
        _score_price(item_fields.get("price"), price_stats),
        _score_text(item_fields.get("title")),
        _score_round_price(item_fields.get("price")),
        _penalty_visibility(item_fields),
    ]

    total = sum(pts for pts, _ in components)
    total = max(0.0, min(100.0, total))

    ordered = sorted(components, key=lambda c: c[0], reverse=True)
    reasons = [reason for _, reason in ordered if reason]

    return float(round(total)), reasons
