"""Best Buy Products API ingest.

Why Best Buy and not a scraper: this is an *official, keyed, sanctioned* API
with a published 5 req/sec, 50k req/day allowance. Polling it every 15 minutes
is nowhere near the "high-frequency polling" the design doc rules out -- that
non-goal is about hammering retailers who never invited you. Best Buy did.

Pokemon Center remains off-limits (Incapsula, JS challenge) and Target's
RedSky is an undocumented internal API, so neither is used.
"""

from __future__ import annotations

import os
from urllib.parse import quote

import requests

from ...models import Product

BASE = "https://api.bestbuy.com/v1/products"
RETAILER = "best_buy"
TIMEOUT = 30
PAGE_SIZE = 100  # API max; one request covers a whole search term

# Only ask for what we use. show=all returns a very large payload per product.
FIELDS = "sku,name,salePrice,regularPrice,onlineAvailability,orderable,url,releaseDate"


class BestBuyError(RuntimeError):
    pass


def api_key() -> str:
    key = os.environ.get("BESTBUY_API_KEY", "").strip()
    if not key:
        raise BestBuyError(
            "BESTBUY_API_KEY is not set. Get a free key at "
            "https://developer.bestbuy.com/ and put it in .env (local) or "
            "GitHub Actions secrets (CI)."
        )
    return key


def _search_url(term: str) -> str:
    # Best Buy's query syntax is positional: products(<query>)?<params>.
    # The search term goes inside the parens, not as a normal query param.
    return f"{BASE}((search={quote(term)}))"


def fetch(term: str, *, key: str | None = None) -> dict:
    """Raw JSON for one search term."""
    try:
        resp = requests.get(
            _search_url(term),
            params={
                "format": "json",
                "show": FIELDS,
                "pageSize": PAGE_SIZE,
                "apiKey": key or api_key(),
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise BestBuyError(f"best buy request failed: {exc}") from exc

    if resp.status_code == 403:
        raise BestBuyError("best buy rejected the API key (403)")
    if resp.status_code == 429:
        # Back off rather than escalate; the doc is explicit about this.
        raise BestBuyError("best buy rate limited us (429) -- back off")
    if resp.status_code != 200:
        raise BestBuyError(f"best buy returned {resp.status_code}: {resp.text[:200]}")

    return resp.json()


def parse(payload: dict, *, term: str) -> list[Product]:
    """Best Buy JSON -> Product.

    `onlineAvailability` is a documented boolean and is the stock signal.
    `orderable` is recorded but never branched on: its value vocabulary is
    undocumented, and guessing it would mean guessing whether an alert is real.
    """
    if "products" not in payload:
        raise BestBuyError(f"unexpected payload shape: {sorted(payload)[:6]}")

    out: list[Product] = []
    for p in payload["products"]:
        sku = p.get("sku")
        name = p.get("name")
        if sku is None or not name:
            continue  # nothing actionable without an identity

        price = p.get("salePrice")
        if price is None:
            price = p.get("regularPrice")

        out.append(
            Product(
                sku=str(sku),
                name=name,
                retailer=RETAILER,
                in_stock=bool(p.get("onlineAvailability")),
                url=p.get("url") or f"https://www.bestbuy.com/site/searchpage.jsp?st={quote(name)}",
                price=float(price) if price is not None else None,
                raw_status=p.get("orderable"),
                source=f"bestbuy_api:{term}",
            )
        )
    return out


def ingest(terms: list[str], *, key: str | None = None) -> list[Product]:
    """Fetch every watchlist term. One request per term, well inside quota."""
    key = key or api_key()
    products: list[Product] = []
    for term in terms:
        products.extend(parse(fetch(term, key=key), term=term))
    return products
