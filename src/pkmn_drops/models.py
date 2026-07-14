"""Shared schema. Lock this before anything else depends on it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Product:
    """A purchasable SKU at a retailer.

    Distinct from Drop on purpose. A Drop is a calendar event ("Pitch Black
    releases July 17"); a Product is a thing with a price and a stock level
    ("Pitch Black Elite Trainer Box, $49.99, in stock at Best Buy"). Phase 1
    proved you cannot buy a Drop -- Pokemon Center had every Pitch Black
    product sold out three days before Pitch Black's own release date.
    """

    sku: str
    name: str
    retailer: str
    in_stock: bool
    url: str
    source: str
    price: float | None = None
    # Retailer's own status string. Best Buy's `orderable` vocabulary is
    # undocumented, so it is recorded but never branched on until observed.
    raw_status: str | None = None

    @property
    def key(self) -> str:
        return f"{self.retailer}:{self.sku}"


@dataclass(frozen=True)
class Drop:
    product_name: str
    retailer: str
    drop_datetime: datetime
    time_confirmed: bool
    source: str
    sku: str | None = None
    set_name: str | None = None
    product_url: str | None = None
    msrp: float | None = None

    def __post_init__(self) -> None:
        if self.drop_datetime.tzinfo is None:
            raise ValueError(
                f"drop_datetime must be timezone-aware, got naive: {self.drop_datetime!r}"
            )

    @property
    def key(self) -> str:
        """Stable identity across runs. Excludes drop_datetime so that a
        rescheduled drop is recognised as *changed* rather than as a new drop."""
        raw = f"{self.retailer}|{self.sku or self.product_name.strip().lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def utc(self) -> datetime:
        return self.drop_datetime.astimezone(timezone.utc)
