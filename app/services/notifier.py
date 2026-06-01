import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from datetime import datetime

from app.config import settings
from app.database import Listing

logger = logging.getLogger(__name__)


def format_price(value):
    if value is None:
        return "k.A."
    return f"{value:,.0f} €".replace(",", ".")


def format_sqm(value):
    if value is None:
        return "k.A."
    return f"{value:.0f} m²"


def format_rooms(value):
    if value is None:
        return "k.A."
    return f"{value:g} Zi."


SOURCE_LABELS = {
    "immoscout24": "ImmobilienScout24",
    "immowelt": "Immowelt",
    "immonet": "Immonet",
}


def build_listing_html(listing: Listing) -> str:
    detail_url = f"{settings.base_url}/listings/{listing.id}"
    source_label = SOURCE_LABELS.get(listing.source, listing.source)
    return f"""
    <tr>
        <td style="padding:10px; border-bottom:1px solid #eee;">
            <strong><a href="{detail_url}" style="color:#0d6efd;text-decoration:none;">{listing.title}</a></strong><br>
            <small style="color:#666;">{source_label} · {listing.district or "Frankfurt"}</small>
        </td>
        <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">
            {format_price(listing.price)}
        </td>
        <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">
            {format_sqm(listing.size_sqm)}
        </td>
        <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">
            {format_rooms(listing.rooms)}
        </td>
        <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">
            {format_price(listing.price_per_sqm)}/m²
        </td>
        <td style="padding:10px; border-bottom:1px solid #eee;">
            <a href="{listing.url}" style="color:#0d6efd;" target="_blank">Exposé →</a>
        </td>
    </tr>"""


def build_email_html(new_listings: List[Listing]) -> str:
    rows = "".join(build_listing_html(l) for l in new_listings)
    count = len(new_listings)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Neue Immobilien in Frankfurt</title>
</head>
<body style="font-family: Arial, sans-serif; background:#f8f9fa; margin:0; padding:20px;">
  <div style="max-width:800px; margin:0 auto; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="background:#0d6efd; color:#fff; padding:24px;">
      <h1 style="margin:0; font-size:22px;">🏠 {count} neue Immobilie{'n' if count != 1 else ''} in Frankfurt</h1>
      <p style="margin:8px 0 0; opacity:0.9; font-size:14px;">Gefunden am {now}</p>
    </div>
    <div style="padding:24px;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa;">
            <th style="padding:10px; text-align:left; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">Objekt</th>
            <th style="padding:10px; text-align:right; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">Preis</th>
            <th style="padding:10px; text-align:right; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">Größe</th>
            <th style="padding:10px; text-align:right; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">Zimmer</th>
            <th style="padding:10px; text-align:right; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">€/m²</th>
            <th style="padding:10px; text-align:left; font-size:12px; text-transform:uppercase; color:#666; border-bottom:2px solid #dee2e6;">Link</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
    <div style="background:#f8f9fa; padding:16px 24px; text-align:center; border-top:1px solid #dee2e6;">
      <a href="{settings.base_url}" style="color:#0d6efd; font-size:14px;">Zur Immobilien-Übersicht →</a>
    </div>
  </div>
</body>
</html>"""


def send_notification(new_listings: List[Listing]) -> bool:
    """Send email notification for new listings. Returns True on success."""
    if not new_listings:
        return True
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP credentials not configured, skipping email notification")
        return False

    try:
        subject = f"[Immo-Scanner] {len(new_listings)} neue Wohnungen in Frankfurt"
        html_body = build_email_html(new_listings)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_user
        msg["To"] = settings.notify_email

        # Plain text fallback
        text_lines = [f"Neue Immobilien in Frankfurt ({len(new_listings)} Treffer):\n"]
        for l in new_listings:
            text_lines.append(
                f"• {l.title}\n"
                f"  Preis: {format_price(l.price)} | Größe: {format_sqm(l.size_sqm)} | {format_rooms(l.rooms)}\n"
                f"  Exposé: {l.url}\n"
                f"  Details: {settings.base_url}/listings/{l.id}\n"
            )
        text_body = "\n".join(text_lines)

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())

        logger.info(f"Notification email sent to {settings.notify_email} ({len(new_listings)} listings)")
        return True
    except Exception as e:
        logger.error(f"Failed to send notification email: {e}", exc_info=True)
        return False
