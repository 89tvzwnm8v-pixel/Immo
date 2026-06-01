import httpx
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.models.listing import RawListing

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


class BaseScraper(ABC):
    source_name: str = ""

    def __init__(self):
        self.client = httpx.Client(
            headers={**DEFAULT_HEADERS, "User-Agent": random.choice(USER_AGENTS)},
            timeout=30.0,
            follow_redirects=True,
            http2=True,
        )

    def __del__(self):
        try:
            self.client.close()
        except Exception:
            pass

    def get(self, url: str, referer: Optional[str] = None, **kwargs) -> httpx.Response:
        headers = {}
        if referer:
            headers["Referer"] = referer
        # rotate User-Agent per request
        headers["User-Agent"] = random.choice(USER_AGENTS)
        time.sleep(random.uniform(1.0, 3.0))
        try:
            response = self.client.get(url, headers=headers, **kwargs)
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
