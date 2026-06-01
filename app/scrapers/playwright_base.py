import logging
import random
import time
from abc import abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from app.models.listing import RawListing
from app.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]


class PlaywrightBaseScraper(BaseScraper):
    """Scraper base that renders pages via a real Chromium browser."""

    def __init__(self):
        super().__init__()
        self._pw = None
        self._browser: Optional["Browser"] = None

    def _start_browser(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")
        if self._browser and self._browser.is_connected():
            return
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=BROWSER_ARGS,
        )

    def _stop_browser(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None

    @contextmanager
    def _new_page(self):
        self._start_browser()
        context = self._browser.new_context(
            locale="de-DE",
            user_agent=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.{random.randint(6000,7000)}.{random.randint(0,200)} Safari/537.36",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "Accept-Language": "de-DE,de;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            },
        )
        # Hide automation markers
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()
        try:
            yield page
        finally:
            try:
                context.close()
            except Exception:
                pass

    def fetch_html(self, url: str, wait_for: Optional[str] = None, timeout: int = 30000) -> str:
        """Load URL in Chromium, return rendered HTML."""
        time.sleep(random.uniform(1.5, 3.5))
        with self._new_page() as page:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            # Wait for a specific selector if provided
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=8000)
                except Exception:
                    pass
            else:
                # Give JS time to render
                page.wait_for_timeout(2000)
            return page.content()

    def fetch_html_with_page(self, url: str, timeout: int = 30000):
        """Returns (html, page) — caller must manage context manually for multi-step flows."""
        time.sleep(random.uniform(1.5, 3.5))
        self._start_browser()
        context = self._browser.new_context(
            locale="de-DE",
            user_agent=f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.{random.randint(6000,7000)}.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = context.new_page()
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        html = page.content()
        context.close()
        return html

    def __del__(self):
        self._stop_browser()
        try:
            self.client.close()
        except Exception:
            pass
