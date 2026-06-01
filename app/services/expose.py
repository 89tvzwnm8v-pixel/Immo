import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.database import Listing
from app.scrapers import SCRAPERS

logger = logging.getLogger(__name__)


def fetch_and_store_expose(listing_id: int, db: Session) -> bool:
    """Fetch full exposé details for a listing and update the database record."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        logger.warning(f"Listing {listing_id} not found")
        return False

    scraper_class = SCRAPERS.get(listing.source)
    if not scraper_class:
        logger.warning(f"No scraper for source {listing.source}")
        return False

    scraper = scraper_class()
    try:
        expose_data = scraper.fetch_expose(listing.url)
        if not expose_data:
            logger.warning(f"No expose data returned for listing {listing_id}")
            return False

        # Update listing fields from expose data
        if expose_data.get("description"):
            listing.description = expose_data["description"]
        if expose_data.get("features"):
            existing = listing.features or []
            merged = list(dict.fromkeys(existing + expose_data["features"]))
            listing.features = merged
        if expose_data.get("images"):
            existing_imgs = listing.images or []
            merged_imgs = list(dict.fromkeys(existing_imgs + expose_data["images"]))
            listing.images = merged_imgs
        if expose_data.get("contact_name"):
            listing.contact_name = expose_data["contact_name"].strip()
        if expose_data.get("contact_phone"):
            listing.contact_phone = expose_data["contact_phone"].strip()
        if expose_data.get("contact_email"):
            listing.contact_email = expose_data["contact_email"].strip()
        if expose_data.get("year_built"):
            listing.year_built = expose_data["year_built"]
        if expose_data.get("floor"):
            listing.floor = expose_data["floor"]

        listing.expose_fetched_at = datetime.utcnow()
        db.commit()
        logger.info(f"Exposé fetched and stored for listing {listing_id} ({listing.source}:{listing.external_id})")
        return True
    except Exception as e:
        logger.error(f"Error fetching expose for listing {listing_id}: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        scraper.client.close()
