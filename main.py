"""Entry point for vinted-alert.

Run once (python main.py), meant to be triggered periodically by an
external scheduler (cron-job.org hitting the GitHub Actions
`workflow_dispatch` API every 15 min — see README.md).

Each configured search is a vinted.fr URL: every filter it carries is
applied server-side by Vinted, so every item returned is a match. For each
search we fetch the matches, record their price into the history (kept for
a future quality score, not used to filter), and collect the ones never
seen before into a single digest (email + ntfy). One search failing
(network, Vinted API error) never blocks the others.
"""

from __future__ import annotations

import logging
import os

import yaml
from dotenv import load_dotenv

import notifier
import storage
from client import VintedAPIError, VintedClient
from vinted_url import InvalidVintedURL, describe_params, parse_vinted_url

log = logging.getLogger("vinted_alert")

CONFIG_PATH = "config.yaml"
PRICE_HISTORY_PATH = "price_history.json"
SEEN_ITEMS_PATH = "seen_items.json"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
        try:
            params = parse_vinted_url(search["url"])
        except (KeyError, InvalidVintedURL) as exc:
            log.error("Recherche '%s' ignorée — URL inutilisable : %s", name, exc)
            continue

        log.info("▶ Recherche %s (%s)", name, describe_params(params))

        try:
            items = client.search(params)
        except VintedAPIError as exc:
            log.error("API KO sur '%s' : %s", name, exc)
            continue
        except Exception:
            log.exception("Erreur inattendue sur recherche '%s'", name)
            continue

        new_count = 0
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
            # Tous les filtres sont appliqués côté serveur par Vinted :
            # chaque item reçu est un match, il suffit qu'il soit nouveau.
            digest_items.append(dict(fields))

        log.info("✓ %s : reçus=%d nouveaux=%d", name, len(items), new_count)

    storage.save_price_history(PRICE_HISTORY_PATH, price_data)
    storage.save_seen_items(SEEN_ITEMS_PATH, seen_ids_list)

    if digest_items:
        email_ok = ntfy_ok = False
        try:
            notifier.send_email(notifier.build_digest_html(digest_items), len(digest_items))
            email_ok = True
        except Exception:
            log.exception("Échec envoi email")
        try:
            notifier.send_ntfy(digest_items)
            ntfy_ok = True
        except Exception:
            log.exception("Échec envoi ntfy")

        if not (email_ok or ntfy_ok):
            return 1
        log.info(
            "🔔 Digest : %d article(s) — email=%s ntfy=%s",
            len(digest_items),
            "OK" if email_ok else "KO",
            "OK" if ntfy_ok else "KO",
        )
    else:
        log.info("Aucun nouvel article qualifié ce cycle — pas de notif")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
