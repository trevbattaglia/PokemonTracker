"""Scrapers. One function per source. Each returns raw text for a parser.

Serebii's robots.txt disallows only /hidden/ranch/ and /crossword/, so this
page is in bounds. Fetched once daily -- see the doc's rate-limit non-goals.
"""

from __future__ import annotations

import requests

from .. import net

SEREBII_ENGLISH_SETS = "https://www.serebii.net/card/english.shtml"

USER_AGENT = "pkmn-drops/0.1 (personal drop calendar; contact via GitHub)"
TIMEOUT = 30


class SourceError(RuntimeError):
    """Raised when a source is unreachable or returns something unusable."""


def fetch_serebii_english() -> str:
    # net.get rides out a transient timeout with a short backoff; a bad status
    # or an outage that outlasts the retries still lands here as SourceError.
    try:
        resp = net.get(
            SEREBII_ENGLISH_SETS,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SourceError(f"serebii fetch failed: {exc}") from exc

    # The page declares no charset. requests would fall back to ISO-8859-1 and
    # mangle every accented character ("Pokémon" -> "PokÃ©mon"). Force cp1252,
    # which is what the page is actually encoded in.
    resp.encoding = "windows-1252"
    return resp.text
