"""Entry point for vinted-alert.

Run once (python main.py), meant to be triggered periodically by an
external scheduler (cron-job.org hitting the GitHub Actions
`workflow_dispatch` API every 15 min — see README.md).

For every configured search: fetch items, record their price into the
history (kept for a future quality score, not used to filter yet), and
collect the new-and-under-price_max ones into a single digest email. One
search failing (network, Vinted API error) never blocks the others.
"""

from __future__ import annotations

import logging
import os

import yaml
from dotenv import load_dotenv

import notifier
import storage
from client import VintedAPIError, VintedClient

log = logging.getLogger("vinted_alert")

CONFIG_PATH = "config.yaml"
PRICE_HISTORY_PATH = "price_history.json"
SEEN_ITEMS_PATH = "seen_items.json"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _matches_search(fields: dict, search: dict, client: VintedClient) -> bool:
    """Price/brand/size/color filter for one already-deduped item.

    Checks are ordered cheapest-first: price/brand/size only look at data
    already in `fields` (no I/O). Color is checked last and only if
    configured, since it costs one extra HTTP request per candidate
    (client.get_item_attributes scrapes the item detail page).
    """
    price_max = search.get("price_max")
    if price_max is None or fields["price"] is None or fields["price"] > float(price_max):
        return False

    wanted_brand = search.get("brand")
    if wanted_brand and (fields["brand"] or "").strip().lower() != wanted_brand.strip().lower():
        return False

    wanted_sizes = search.get("sizes")
    if wanted_sizes and (fields["size"] or "").strip() not in [str(s).strip() for s in wanted_sizes]:
        return False

    wanted_colors = search.get("colors")
    if wanted_colors:
        attrs = client.get_item_attributes(fields["item_id"])
        color_value = (attrs or {}).get("color", "")
        if not any(c.lower() in color_value.lower() for c in wanted_colors):
            return False

    return True


def main() -> int:
    load_dotenv(override=True)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(CONFIG_PATH)
    searches = config.get("searches") or []

    price_data = storage.load_price_history(PRICE_HISTORY_PATH)
    seen_ids_list = storage.load_seen_items(SEEN_ITEMS_PATH)
    seen_ids = set(seen_ids_list)

    client = VintedClient()
    digest_items: list[dict] = []

    for search in searches:
        name = search.get("name", "?")
        price_max = search.get("price_max")
        if price_max is None:
            log.warning("Recherche '%s' sans price_max — aucun article ne pourra qualifier", name)
        log.info("▶ Recherche %s...", name)

        kwargs = {
            "query": search["query"],
            "price_max": search.get("price_max"),
            "catalog_ids": search.get("catalog_ids"),
            "brand_ids": search.get("brand_ids"),
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        try:
            items = client.search(**kwargs)
        except VintedAPIError as exc:
            log.error("API KO sur '%s' : %s", name, exc)
            continue
        except Exception:
            log.exception("Erreur inattendue sur recherche '%s'", name)
            continue

        new_count = qualifying_count = 0
        for item_raw in items:
            try:
                fields = storage.extract_fields(item_raw, name)
            except Exception:
                log.exception("Erreur d'extraction sur un item de '%s'", name)
                continue

            item_id = fields["item_id"]
            if item_id is None:
                continue

            if fields["price"] is not None and fields["brand"] is not None:
                storage.record_price(
                    price_data, fields["brand"], fields["size"], fields["status"], fields["price"]
                )

            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            seen_ids_list.append(item_id)
            new_count += 1

            if _matches_search(fields, search, client):
                qualifying_count += 1
                digest_items.append(dict(fields))

        log.info(
            "✓ %s : reçus=%d nouveaux=%d qualifiés=%d",
            name,
            len(items),
            new_count,
            qualifying_count,
        )

    storage.save_price_history(PRICE_HISTORY_PATH, price_data)
    storage.save_seen_items(SEEN_ITEMS_PATH, seen_ids_list)

    if digest_items:
        html_body = notifier.build_digest_html(digest_items)
        try:
            notifier.send_email(html_body, len(digest_items))
        except Exception:
            log.exception("Échec envoi email")
            return 1
        log.info("🔔 Digest envoyé : %d article(s)", len(digest_items))
    else:
        log.info("Aucun nouvel article qualifié ce cycle — pas d'email")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
