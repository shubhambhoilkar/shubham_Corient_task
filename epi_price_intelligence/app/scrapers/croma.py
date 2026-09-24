from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import BaseAdapter, RawListing


class CromaAdapter(BaseAdapter):
    source_name = "croma"
    base_url = "https://www.croma.com"

    def build_search_url(self, query: str, filters: dict) -> str:
        return f"{self.base_url}/searchB?q={quote_plus(query)}%3Arelevance&text={quote_plus(query)}"

    def _parse_html(self, soup: BeautifulSoup) -> list[RawListing]:
        # CSS fallback for when JSON-LD is absent from the search results page.
        # Croma's PLP product cards are typically rendered as <li class="product-item"> with
        # a title link, a price block ("₹1,29,490") and a strike-through MRP. Selectors are
        # kept narrow and defensive (missing nodes are skipped, never raise) because retailer
        # markup changes without notice -- this is a best-effort fallback, not the primary path.
        listings: list[RawListing] = []
        for card in soup.select("li.product-item, div.product-item, li[class*='product']"):
            title_el = card.select_one("h3, a.product-title, .product-title")
            price_el = card.select_one(".amount, .new-price, [class*='price']")
            link_el = card.select_one("a[href]")
            if not title_el or not price_el:
                continue
            name = title_el.get_text(strip=True)
            price = _parse_inr(price_el.get_text(strip=True))
            if not name or price is None:
                continue
            listings.append(
                RawListing(
                    source=self.source_name,
                    product_name=name,
                    brand=self.infer_brand(name),
                    model=name,
                    product_url=(
                        self.base_url + link_el["href"]
                        if link_el and link_el.get("href", "").startswith("/")
                        else (link_el["href"] if link_el else self.base_url)
                    ),
                    selling_price=price,
                    seller="Croma",
                )
            )
        return listings


def _parse_inr(text: str):
    digits = "".join(ch for ch in text if ch.isdigit())
    return float(digits) if digits else None
