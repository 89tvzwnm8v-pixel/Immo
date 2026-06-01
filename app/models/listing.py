from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime


class RawListing(BaseModel):
    external_id: str
    source: str
    url: str
    title: str
    price: Optional[float] = None
    price_per_sqm: Optional[float] = None
    size_sqm: Optional[float] = None
    rooms: Optional[float] = None
    district: Optional[str] = None
    address: Optional[str] = None
    floor: Optional[str] = None
    year_built: Optional[int] = None
    description: Optional[str] = None
    features: List[str] = []
    images: List[str] = []
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    raw_data: Dict[str, Any] = {}


class ListingOut(BaseModel):
    id: int
    external_id: str
    source: str
    url: str
    title: str
    price: Optional[float]
    price_per_sqm: Optional[float]
    size_sqm: Optional[float]
    rooms: Optional[float]
    district: Optional[str]
    address: Optional[str]
    floor: Optional[str]
    year_built: Optional[int]
    description: Optional[str]
    features: List[str] = []
    images: List[str] = []
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    expose_fetched_at: Optional[datetime]

    class Config:
        from_attributes = True


class ScanResult(BaseModel):
    source: str
    listings_found: int
    listings_new: int
    error: Optional[str] = None
    duration_seconds: float


class DashboardStats(BaseModel):
    total_listings: int
    new_today: int
    saved_count: int
    avg_price_per_sqm: Optional[float]
    last_scan: Optional[datetime]
