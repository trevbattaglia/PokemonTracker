"""Collapse the same restock reported by multiple sources.

Only one ingest source exists today (Best Buy), so this is close to a no-op --
but it's the seam that stops the second source from tripling your notifications
on day one. The same restock will hit from three feeds within seconds.
"""

from __future__ import annotations

from datetime import datetime

from ..models import Product

BUCKET_SECONDS = 300  # ~5min, per the design doc


def dedupe(products: list[Product], *, seen_at: datetime) -> list[Product]:
    """Keep the first sighting per (retailer, sku, ~5min bucket).

    Ordering is preserved so the winner is whichever source reported first --
    which is the one that would have pinged you first anyway.
    """
    bucket = int(seen_at.timestamp()) // BUCKET_SECONDS
    seen: set[tuple[str, str, int]] = set()
    out: list[Product] = []

    for p in products:
        k = (p.retailer, p.sku, bucket)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)

    return out
