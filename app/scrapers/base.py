import httpx
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.models.listing import RawListing

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class BaseScraper(ABC):
    source_name: str = ""

    def __init__(self):
        self.client = httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )

    def __del__(self):
        try:
            self.client.close()
        except Exception:
            pass

    def get(self, url: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} for {url}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            raise

    @abstractmethod
    def build_search_url(self, profile: Any) -> str:
        pass

    @abstractmethod
    def fetch_listings(self, profile: Any) -> List[RawListing]:
        pass

    @abstractmethod
    def fetch_expose(self, url: str) -> Optional[Dict[str, Any]]:
        pass

    def safe_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            cleaned = str(value).replace(".", "").replace(",", ".").strip()
            cleaned = "".join(c for c in cleaned if c.isdigit() or c == ".")
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None

    def safe_int(self, value: Any) -> Optional[int]:
        f = self.safe_float(value)
        return int(f) if f is not None else None
