from app.scrapers.immoscout import ImmoscoutScraper
from app.scrapers.immowelt import ImmoweltScraper
from app.scrapers.immonet import ImmonetScraper

SCRAPERS = {
    "immoscout24": ImmoscoutScraper,
    "immowelt": ImmoweltScraper,
    "immonet": ImmonetScraper,
}

__all__ = ["ImmoscoutScraper", "ImmoweltScraper", "ImmonetScraper", "SCRAPERS"]
