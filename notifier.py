"""Email notifier — one digest per run, sent via Gmail SMTP.

Reads EMAIL_EXPEDITEUR / EMAIL_MOT_DE_PASSE / EMAIL_DESTINATAIRE from the
environment. Same SMTP pattern as ~/doctolib-alert/doctolib_alert.py.
"""

from __future__ import annotations

import html
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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
    score = int(item.get("score") or 0)
    url = item.get("url") or "#"
    photo_url = item.get("photo_url")
    reasons = item.get("reasons") or []
    reasons_html = "".join(f"<li>{html.escape(r)}</li>" for r in reasons)
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
        <div style="font-size:16px;color:#2b6cb0;font-weight:bold;">{price_str} · score {score}</div>
        <ul style="margin:6px 0 10px 16px;padding:0;color:#4a5568;font-size:13px;">{reasons_html}</ul>
        <a href="{html.escape(url)}" style="display:inline-block;background:#107ACA;color:white;
           padding:10px 20px;text-decoration:none;border-radius:6px;font-size:14px;font-weight:bold;">
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
