from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import BaseAdapter, RawListing


class VijaySalesAdapter(BaseAdapter):
    source_name = "vijay_sales"
    base_url = "https://www.vijaysales.com"

    def build_search_url(self, query: str, filters: dict) -> str:
        return f"{self.base_url}/search/{quote_plus(query)}"

    def _parse_html(self, soup: BeautifulSoup) -> list[RawListing]:
        # Fallback CSS parsing for Vijay Sales product-listing cards, mirroring the same
        # defensive approach as the Croma adapter (see croma.py for rationale).
        listings: list[RawListing] = []
        for card in soup.select("div.product-item, div[class*='product-box'], li[class*='product']"):
            title_el = card.select_one("h3, a.product-name, .product-name")
            price_el = card.select_one(".price, .special-price, [class*='price']")
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
                    seller="Vijay Sales",
                )
            )
        return listings


def _parse_inr(text: str):
    digits = "".join(ch for ch in text if ch.isdigit())
    return float(digits) if digits else None
