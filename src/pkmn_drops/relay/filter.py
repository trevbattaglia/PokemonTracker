"""Watchlist filtering.

A false negative here means you miss a drop, which is the failure this whole
project exists to prevent. So the rules are deliberately dumb and explicit:
substring matching, no fuzzy logic, no stemming. If a product slips through
that shouldn't, add an exclude term -- don't make the matcher clever.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..config import WATCHLIST_PATH
from ..models import Product


@dataclass(frozen=True)
class Rule:
    # A single string is one required substring. A list means *every* term must
    # be present (AND), which is how a rule can require both "Center" and "Elite
    # Trainer Box" -- a Pokemon Center Edition ETB -- without also matching a
    # plain ETB or a non-ETB Pokemon Center product.
    match: str | tuple[str, ...]
    retailers: tuple[str, ...] = ()
    max_price: float | None = None

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.match,) if isinstance(self.match, str) else tuple(self.match)


@dataclass(frozen=True)
class Watchlist:
    rules: tuple[Rule, ...]
    exclude: tuple[str, ...]

    def matches(self, p: Product) -> bool:
        name = p.name.lower()

        if any(term.lower() in name for term in self.exclude):
            return False

        for rule in self.rules:
            # Every required term must appear. Still dumb substring matching, no
            # fuzzy logic -- just conjunctive now so a rule can pin down an
            # edition, not only a product type.
            if not all(t.lower() in name for t in rule.terms):
                continue
            if rule.retailers and p.retailer not in rule.retailers:
                continue
            # An unknown price must not silently pass a max_price rule -- if we
            # can't prove it's under budget, don't claim it is.
            if rule.max_price is not None:
                if p.price is None or p.price > rule.max_price:
                    continue
            return True

        return False

    def search_terms(self) -> list[str]:
        """What to actually ask a retailer for. Without this the ingest would
        have to pull the entire catalogue and filter locally. A multi-term rule
        collapses to a single space-joined query."""
        return [" ".join(r.terms) for r in self.rules]


class WatchlistError(RuntimeError):
    pass


def load(path: Path | None = None) -> Watchlist:
    p = Path(path or WATCHLIST_PATH)
    if not p.exists():
        raise WatchlistError(f"no watchlist at {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    entries = raw.get("watchlist") or []
    if not entries:
        # An empty watchlist would silently match nothing and the relay would
        # look healthy while alerting on nothing at all.
        raise WatchlistError(f"{p} has no watchlist entries -- relay would be a no-op")

    rules = []
    for e in entries:
        m = e.get("match")
        if not m:
            raise WatchlistError(f"watchlist entry missing 'match': {e!r}")
        # A YAML list becomes an all-of term set; a scalar stays a single term.
        if isinstance(m, list):
            m = tuple(m)
        rules.append(
            Rule(
                match=m,
                retailers=tuple(e.get("retailers") or ()),
                max_price=e.get("max_price"),
            )
        )

    return Watchlist(rules=tuple(rules), exclude=tuple(raw.get("exclude") or ()))
