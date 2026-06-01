from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, index=True)
    source = Column(String, index=True)
    url = Column(String)
    title = Column(String)
    price = Column(Float, nullable=True)
    price_per_sqm = Column(Float, nullable=True)
    size_sqm = Column(Float, nullable=True)
    rooms = Column(Float, nullable=True)
    district = Column(String, nullable=True)
    address = Column(String, nullable=True)
    floor = Column(String, nullable=True)
    year_built = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    features = Column(JSON, default=list)
    images = Column(JSON, default=list)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    status = Column(String, default="new")
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expose_fetched_at = Column(DateTime, nullable=True)
    raw_data = Column(JSON, default=dict)

    def __repr__(self):
        return f"<Listing {self.source}:{self.external_id}>"


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    listings_found = Column(Integer, default=0)
    listings_new = Column(Integer, default=0)
    error = Column(String, nullable=True)


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    active = Column(Boolean, default=True)
    source = Column(String)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    min_size = Column(Float, nullable=True)
    max_size = Column(Float, nullable=True)
    min_rooms = Column(Float, nullable=True)
    districts = Column(JSON, default=list)
    keywords = Column(JSON, default=list)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    # Create default search profiles if none exist
    db = SessionLocal()
    try:
        if db.query(SearchProfile).count() == 0:
            from app.config import settings
            sources = ["immoscout24", "immowelt", "immonet"]
            for source in sources:
                profile = SearchProfile(
                    name=f"Frankfurt {source.capitalize()} default",
                    active=True,
                    source=source,
                    max_price=settings.max_price,
                    min_size=settings.min_size,
                    min_rooms=settings.min_rooms,
                    districts=settings.districts_list,
                    keywords=[],
                )
                db.add(profile)
            db.commit()
    finally:
        db.close()
