"""Add a new alert to config.yaml from a vinted.fr search URL.

    python add_alert.py "<url vinted>" [--name mon_alerte] [--push]

Filter on vinted.fr with its own UI, copy the URL, paste it here. The
script previews what currently matches before writing anything, so you can
check the filter is right — then appends the alert to config.yaml.

Appends as text rather than re-dumping the YAML, to keep the file's
comments intact.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

import yaml

from client import VintedAPIError, VintedClient
from storage import extract_fields
from vinted_url import InvalidVintedURL, describe_params, parse_vinted_url

CONFIG_PATH = "config.yaml"
PREVIEW_LIMIT = 10


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug or "alerte"


def _suggest_name(params: dict[str, str], existing: set[str]) -> str:
    base = _slugify(params.get("search_text", "") or "alerte")
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def _existing_names(config: dict) -> set[str]:
    return {s.get("name") for s in (config.get("searches") or []) if s.get("name")}


def _format_price(fields: dict) -> str:
    price = fields.get("price")
    if price is None:
        return "?"
    currency = fields.get("currency")
    suffix = "€" if currency in (None, "", "EUR") else f" {currency}"
    return f"{float(price):g}{suffix}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="add_alert")
    parser.add_argument("url", help="URL de la recherche vinted.fr (entre guillemets)")
    parser.add_argument("--name", help="Nom de l'alerte (sinon déduit du texte recherché)")
    parser.add_argument("--push", action="store_true", help="git commit + push après ajout")
    parser.add_argument("--yes", "-y", action="store_true", help="Ne pas demander confirmation")
    args = parser.parse_args(argv)

    try:
        params = parse_vinted_url(args.url)
    except InvalidVintedURL as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_config = f.read()
    config = yaml.safe_load(raw_config) or {}
    existing = _existing_names(config)

    name = args.name or _suggest_name(params, existing)
    if name in existing:
        print(
            f"❌ Une alerte nommée '{name}' existe déjà. Choisis un autre nom "
            f"avec --name.",
            file=sys.stderr,
        )
        return 2

    print(f"Filtres reconnus : {describe_params(params)}")
    print("Recherche en cours sur Vinted...\n")

    try:
        items = VintedClient().search(params)
    except VintedAPIError as exc:
        print(f"❌ Vinted injoignable : {exc}", file=sys.stderr)
        return 1

    if not items:
        print(
            "⚠️  Aucun article ne correspond actuellement.\n"
            "   L'alerte reste valable (elle se déclenchera sur les futures\n"
            "   annonces), mais vérifie que les filtres sont les bons."
        )
    else:
        print(f"{len(items)} article(s) correspondent actuellement :")
        for item_raw in items[:PREVIEW_LIMIT]:
            f = extract_fields(item_raw, name)
            size = f.get("size") or "?"
            print(f"  • {f.get('title')} — {_format_price(f)} · taille {size}")
            print(f"    {f.get('url')}")
        if len(items) > PREVIEW_LIMIT:
            print(f"  … et {len(items) - PREVIEW_LIMIT} autre(s)")
        print(
            f"\n⚠️  À la première exécution, ces {len(items)} article(s) seront "
            "considérés\n   comme nouveaux : tu recevras une notif les listant."
        )

    print(f"\nAlerte à ajouter : name={name}")
    if not args.yes:
        answer = input("Confirmer l'ajout ? [o/N] ").strip().lower()
        if answer not in ("o", "oui", "y", "yes"):
            print("Annulé, config.yaml inchangé.")
            return 0

    entry = f'  - name: {name}\n    url: "{args.url.strip()}"\n'
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(raw_config.rstrip("\n") + "\n" + entry)
    print(f"✅ Alerte '{name}' ajoutée à {CONFIG_PATH}")

    if args.push:
        subprocess.run(["git", "add", CONFIG_PATH], check=True)
        subprocess.run(["git", "commit", "-m", f"Ajoute l'alerte {name}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("✅ Poussé sur GitHub — l'alerte sera active au prochain cycle.")
    else:
        print("ℹ️  Pense à `git add config.yaml && git commit && git push` "
              "pour l'activer sur GitHub Actions (ou relance avec --push).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
