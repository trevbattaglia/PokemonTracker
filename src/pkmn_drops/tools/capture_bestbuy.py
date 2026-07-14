"""Capture a real Best Buy API response as a test fixture.

The committed fixture is synthetic -- built from the published schema, because
getting a key requires creating an account. That violates the project's own
rule that fixtures be real captures, so it is a placeholder.

Once BESTBUY_API_KEY is set:

    python -m pkmn_drops.tools.capture_bestbuy > tests/fixtures/bestbuy_search.json

Then run `pkmn-drops status-vocab` after a relay run to learn what values
Best Buy's undocumented `orderable` field actually takes.
"""

from __future__ import annotations

import json
import sys

from ..relay.ingest import bestbuy


def main() -> int:
    payload = bestbuy.fetch("Elite Trainer Box")
    payload["_fixture_provenance"] = (
        "REAL capture from api.bestbuy.com via pkmn_drops.tools.capture_bestbuy"
    )
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    print()

    products = payload.get("products", [])
    statuses = sorted({str(p.get("orderable")) for p in products})
    print(
        f"\ncaptured {len(products)} products; observed orderable values: {statuses}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
