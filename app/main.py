import logging
import os
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, init_db, Listing, ScanRun, SearchProfile
from app.scheduler import init_scheduler, run_all_scans, run_scan_for_source
from app.services.expose import fetch_and_store_expose

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Frankfurt Immo-Scanner", version="1.0.0")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Template filters / globals ---

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
    v = float(value)
    return f"{v:g} Zi."

def format_dt(value):
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)

templates.env.filters["price"] = format_price
templates.env.filters["sqm"] = format_sqm
templates.env.filters["rooms"] = format_rooms
templates.env.filters["dt"] = format_dt


@app.on_event("startup")
async def startup():
    init_db()
    init_scheduler()
    logger.info("Immo-Scanner started")


@app.on_event("shutdown")
async def shutdown():
    from app.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


# ---- Dashboard ----

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    total = db.query(func.count(Listing.id)).scalar() or 0

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = db.query(func.count(Listing.id)).filter(
        Listing.first_seen_at >= today_start
    ).scalar() or 0

    saved = db.query(func.count(Listing.id)).filter(Listing.status == "saved").scalar() or 0

    avg_ppsm = db.query(func.avg(Listing.price_per_sqm)).filter(
        Listing.price_per_sqm.isnot(None)
    ).scalar()

    last_scan_row = db.query(ScanRun.finished_at).order_by(desc(ScanRun.finished_at)).first()
    last_scan = last_scan_row[0] if last_scan_row else None

    recent = (
        db.query(Listing)
        .order_by(desc(Listing.first_seen_at))
        .limit(20)
        .all()
    )

    source_counts = {}
    for row in db.query(Listing.source, func.count(Listing.id)).group_by(Listing.source).all():
        source_counts[row[0]] = row[1]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total": total,
        "new_today": new_today,
        "saved": saved,
        "avg_ppsm": round(avg_ppsm, 0) if avg_ppsm else None,
        "last_scan": last_scan,
        "recent_listings": recent,
        "source_counts": source_counts,
    })


# ---- Listings list ----

@app.get("/listings", response_class=HTMLResponse)
async def listings_page(
    request: Request,
    db: Session = Depends(get_db),
    source: Optional[str] = None,
    status: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_size: Optional[float] = None,
    max_size: Optional[float] = None,
    district: Optional[str] = None,
    page: int = 1,
):
    q = db.query(Listing)
    if source:
        q = q.filter(Listing.source == source)
    if status:
        q = q.filter(Listing.status == status)
    if min_price:
        q = q.filter(Listing.price >= min_price)
    if max_price:
        q = q.filter(Listing.price <= max_price)
    if min_size:
        q = q.filter(Listing.size_sqm >= min_size)
    if max_size:
        q = q.filter(Listing.size_sqm <= max_size)
    if district:
        q = q.filter(Listing.district.ilike(f"%{district}%"))

    total = q.count()
    per_page = 25
    listings = q.order_by(desc(Listing.first_seen_at)).offset((page - 1) * per_page).limit(per_page).all()

    districts = [r[0] for r in db.query(Listing.district).filter(Listing.district.isnot(None)).distinct().all()]

    return templates.TemplateResponse("listings.html", {
        "request": request,
        "listings": listings,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "filters": {
            "source": source, "status": status, "min_price": min_price,
            "max_price": max_price, "min_size": min_size, "max_size": max_size,
            "district": district,
        },
        "districts": sorted(d for d in districts if d),
    })


# ---- Single listing ----

@app.get("/listings/{listing_id}", response_class=HTMLResponse)
async def listing_detail(request: Request, listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    # Auto-mark as seen if status=new
    if listing.status == "new":
        listing.status = "seen"
        db.commit()
    return templates.TemplateResponse("listing.html", {"request": request, "listing": listing})


# ---- Status update ----

@app.post("/listings/{listing_id}/status")
async def update_status(listing_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if status not in ("new", "seen", "saved", "archived"):
        raise HTTPException(status_code=400, detail="Invalid status")
    listing.status = status
    db.commit()
    return RedirectResponse(url=f"/listings/{listing_id}", status_code=303)


# ---- Fetch expose ----

@app.post("/listings/{listing_id}/fetch-expose")
async def trigger_fetch_expose(listing_id: int, db: Session = Depends(get_db)):
    ok = fetch_and_store_expose(listing_id, db)
    return JSONResponse({"success": ok, "listing_id": listing_id})


# ---- Manual scan ----

@app.get("/scan")
async def manual_scan(source: Optional[str] = None):
    if source:
        results = [run_scan_for_source(source)]
    else:
        results = run_all_scans()
    return JSONResponse({"status": "ok", "results": results})


# ---- Settings ----

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    profiles = db.query(SearchProfile).order_by(SearchProfile.source).all()
    recent_scans = db.query(ScanRun).order_by(desc(ScanRun.started_at)).limit(20).all()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "profiles": profiles,
        "recent_scans": recent_scans,
    })


@app.post("/settings")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    # Update .env file with new values
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    env_vars = {
        "SMTP_HOST": form.get("smtp_host", settings.smtp_host),
        "SMTP_PORT": form.get("smtp_port", str(settings.smtp_port)),
        "SMTP_USER": form.get("smtp_user", settings.smtp_user),
        "SMTP_PASSWORD": form.get("smtp_password", settings.smtp_password),
        "NOTIFY_EMAIL": form.get("notify_email", settings.notify_email),
        "MAX_PRICE": form.get("max_price", str(settings.max_price)),
        "MIN_SIZE": form.get("min_size", str(settings.min_size)),
        "MIN_ROOMS": form.get("min_rooms", str(settings.min_rooms)),
        "SEARCH_INTERVAL_MINUTES": form.get("search_interval_minutes", str(settings.search_interval_minutes)),
        "BASE_URL": form.get("base_url", settings.base_url),
    }
    lines = []
    for k, v in env_vars.items():
        lines.append(f"{k}={v}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    return RedirectResponse(url="/settings?saved=1", status_code=303)


# ---- API endpoints ----

@app.get("/api/listings")
async def api_listings(db: Session = Depends(get_db), status: Optional[str] = None, limit: int = 50):
    q = db.query(Listing)
    if status:
        q = q.filter(Listing.status == status)
    items = q.order_by(desc(Listing.first_seen_at)).limit(limit).all()
    return [
        {
            "id": l.id,
            "source": l.source,
            "title": l.title,
            "price": l.price,
            "size_sqm": l.size_sqm,
            "rooms": l.rooms,
            "district": l.district,
            "status": l.status,
            "url": l.url,
            "first_seen_at": l.first_seen_at.isoformat() if l.first_seen_at else None,
        }
        for l in items
    ]


@app.get("/api/stats")
async def api_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Listing.id)).scalar() or 0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = db.query(func.count(Listing.id)).filter(Listing.first_seen_at >= today_start).scalar() or 0
    avg_ppsm = db.query(func.avg(Listing.price_per_sqm)).filter(Listing.price_per_sqm.isnot(None)).scalar()
    return {
        "total": total,
        "new_today": new_today,
        "avg_price_per_sqm": round(avg_ppsm, 2) if avg_ppsm else None,
    }
