import json
import logging
import re
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
from app.scrapers.base import BaseScraper
from app.models.listing import RawListing

logger = logging.getLogger(__name__)


class ImmoscoutScraper(BaseScraper):
    source_name = "immoscout24"
    BASE_SEARCH_URL = "https://www.immobilienscout24.de/Suche/de/hessen/frankfurt-am-main/wohnung-kaufen"

    def build_search_url(self, profile: Any) -> str:
        params = []
        if hasattr(profile, "max_price") and profile.max_price:
            params.append(f"kaufpreis=-{int(profile.max_price)}")
        if hasattr(profile, "min_size") and profile.min_size:
            params.append(f"wohnflaeche={int(profile.min_size)}-")
        if hasattr(profile, "min_rooms") and profile.min_rooms:
            params.append(f"zimmer={profile.min_rooms}-")
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

            # Try to extract from embedded JSON __INITIAL_STATE__
            scripts = soup.find_all("script")
            json_data = None
            for script in scripts:
                if script.string and "__INITIAL_STATE__" in script.string:
                    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", script.string, re.DOTALL)
                    if match:
                        try:
                            json_data = json.loads(match.group(1))
                            break
                        except json.JSONDecodeError:
                            pass

            if json_data:
                listings.extend(self._parse_from_json(json_data))
            else:
                listings.extend(self._parse_from_html(soup))

        except Exception as e:
            logger.error(f"ImmoscoutScraper.fetch_listings error: {e}", exc_info=True)

        return listings

    def _parse_from_json(self, data: dict) -> List[RawListing]:
        listings = []
        try:
            # Navigate the nested structure
            results = (
                data.get("searchResult", {})
                .get("searchResponseModel", {})
                .get("resultlist.resultlist", {})
                .get("resultlistEntries", [{}])[0]
                .get("resultlistEntry", [])
            )
            for entry in results:
                try:
                    re_data = entry.get("resultlist.realEstate", {})
                    ext_id = str(entry.get("@id", "") or re_data.get("@id", ""))
                    if not ext_id:
                        continue
                    price_raw = re_data.get("price", {})
                    price = self.safe_float(price_raw.get("value"))
                    size = self.safe_float(re_data.get("livingSpace"))
                    rooms = self.safe_float(re_data.get("numberOfRooms"))
                    address = re_data.get("address", {})
                    district = address.get("quarter") or address.get("city")
                    addr_str = ", ".join(filter(None, [
                        address.get("street"),
                        address.get("houseNumber"),
                        address.get("postcode"),
                        address.get("city"),
                    ]))
                    title = re_data.get("title", f"Wohnung {ext_id}")
                    listing_url = f"https://www.immobilienscout24.de/expose/{ext_id}"
                    price_per_sqm = None
                    if price and size and size > 0:
                        price_per_sqm = round(price / size, 2)
                    imgs = []
                    for img in re_data.get("titlePicture", {}).get("urls", []):
                        for scale in img.values():
                            if isinstance(scale, str) and scale.startswith("http"):
                                imgs.append(scale)
                                break
                    listings.append(RawListing(
                        external_id=ext_id,
                        source=self.source_name,
                        url=listing_url,
                        title=title,
                        price=price,
                        price_per_sqm=price_per_sqm,
                        size_sqm=size,
                        rooms=rooms,
                        district=district,
                        address=addr_str,
                        images=imgs[:5],
                        raw_data=re_data,
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing IS24 entry: {e}")
        except Exception as e:
            logger.error(f"Error parsing IS24 JSON: {e}")
        return listings

    def _parse_from_html(self, soup: BeautifulSoup) -> List[RawListing]:
        listings = []
        try:
            items = soup.select("li[data-id]") or soup.select("[data-obid]") or soup.select(".result-list__listing")
            for item in items:
                try:
                    ext_id = item.get("data-id") or item.get("data-obid", "")
                    if not ext_id:
                        continue
                    title_el = item.select_one("h5, .result-list-entry__brand-title, [data-ng-bind]")
                    title = title_el.get_text(strip=True) if title_el else f"Wohnung {ext_id}"
                    price_el = item.select_one(".result-list-entry__primary-criterion dd, [data-ng-bind*='price']")
                    price = self.safe_float(price_el.get_text(strip=True)) if price_el else None
                    size_el = item.select_one(".result-list-entry__primary-criterion dd:nth-child(2)")
                    size = self.safe_float(size_el.get_text(strip=True)) if size_el else None
                    listing_url = f"https://www.immobilienscout24.de/expose/{ext_id}"
                    listings.append(RawListing(
                        external_id=str(ext_id),
                        source=self.source_name,
                        url=listing_url,
                        title=title,
                        price=price,
                        size_sqm=size,
                    ))
                except Exception as e:
                    logger.debug(f"Error parsing IS24 HTML item: {e}")
        except Exception as e:
            logger.error(f"Error in IS24 HTML parsing: {e}")
        return listings

    def fetch_expose(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.get(url)
            soup = BeautifulSoup(response.text, "lxml")
            data = {}

            # Try JSON first
            scripts = soup.find_all("script")
            for script in scripts:
                if script.string and "__INITIAL_STATE__" in script.string:
                    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", script.string, re.DOTALL)
                    if match:
                        try:
                            json_data = json.loads(match.group(1))
                            expose = json_data.get("expose", {}).get("exposeModel", {})
                            re_data = expose.get("expose.realEstate", {})
                            data["description"] = re_data.get("descriptionNote", "")
                            data["equipment"] = re_data.get("furnishingNote", "")
                            data["location_note"] = re_data.get("locationNote", "")
                            contact = expose.get("expose.agent", {})
                            data["contact_name"] = contact.get("person", {}).get("firstname", "") + " " + contact.get("person", {}).get("lastname", "")
                            data["contact_phone"] = contact.get("phoneNumber", "")
                            data["year_built"] = re_data.get("constructionYear")
                            data["floor"] = str(re_data.get("floor", "")) if re_data.get("floor") is not None else None
                            imgs = []
                            for att in re_data.get("attachments", []):
                                for url_obj in att.get("urls", []):
                                    for scale, img_url in url_obj.items():
                                        if isinstance(img_url, str) and img_url.startswith("http"):
                                            imgs.append(img_url)
                                            break
                            data["images"] = imgs[:10]
                            return data
                        except Exception as e:
                            logger.debug(f"IS24 expose JSON parse error: {e}")

            # Fallback HTML
            desc_el = soup.select_one("[data-qa='description'] p, .is24-text.description p")
            if desc_el:
                data["description"] = desc_el.get_text(strip=True)
            feats = []
            for feat_el in soup.select(".criteriagroup.boolean-listing li"):
                feats.append(feat_el.get_text(strip=True))
            data["features"] = feats
            return data
        except Exception as e:
            logger.error(f"ImmoscoutScraper.fetch_expose error for {url}: {e}")
            return None
