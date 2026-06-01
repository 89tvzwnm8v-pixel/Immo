import logging
import re
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
from app.scrapers.base import BaseScraper
from app.models.listing import RawListing

logger = logging.getLogger(__name__)


class ImmoweltScraper(BaseScraper):
    source_name = "immowelt"
    BASE_SEARCH_URL = "https://www.immowelt.de/liste/frankfurt-am-main/wohnungen/kaufen"

    def build_search_url(self, profile: Any) -> str:
        params = []
        if hasattr(profile, "max_price") and profile.max_price:
            params.append(f"pmi={int(profile.max_price)}")
        if hasattr(profile, "min_size") and profile.min_size:
            params.append(f"ami={int(profile.min_size)}")
        if hasattr(profile, "min_rooms") and profile.min_rooms:
            params.append(f"rmi={int(profile.min_rooms)}")
        base = self.BASE_SEARCH_URL
        if params:
            base += "?" + "&".join(params)
        return base

    def fetch_listings(self, profile: Any) -> List[RawListing]:
        url = self.build_search_url(profile)
        listings = []
        try:
            response = self.get(url)
            soup = BeautifulSoup(response.text, "lxml")
            listings.extend(self._parse_listings(soup))
        except Exception as e:
            logger.error(f"ImmoweltScraper.fetch_listings error: {e}", exc_info=True)
        return listings

    def _parse_listings(self, soup: BeautifulSoup) -> List[RawListing]:
        listings = []
        # Immowelt uses data-testid or class-based cards
        cards = (
            soup.select("[data-testid='serp-core-classified-card-testid']")
            or soup.select("article.listitem")
            or soup.select(".EstateItem-module__item")
            or soup.select("div[class*='EstateItem']")
            or soup.select("article[class*='card']")
            or soup.select(".ng-scope .listitem")
        )
        logger.info(f"Immowelt: found {len(cards)} raw cards")

        for card in cards:
            try:
                # Extract link / ID
                link_el = card.select_one("a[href*='/expose/']") or card.select_one("a[href]")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                if href.startswith("/"):
                    href = "https://www.immowelt.de" + href
                # Extract external ID from URL
                id_match = re.search(r"/expose/([A-Za-z0-9]+)", href)
                if not id_match:
                    # Try to get any unique identifier from href
                    id_match = re.search(r"/([A-Za-z0-9]{8,})/?$", href)
                ext_id = id_match.group(1) if id_match else href.split("/")[-1]
                if not ext_id:
                    continue

                # Title
                title_el = (
                    card.select_one("h2")
                    or card.select_one("[data-testid='card-mfe-title']")
                    or card.select_one(".headline")
                    or card.select_one("h3")
                )
                title = title_el.get_text(strip=True) if title_el else f"Wohnung {ext_id}"

                # Price
                price_el = (
                    card.select_one("[data-testid='card-mfe-buying-price-testid']")
                    or card.select_one(".price")
                    or card.select_one("[class*='price' i]")
                )
                price = self.safe_float(price_el.get_text(strip=True)) if price_el else None

                # Size / Rooms
                facts = card.select("[data-testid*='area'], [data-testid*='rooms'], .fact, [class*='fact' i]")
                size = None
                rooms = None
                for fact in facts:
                    txt = fact.get_text(strip=True)
                    if "m²" in txt or "qm" in txt.lower():
                        size = self.safe_float(re.sub(r"[^\d,.]", "", txt.split("m")[0]))
                    elif "Zi" in txt or "Zimmer" in txt:
                        rooms = self.safe_float(re.sub(r"[^\d,.]", "", txt))

                # District / address
                location_el = (
                    card.select_one("[data-testid='card-mfe-location-testid']")
                    or card.select_one(".location")
                    or card.select_one("[class*='location' i]")
                )
                address = location_el.get_text(strip=True) if location_el else None
                district = None
                if address:
                    # Try to extract district from "Frankfurt am Main - Sachsenhausen" pattern
                    m = re.search(r"Frankfurt[^-]*-\s*(.+)", address)
                    if m:
                        district = m.group(1).strip()

                # Image
                img_el = card.select_one("img[src], img[data-src]")
                images = []
                if img_el:
                    img_src = img_el.get("src") or img_el.get("data-src", "")
                    if img_src and img_src.startswith("http"):
                        images = [img_src]

                price_per_sqm = None
                if price and size and size > 0:
                    price_per_sqm = round(price / size, 2)

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
                logger.debug(f"Error parsing Immowelt card: {e}")

        return listings

    def fetch_expose(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.get(url)
            soup = BeautifulSoup(response.text, "lxml")
            data = {}

            # Description
            desc_el = (
                soup.select_one("[data-testid='description-text']")
                or soup.select_one(".objectDescription")
                or soup.select_one("[id='objectdescription']")
                or soup.select_one(".description")
            )
            if desc_el:
                data["description"] = desc_el.get_text(separator="\n", strip=True)

            # Features
            feats = []
            for el in soup.select("[data-testid='features'] li, .equipment li, .ausstattung li"):
                txt = el.get_text(strip=True)
                if txt:
                    feats.append(txt)
            data["features"] = feats

            # Contact
            contact_el = soup.select_one(".contactName, [data-testid='contact-name'], .provider-name")
            if contact_el:
                data["contact_name"] = contact_el.get_text(strip=True)

            phone_el = soup.select_one("[data-testid='contact-phone'], .phone a, a[href^='tel:']")
            if phone_el:
                data["contact_phone"] = phone_el.get_text(strip=True) or phone_el.get("href", "").replace("tel:", "")

            # Images
            imgs = []
            for img in soup.select(".gallery img[src], [data-testid*='gallery'] img"):
                src = img.get("src") or img.get("data-src", "")
                if src and src.startswith("http"):
                    imgs.append(src)
            data["images"] = imgs[:10]

            # Year built
            for row in soup.select("dl dt, .criteriagroup dt, [data-testid*='detail'] dt"):
                label = row.get_text(strip=True).lower()
                val_el = row.find_next_sibling("dd")
                if val_el and ("baujahr" in label or "year" in label):
                    data["year_built"] = self.safe_int(val_el.get_text(strip=True))
                if val_el and "etage" in label:
                    data["floor"] = val_el.get_text(strip=True)

            return data
        except Exception as e:
            logger.error(f"ImmoweltScraper.fetch_expose error for {url}: {e}")
            return None
