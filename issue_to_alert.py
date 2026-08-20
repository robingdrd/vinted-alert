"""Turn a GitHub issue containing a vinted.fr URL into an alert.

Run by .github/workflows/add_alert.yml when an issue is opened. Reads the
issue from the environment (never from argv, so nothing from the issue text
can reach a shell), writes the reply to `comment.md`, and reports through
GITHUB_OUTPUT whether config.yaml was modified.

Always exits 0 for *handled* problems (no URL, bad URL, duplicate name):
those are reported to the user as an issue comment, not as a red build.
"""

from __future__ import annotations

import os
import re
import sys

from add_alert import append_alert, existing_names, unique_name
from client import VintedAPIError, VintedClient
from storage import extract_fields
from vinted_url import InvalidVintedURL, describe_params, parse_vinted_url

PREVIEW_LIMIT = 10
# Les crochets doivent rester autorisés : les URLs Vinted portent leurs
# filtres sous la forme `brand_ids[]=20413`. On ne coupe donc que sur les
# espaces, les parenthèses (syntaxe des liens Markdown) et les guillemets.
URL_RE = re.compile(r"https?://[^\s<>()\"']+vinted\.fr[^\s<>()\"']*", re.I)


def _write_output(added: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"added={'true' if added else 'false'}\n")


def _finish(comment: str, added: bool) -> int:
    with open("comment.md", "w", encoding="utf-8") as f:
        f.write(comment)
    _write_output(added)
    print(comment)
    return 0


def _price(fields: dict) -> str:
    price = fields.get("price")
    if price is None:
        return "?"
    currency = fields.get("currency")
    return f"{float(price):g}" + ("€" if currency in (None, "", "EUR") else f" {currency}")


def main() -> int:
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "") or ""

    match = URL_RE.search(body) or URL_RE.search(title)
    if not match:
        return _finish(
            "❌ **Aucune URL Vinted trouvée dans cette issue.**\n\n"
            "Colle l'URL d'une recherche `vinted.fr` (filtres compris) dans "
            "le corps de l'issue, puis rouvre-en une nouvelle.",
            added=False,
        )

    url = match.group(0)
    try:
        params = parse_vinted_url(url)
    except InvalidVintedURL as exc:
        return _finish(f"❌ **URL inutilisable.**\n\n{exc}\n\n`{url}`", added=False)

    # Nom : titre de l'issue (sans un éventuel préfixe "Alerte :"), sinon
    # le texte recherché.
    raw_name = re.sub(r"^\s*alerte\s*:?\s*", "", title, flags=re.I).strip()
    name = unique_name(raw_name or params.get("search_text", "") or "alerte", existing_names())

    try:
        items = VintedClient().search(params)
    except VintedAPIError as exc:
        return _finish(
            f"⚠️ **Vinted est injoignable, alerte non ajoutée.**\n\n{exc}\n\n"
            "Rouvre une issue pour réessayer.",
            added=False,
        )

    append_alert(name, url)

    lines = [
        f"✅ **Alerte `{name}` ajoutée.**",
        "",
        f"Filtres : {describe_params(params)}",
        f"[Voir cette recherche sur Vinted]({url})",
        "",
    ]
    if not items:
        lines += [
            "Aucun article ne correspond pour l'instant — l'alerte se "
            "déclenchera sur les prochaines annonces. Si tu t'attendais à des "
            "résultats, vérifie tes filtres.",
        ]
    else:
        lines += [f"**{len(items)} article(s) correspondent actuellement :**", ""]
        for item_raw in items[:PREVIEW_LIMIT]:
            f = extract_fields(item_raw, name)
            lines.append(
                f"- [{f.get('title')}]({f.get('url')}) — **{_price(f)}** · taille {f.get('size') or '?'}"
            )
        if len(items) > PREVIEW_LIMIT:
            lines.append(f"- … et {len(items) - PREVIEW_LIMIT} autre(s)")
        lines += [
            "",
            f"⚠️ Au prochain cycle, ces {len(items)} article(s) seront vus pour "
            "la première fois : tu recevras une notification les listant "
            "(sauf ceux déjà notifiés par une autre alerte).",
        ]

    return _finish("\n".join(lines), added=True)


if __name__ == "__main__":
    sys.exit(main())
