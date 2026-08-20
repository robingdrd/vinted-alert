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


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug or "alerte"


def unique_name(base: str, existing: set[str]) -> str:
    """`base`, or `base_2`, `base_3`... if already taken."""
    base = slugify(base)
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def existing_names(config_path: str = CONFIG_PATH) -> set[str]:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return {s.get("name") for s in (config.get("searches") or []) if s.get("name")}


def append_alert(name: str, url: str, config_path: str = CONFIG_PATH) -> None:
    """Append one alert to config.yaml as raw text.

    Appending text rather than re-dumping the parsed YAML keeps the file's
    explanatory comments (and their formatting) intact.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    entry = f'  - name: {name}\n    url: "{url.strip()}"\n'
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(raw.rstrip("\n") + "\n" + entry)


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

    existing = existing_names()

    name = args.name or unique_name(params.get("search_text", "") or "alerte", existing)
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

    append_alert(name, args.url)
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
