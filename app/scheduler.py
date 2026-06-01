import logging
from datetime import datetime
from typing import List

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, Listing, ScanRun, SearchProfile
from app.models.listing import RawListing
from app.scrapers import SCRAPERS
from app.services.notifier import send_notification

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def upsert_listing(db: Session, raw: RawListing) -> tuple[Listing, bool]:
    """Insert or update a listing. Returns (listing, is_new)."""
    existing = db.query(Listing).filter(
        Listing.external_id == raw.external_id,
        Listing.source == raw.source,
    ).first()

    if existing:
        existing.last_seen_at = datetime.utcnow()
        if raw.price and existing.price != raw.price:
            existing.price = raw.price
        if raw.price_per_sqm:
            existing.price_per_sqm = raw.price_per_sqm
        db.commit()
        return existing, False

    listing = Listing(
        external_id=raw.external_id,
        source=raw.source,
        url=raw.url,
        title=raw.title,
        price=raw.price,
        price_per_sqm=raw.price_per_sqm,
        size_sqm=raw.size_sqm,
        rooms=raw.rooms,
        district=raw.district,
        address=raw.address,
        floor=raw.floor,
        year_built=raw.year_built,
        description=raw.description,
        features=raw.features or [],
        images=raw.images or [],
        contact_name=raw.contact_name,
        contact_email=raw.contact_email,
        contact_phone=raw.contact_phone,
        status="new",
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        raw_data=raw.raw_data or {},
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing, True


def run_scan_for_source(source: str) -> dict:
    """Run a scan for a single source. Returns result dict."""
    db = SessionLocal()
    scan_run = ScanRun(source=source, started_at=datetime.utcnow())
    db.add(scan_run)
    db.commit()

    result = {
        "source": source,
        "listings_found": 0,
        "listings_new": 0,
        "error": None,
        "duration_seconds": 0.0,
    }
    new_listings: List[Listing] = []

    try:
        scraper_class = SCRAPERS.get(source)
        if not scraper_class:
            raise ValueError(f"Unknown scraper: {source}")

        scraper = scraper_class()
        profiles = db.query(SearchProfile).filter(
            SearchProfile.source == source,
            SearchProfile.active == True,
        ).all()

        if not profiles:
            logger.info(f"No active profiles for {source}, using defaults")
            # Use a dummy profile with default settings
            class DefaultProfile:
                max_price = settings.max_price
                min_size = settings.min_size
                min_rooms = settings.min_rooms
                districts = settings.districts_list
            profiles = [DefaultProfile()]

        seen_ids = set()
        for profile in profiles:
            try:
                raw_listings = scraper.fetch_listings(profile)
                result["listings_found"] += len(raw_listings)
                logger.info(f"[{source}] Fetched {len(raw_listings)} listings from profile")

                for raw in raw_listings:
                    if raw.external_id in seen_ids:
                        continue
                    seen_ids.add(raw.external_id)
                    listing, is_new = upsert_listing(db, raw)
                    if is_new:
                        result["listings_new"] += 1
                        new_listings.append(listing)
            except Exception as e:
                logger.error(f"Error scanning profile {getattr(profile, 'name', 'default')} for {source}: {e}")

        scraper.client.close()

    except Exception as e:
        logger.error(f"Scan error for {source}: {e}", exc_info=True)
        result["error"] = str(e)
    finally:
        scan_run.finished_at = datetime.utcnow()
        scan_run.listings_found = result["listings_found"]
        scan_run.listings_new = result["listings_new"]
        scan_run.error = result["error"]
        result["duration_seconds"] = (scan_run.finished_at - scan_run.started_at).total_seconds()
        db.commit()
        db.close()

    # Send notifications for new listings
    if new_listings:
        try:
            send_notification(new_listings)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    return result


def run_all_scans():
    """Run scans for all active sources."""
    logger.info("Starting scheduled scan for all sources")
    results = []
    db = SessionLocal()
    try:
        active_sources = (
            db.query(SearchProfile.source)
            .filter(SearchProfile.active == True)
            .distinct()
            .all()
        )
        sources = [r[0] for r in active_sources] if active_sources else list(SCRAPERS.keys())
    finally:
        db.close()

    for source in sources:
        try:
            result = run_scan_for_source(source)
            results.append(result)
            logger.info(
                f"[{source}] Scan complete: {result['listings_found']} found, "
                f"{result['listings_new']} new, {result['duration_seconds']:.1f}s"
            )
        except Exception as e:
            logger.error(f"Failed to run scan for {source}: {e}")
    return results


def init_scheduler():
    """Initialize and start the APScheduler."""
    interval = settings.search_interval_minutes
    scheduler.add_job(
        run_all_scans,
        "interval",
        minutes=interval,
        id="scan_all",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(f"Scheduler started: scanning every {interval} minutes")
    return scheduler
