"""Shared schema. Lock this before anything else depends on it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone


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
