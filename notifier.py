"""Email + ntfy notifier — one digest per run.

Email: reads EMAIL_EXPEDITEUR / EMAIL_MOT_DE_PASSE / EMAIL_DESTINATAIRE from
the environment, sent via Gmail SMTP.
ntfy: posts to the public ntfy.sh broker, topic read from NTFY_TOPIC. The
broker has no auth — knowing the topic name is enough to subscribe *or*
publish to it, so the topic must stay out of this (public) repo and live in
the environment / GitHub Secrets like any other credential.
Same dual-channel pattern as ~/doctolib-alert/doctolib_alert.py.
"""

from __future__ import annotations

import html
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)


def _format_price(price, currency) -> str:
    if price is None:
        return "?"
    price_str = f"{float(price):g}"
    if currency in (None, "", "EUR"):
        return f"{price_str}€"
    return f"{price_str} {currency}"


def _item_card_html(item: dict) -> str:
    title = html.escape(item.get("title") or "(sans titre)")
    brand = html.escape(item.get("brand") or "?")
    price_str = _format_price(item.get("price"), item.get("currency"))
    url = item.get("url") or "#"
    photo_url = item.get("photo_url")
    seller = item.get("seller_login")
    seller_html = f" · vendeur {html.escape(seller)}" if seller else ""

    img_html = (
        f'<img src="{html.escape(photo_url)}" alt="" '
        f'style="width:100%;max-width:440px;border-radius:8px;display:block;margin-bottom:8px;">'
        if photo_url
        else ""
    )

    return f"""
    <tr><td style="padding:20px 0;border-bottom:1px solid #e2e8f0;">
        {img_html}
        <div style="font-size:17px;font-weight:bold;color:#2d3748;">{title}</div>
        <div style="color:#718096;font-size:14px;margin:2px 0 6px;">{brand}{seller_html}</div>
        <div style="font-size:16px;color:#2b6cb0;font-weight:bold;">{price_str}</div>
        <a href="{html.escape(url)}" style="display:inline-block;background:#107ACA;color:white;
           padding:10px 20px;text-decoration:none;border-radius:6px;font-size:14px;font-weight:bold;margin-top:8px;">
           Voir sur Vinted
        </a>
    </td></tr>"""


def build_digest_html(items: list[dict]) -> str:
    cards = "".join(_item_card_html(it) for it in items)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:480px;margin:0 auto;padding:16px;">
<h2 style="color:#2d3748;margin-bottom:4px;">Vinted Alert</h2>
<p style="color:#718096;margin-top:0;">{len(items)} nouvelle(s) affaire(s) trouvée(s)</p>
<table style="width:100%;border-collapse:collapse;">{cards}</table>
<p style="color:#a0aec0;font-size:12px;margin-top:24px;">Alerte automatique vinted-alert</p>
</body></html>"""


def send_email(html_body: str, count: int) -> None:
    sender = os.environ.get("EMAIL_EXPEDITEUR", "")
    password = os.environ.get("EMAIL_MOT_DE_PASSE", "")
    recipient = os.environ.get("EMAIL_DESTINATAIRE", "")
    missing = [
        name
        for name, value in (
            ("EMAIL_EXPEDITEUR", sender),
            ("EMAIL_MOT_DE_PASSE", password),
            ("EMAIL_DESTINATAIRE", recipient),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Variable(s) d'environnement manquante(s) : {', '.join(missing)}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Vinted Alert — {count} nouvelle(s) affaire(s)"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipient, msg.as_string())
    logger.info("Email envoyé (%d article(s))", count)


# Au-delà de 4096 octets, ntfy.sh ne délivre plus le corps comme texte : il
# le convertit en pièce jointe (attachment.txt), illisible d'un coup d'œil
# sur le téléphone — et sans erreur HTTP pour le signaler. On garde donc la
# notif courte : c'est le canal « préviens-moi », l'email porte le détail.
NTFY_MAX_ITEMS = 5
NTFY_MAX_BYTES = 3500


def _ntfy_body(items: list[dict]) -> str:
    lines = []
    for it in items[:NTFY_MAX_ITEMS]:
        title = it.get("title") or "(sans titre)"
        price_str = _format_price(it.get("price"), it.get("currency"))
        lines.append(f"{title} — {price_str}\n{it.get('url') or ''}")
    remaining = len(items) - NTFY_MAX_ITEMS
    if remaining > 0:
        lines.append(f"… et {remaining} autre(s) — voir l'email")

    body = "\n\n".join(lines)
    # Filet de sécurité : quelques titres à rallonge peuvent suffire à
    # dépasser la limite même avec 5 articles.
    encoded = body.encode("utf-8")
    if len(encoded) > NTFY_MAX_BYTES:
        body = encoded[:NTFY_MAX_BYTES].decode("utf-8", "ignore") + "\n\n[…] voir l'email"
    return body


def send_ntfy(items: list[dict]) -> None:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise ValueError(
            "NTFY_TOPIC absent de l'environnement — impossible d'envoyer la "
            "notification push (voir .env.example)."
        )
    count = len(items)
    data = _ntfy_body(items)
    click_url = items[0].get("url") if len(items) == 1 else None
    headers = {
        "Title": f"Vinted Alert — {count} nouvelle(s) affaire(s)".encode("utf-8"),
        "Priority": "urgent",
        "Tags": "shopping_bags",
    }
    if click_url:
        headers["Click"] = click_url.encode("utf-8")
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=data.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Notification ntfy envoyée (%d article(s))", count)
