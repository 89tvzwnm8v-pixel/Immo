import logging
import re
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
from app.scrapers.base import BaseScraper
from app.models.listing import RawListing

logger = logging.getLogger(__name__)


class ImmonetScraper(BaseScraper):
    source_name = "immonet"
    BASE_SEARCH_URL = "https://www.immonet.de/immobiliensuche/sel.do"

    def build_search_url(self, profile: Any) -> str:
        # city=80935 is Frankfurt am Main, objecttype=1 = Wohnung, suchart=1 = Kaufen
        params = {
            "suchart": "1",
            "city": "80935",
            "objecttype": "1",
            "listsize": "26",
        }
        if hasattr(profile, "max_price") and profile.max_price:
            params["pricemax"] = str(int(profile.max_price))
        if hasattr(profile, "min_size") and profile.min_size:
            params["areamin"] = str(int(profile.min_size))
        if hasattr(profile, "min_rooms") and profile.min_rooms:
            params["roomsmin"] = str(profile.min_rooms)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_SEARCH_URL}?{query}"

    def fetch_listings(self, profile: Any) -> List[RawListing]:
        url = self.build_search_url(profile)
        listings = []
        try:
            response = self.get(url)
            soup = BeautifulSoup(response.text, "lxml")
            listings.extend(self._parse_listings(soup))
        except Exception as e:
            logger.error(f"ImmonetScraper.fetch_listings error: {e}", exc_info=True)
        return listings

    def _parse_listings(self, soup: BeautifulSoup) -> List[RawListing]:
        listings = []

        # Immonet listing cards
        cards = (
            soup.select("div[id^='item_']")
            or soup.select(".item-container")
            or soup.select("article.item")
            or soup.select("[class*='listitem']")
        )
        logger.info(f"Immonet: found {len(cards)} raw cards")

        for card in cards:
            try:
                # ID from container id="item_12345"
                card_id = card.get("id", "")
                ext_id = card_id.replace("item_", "") if card_id.startswith("item_") else ""

                # Link
                link_el = card.select_one("a[href*='/expose/'], a[href*='anzeige']") or card.select_one("a[href]")
                href = ""
                if link_el:
                    href = link_el.get("href", "")
                    if href.startswith("/"):
                        href = "https://www.immonet.de" + href
                    if not ext_id:
                        m = re.search(r"/(\d+)/?(?:\?|$)", href)
                        if m:
                            ext_id = m.group(1)

                if not ext_id:
                    continue

                # Title
                title_el = (
                    card.select_one("h2 a")
                    or card.select_one(".item-title")
                    or card.select_one("h3")
                    or card.select_one("a.item-link")
                )
                title = title_el.get_text(strip=True) if title_el else f"Wohnung {ext_id}"

                # Price
                price_el = (
                    card.select_one(".item-price .price")
                    or card.select_one("[class*='price' i]")
                    or card.select_one(".h4")
                )
                price = self.safe_float(price_el.get_text(strip=True)) if price_el else None

                # Size & Rooms from criteria
                size = None
                rooms = None
                for el in card.select(".item-info td, .item-details td, .proptypelist span"):
                    txt = el.get_text(strip=True)
                    if "m²" in txt:
                        size = self.safe_float(re.sub(r"[^\d,.]", "", txt.split("m")[0]))
                    if "Zi." in txt or "Zimmer" in txt:
                        rooms = self.safe_float(re.sub(r"[^\d,.]", "", txt))

                # Address
                addr_el = (
                    card.select_one(".item-location")
                    or card.select_one("[class*='location' i]")
                    or card.select_one(".item-address")
                )
                address = addr_el.get_text(strip=True) if addr_el else None
                district = None
                if address:
                    m = re.search(r"Frankfurt[^-]*-\s*(.+)", address)
                    if m:
                        district = m.group(1).strip()

                # Image
                img_el = card.select_one("img[src]")
                images = []
                if img_el:
                    src = img_el.get("src", "")
                    if src.startswith("http"):
                        images = [src]

                price_per_sqm = None
                if price and size and size > 0:
                    price_per_sqm = round(price / size, 2)

                if not href:
                    href = f"https://www.immonet.de/anzeige/{ext_id}"

                listings.append(RawListing(
                    external_id=ext_id,
                    source=self.source_name,
                    url=href,
                    title=title,
                    price=price,
                    price_per_sqm=price_per_sqm,
                    size_sqm=size,
                    rooms=rooms,
                    district=district,
                    address=address,
                    images=images,
                    raw_data={"href": href},
                ))
            except Exception as e:
                logger.debug(f"Error parsing Immonet card: {e}")

        return listings

    def fetch_expose(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.get(url)
            soup = BeautifulSoup(response.text, "lxml")
            data = {}

            # Description
            desc_el = (
                soup.select_one("#aobj-longdesc")
                or soup.select_one(".description-text")
                or soup.select_one("[itemprop='description']")
            )
            if desc_el:
                data["description"] = desc_el.get_text(separator="\n", strip=True)

            # Features / Equipment
            feats = []
            for el in soup.select(".equip-list li, #equip li, .ausstattung li"):
                txt = el.get_text(strip=True)
                if txt:
                    feats.append(txt)
            data["features"] = feats

            # Contact info
            contact_el = soup.select_one(".provider-name, .contact-name, [itemprop='name']")
            if contact_el:
                data["contact_name"] = contact_el.get_text(strip=True)

            phone_el = soup.select_one("a[href^='tel:']")
            if phone_el:
                data["contact_phone"] = phone_el.get("href", "").replace("tel:", "")

            # Images
            imgs = []
            for img in soup.select(".gallery-item img, [class*='gallery'] img, .slick-slide img"):
                src = img.get("src") or img.get("data-src", "")
                if src and src.startswith("http"):
                    imgs.append(src)
            data["images"] = list(dict.fromkeys(imgs))[:10]  # deduplicate

            # Details table for year_built and floor
            for row in soup.select("table.criteria-list tr, .prop-list li"):
                txt = row.get_text(" ", strip=True).lower()
                if "baujahr" in txt:
                    m = re.search(r"\d{4}", txt)
                    if m:
                        data["year_built"] = int(m.group(0))
                if "etage" in txt and "floor" not in data:
                    data["floor"] = row.get_text(strip=True)

            return data
        except Exception as e:
            logger.error(f"ImmonetScraper.fetch_expose error for {url}: {e}")
            return None
