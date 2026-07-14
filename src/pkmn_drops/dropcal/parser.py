"""HTML -> Drop. Fixtures in tests/fixtures/ are the contract; if a source
changes its markup, the fixture tests are how we find out before the drop."""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple

from bs4 import BeautifulSoup

from ..config import LOCAL_TZ
from ..models import Drop

SEREBII_BASE = "https://www.serebii.net"

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ],
        start=1,
    )
}

# Typos present in the source itself. Serebii has "Februrary 14th 2007" on the
# EX Power Keepers row. Encode known ones rather than fuzzy matching, so a
# genuinely new month string still surfaces as a skip instead of being guessed.
_MONTHS.update({"februrary": 2, "janurary": 1, "septmber": 9})

# "November 6th 2026" -- all 128 rows on the page use exactly this shape.
_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)\s+(\d{4})$")


class ParseError(RuntimeError):
    """Raised when markup no longer matches expectations."""


def _parse_release_date(text: str) -> datetime:
    m = _DATE_RE.match(text.strip())
    if not m:
        raise ParseError(f"unrecognised date format: {text!r}")
    month_name, day, year = m.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        raise ParseError(f"unrecognised month: {month_name!r}")
    # Serebii publishes a release *date*, never a time. Anchor to local
    # midnight; time_confirmed=False marks it as day-granularity downstream.
    return datetime(int(year), month, int(day), tzinfo=LOCAL_TZ)


class ParseResult(NamedTuple):
    drops: list[Drop]
    skipped: list[str]  # human-readable reasons; surfaced loudly by the caller


def parse_serebii_english(html: str) -> ParseResult:
    """Parse the English sets table.

    A single unparseable row (the source has real typos) must not cost us the
    other 127 rows -- an upcoming drop is what matters. So rows are skipped
    individually and reported. Total failure still raises.
    """
    soup = BeautifulSoup(html, "html.parser")

    table = next(
        (t for t in soup.find_all("table") if "Release Date" in t.get_text()), None
    )
    if table is None:
        raise ParseError("no table containing 'Release Date' -- markup changed")

    drops: list[Drop] = []
    skipped: list[str] = []

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 5:
            continue
        name = cells[2].get_text(strip=True)
        date_text = cells[4].get_text(strip=True)
        if not name or date_text.lower() == "release date":
            continue  # header row

        try:
            when = _parse_release_date(date_text)
        except ParseError as exc:
            skipped.append(f"{name}: {exc}")
            continue

        link = cells[2].find("a")
        url = f"{SEREBII_BASE}{link['href']}" if link and link.get("href") else None

        drops.append(
            Drop(
                product_name=name,
                set_name=name,
                retailer="tcg_release",
                drop_datetime=when,
                time_confirmed=False,
                product_url=url,
                source="serebii:english_sets",
            )
        )

    # A source returning zero results must fail loudly, not silently pass.
    # Silent scraper decay is the #1 failure mode for this kind of tool.
    if not drops:
        detail = f" ({len(skipped)} rows skipped)" if skipped else ""
        raise ParseError(
            f"serebii returned 0 drops{detail} -- markup changed or page empty"
        )

    return ParseResult(drops=drops, skipped=skipped)
