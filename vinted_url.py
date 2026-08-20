"""Translate a vinted.fr search URL into Vinted catalog API parameters.

The whole point of this module: Vinted's own website already has the best
filter UI there is (brands, sizes, colors, materials, condition...), and
its URL encodes every filter as the exact ids the catalog API expects. So
instead of rebuilding that UI, you filter on vinted.fr, copy the URL, and
we translate it here.

Shared by `add_alert.py` (preview at creation time) and `main.py` (runtime),
so what you validate when adding an alert is byte-for-byte what runs later.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

# Params forwarded to /api/v2/catalog/items. Anything else in the URL
# (tracking, `page`, UI-only state...) is dropped. All of these were
# verified to actually filter server-side against the real API.
ALLOWED_PARAMS = {
    "search_text",
    "brand_ids",
    "size_ids",
    "color_ids",
    "status_ids",
    "material_ids",
    "catalog_ids",
    "price_from",
    "price_to",
    "currency",
    "order",
}

# vinted.fr uses a few different names for the same filter depending on
# where the URL comes from (catalog page vs saved search vs app deep link).
PARAM_ALIASES = {
    "catalog": "catalog_ids",
    "brand": "brand_ids",
    "brand_id": "brand_ids",
    "size": "size_ids",
    "color": "color_ids",
    "colour_ids": "color_ids",
    "status": "status_ids",
    "material": "material_ids",
}

# A category can also be a path segment: /catalog/2656-mocassins-et-...
_CATALOG_PATH_RE = re.compile(r"/catalog/(\d+)(?:-|$)")


class InvalidVintedURL(ValueError):
    """Raised when the URL isn't a usable vinted.fr search."""


def parse_vinted_url(url: str) -> dict[str, str]:
    """Return the API params encoded in a vinted.fr search URL.

    Repeated params (`brand_ids[]=1&brand_ids[]=2`) are joined into the
    comma-separated form the API takes: `{"brand_ids": "1,2"}`.

    Raises InvalidVintedURL if the host isn't vinted.fr, or if the URL
    carries no usable filter at all (an unfiltered /catalog would alert on
    the entire site).
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidVintedURL(f"URL invalide : {url!r}")
    host = parsed.netloc.lower().split(":")[0]
    if not (host == "vinted.fr" or host.endswith(".vinted.fr")):
        raise InvalidVintedURL(
            f"Ce n'est pas une URL vinted.fr (domaine trouvé : {host}). "
            "Fais ta recherche sur vinted.fr et copie l'URL de la barre "
            "d'adresse."
        )

    params: dict[str, str] = {}
    for raw_key, values in parse_qs(parsed.query, keep_blank_values=False).items():
        key = raw_key[:-2] if raw_key.endswith("[]") else raw_key
        key = PARAM_ALIASES.get(key, key)
        if key not in ALLOWED_PARAMS:
            continue
        cleaned = [v.strip() for v in values if v and v.strip()]
        if cleaned:
            params[key] = ",".join(cleaned)

    # Category as a path segment, e.g. /catalog/2656-mocassins-et-chaussures
    if "catalog_ids" not in params:
        match = _CATALOG_PATH_RE.search(unquote(parsed.path))
        if match:
            params["catalog_ids"] = match.group(1)

    if not params:
        raise InvalidVintedURL(
            "Aucun filtre trouvé dans cette URL — l'alerte porterait sur "
            "tout Vinted. Ajoute au moins un critère (texte, marque, "
            "catégorie, prix...) sur vinted.fr, puis recopie l'URL."
        )
    return params


def describe_params(params: dict[str, str]) -> str:
    """One-line human summary of parsed params, for CLI/log output."""
    labels = {
        "search_text": "texte",
        "brand_ids": "marque(s)",
        "size_ids": "taille(s)",
        "color_ids": "couleur(s)",
        "status_ids": "état(s)",
        "material_ids": "matière(s)",
        "catalog_ids": "catégorie(s)",
        "price_from": "prix min",
        "price_to": "prix max",
        "currency": "devise",
        "order": "tri",
    }
    return " · ".join(
        f"{labels.get(k, k)}={v}" for k, v in sorted(params.items())
    )
