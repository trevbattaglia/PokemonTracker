"""NowInStock ingest — the design doc's actual Phase 2 plan.

    "The monitoring problem is already solved by people with dedicated
     infrastructure. Re-solving it means fighting Akamai/PerimeterX for a
     signal you can get for free. Don't. Aggregate instead."

That was right, and every direct-retailer path proved it:

  - Pokemon Center: robots.txt disallows /availabilities, /prices, /items,
    /offers — and Incapsula serves a JS challenge regardless.
  - Target RedSky: redsky.target.com/robots.txt is `Disallow: /`, and it
    requires an API key anyway.
  - Best Buy API: sanctioned, but a key requires a non-free email domain.
  - Reddit: robots.txt is `Disallow: /` and it rate-limits on sight.

NowInStock already aggregates Amazon, Target, Walmart, Best Buy and Sam's Club,
and its robots.txt permits /collectibles/ (it disallows only get_item.php and
the alert-setting endpoints). So we read one page politely and let them do the
monitoring they're already doing.
"""

from __future__ import annotations

import hashlib
import re
from typing import NamedTuple

import requests
from bs4 import BeautifulSoup

from ... import net
from ...models import Product

URL = "https://www.nowinstock.net/collectibles/tradingcards/pokemoncards/"
USER_AGENT = (
    "pkmn-drops/0.1 (personal restock relay; "
    "+https://github.com/trevbattaglia/PokemonTracker)"
)
TIMEOUT = 30

# Observed on a real capture, 2026-07-14: 216x Out of Stock, 9x In Stock,
# 1x Preorder, 1x Stock Available. Anything outside this map is reported as a
# skip rather than guessed at -- the stock signal decides whether an alert is
# real, so a wrong guess here is a wrong alert.
_BUYABLE = {
    "in stock": True,
    "stock available": True,
    # A live preorder IS the buying moment for sealed Pokemon -- Pokemon Center
    # sold out of Pitch Black at preorder, days before release. The alert shows
    # the raw status, so "Preorder" never masquerades as "In Stock".
    "preorder": True,
    "pre-order": True,
    "out of stock": False,
    "sold out": False,
}

# NowInStock lists an aggregate "Ebay : All Models" pseudo-row that isn't a
# purchasable product.
_NOT_A_RETAILER = {"all models"}

_RETAILERS = {
    "amazon": "amazon",
    "target": "target",
    "walmart": "walmart",
    "best buy": "best_buy",
    "sam's club": "sams_club",
    "costco": "costco",
    "gamestop": "gamestop",
}


class NowInStockError(RuntimeError):
    pass


class IngestResult(NamedTuple):
    products: list[Product]
    skipped: list[str]


def fetch() -> str:
    # net.get retries a transient timeout so one network blip doesn't crash the
    # 15-min relay and dump a traceback to Discord; a bad status or an outage
    # that survives the retries still surfaces here as NowInStockError.
    try:
        resp = net.get(URL, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise NowInStockError(f"nowinstock fetch failed: {exc}") from exc
    # Honestly declares UTF-8 in both the meta tag and the Content-Type header,
    # so requests gets this right on its own. (Serebii does not -- see
    # dropcal/sources.py.)
    return resp.text


def _price(text: str) -> float | None:
    """Prices come through as '$54.99', '-', 'See Site', or '$1,160.99'.

    An unknown price must stay None, never 0.0: a max_price rule treats None as
    "can't prove it's under budget" and filters it, whereas 0.0 would sail
    through every rule and alert on a scalper listing.
    """
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _sku(retailer: str, name: str) -> str:
    """NowInStock exposes no SKU, so synthesise a stable one. Must be derived
    only from fields that don't change on restock -- price and status both
    move, and a shifting sku would look like a brand-new product every time."""
    return hashlib.sha256(f"{retailer}|{name.lower()}".encode()).hexdigest()[:12]


def parse(html: str) -> IngestResult:
    soup = BeautifulSoup(html, "html.parser")

    products: list[Product] = []
    skipped: list[str] = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue

        label = cells[0].get_text(" ", strip=True)
        if not label or " : " not in label:
            continue  # header rows and layout cruft

        name, _, retailer_label = label.rpartition(" : ")
        name, retailer_label = name.strip(), retailer_label.strip()
        if not name or retailer_label.lower() in _NOT_A_RETAILER:
            continue

        status = cells[1].get_text(" ", strip=True)
        in_stock = _BUYABLE.get(status.lower())
        if in_stock is None:
            skipped.append(f"{name} : {retailer_label} -> unknown status {status!r}")
            continue

        # Passed through verbatim, affiliate redirects and all (mavely.app.link,
        # skimresources, bestbuy.7tiv.net). They do the monitoring we're getting
        # for free; stripping their commission to save you a redirect would be a
        # shabby way to repay that, and the links resolve to the same product.
        link = cells[0].find("a")
        url = link["href"] if link and link.get("href") else URL

        retailer = _RETAILERS.get(
            retailer_label.lower(),
            re.sub(r"[^a-z0-9]+", "_", retailer_label.lower()).strip("_"),
        )

        products.append(
            Product(
                sku=_sku(retailer, name),
                name=name,
                retailer=retailer,
                in_stock=in_stock,
                url=url,
                price=_price(cells[2].get_text(" ", strip=True)),
                raw_status=status,
                source="nowinstock",
            )
        )

    if not products:
        raise NowInStockError(
            f"nowinstock returned 0 products ({len(skipped)} skipped) -- "
            "markup changed or page empty"
        )

    return IngestResult(products=products, skipped=skipped)


def ingest() -> IngestResult:
    return parse(fetch())
