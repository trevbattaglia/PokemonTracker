"""Retailer buy links.

Why search URLs and not direct product URLs:

Pokemon Center sits behind Imperva Incapsula and serves a JS challenge to any
non-browser client, so we cannot look up its product URLs -- and per the design
non-goals we don't try. Escalating past that is exactly the anti-bot evasion
this project refuses to do.

The asymmetry that saves us: the link doesn't need to be fetchable by *us*, it
only needs to work when a human taps it. Incapsula blocks bots, not browsers.
So a deterministic search URL is one tap from the notification, costs zero
requests, and can never decay from markup changes -- unlike a scraped product
URL, which rots the moment a retailer reshuffles its catalogue.

All formats below were verified by hand against a real browser.
"""

from __future__ import annotations

from urllib.parse import quote, quote_plus

# (label, template, uses_path_encoding)
# Ordered by how likely they are to actually have sealed product in stock.
_RETAILERS: list[tuple[str, str, bool]] = [
    ("Pokémon Center", "https://www.pokemoncenter.com/search/{q}", True),
    ("Best Buy", "https://www.bestbuy.com/site/searchpage.jsp?st={q}", False),
    ("Target", "https://www.target.com/s?searchTerm={q}", False),
    ("Walmart", "https://www.walmart.com/search?q={q}", False),
    ("Amazon", "https://www.amazon.com/s?k={q}", False),
]


def _query(set_name: str, *, scoped_site: bool) -> str:
    """Pokemon Center only sells Pokemon, so 'Pokemon TCG' there is noise that
    narrows results for no reason. Everywhere else it's needed -- a bare
    'Pitch Black' on Amazon returns paint and movies."""
    return set_name if scoped_site else f"Pokemon TCG {set_name}"


def buy_links(set_name: str) -> list[tuple[str, str]]:
    """[(retailer_label, search_url)] for a set/product name."""
    links: list[tuple[str, str]] = []
    for label, template, path_encoded in _RETAILERS:
        # Pokemon Center puts the term in the path, everyone else in a query
        # param. quote_plus in a path segment would emit a literal '+'.
        scoped = label == "Pokémon Center"
        term = _query(set_name, scoped_site=scoped)
        encoded = quote(term) if path_encoded else quote_plus(term)
        links.append((label, template.format(q=encoded)))
    return links


def buy_field(set_name: str) -> dict[str, str]:
    """A Discord embed field of tappable retailer links."""
    return {
        "name": "Buy",
        "value": " • ".join(f"[{label}]({url})" for label, url in buy_links(set_name)),
        "inline": False,
    }
