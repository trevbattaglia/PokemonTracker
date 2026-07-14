"""Entrypoints for the two crons.

    python -m pkmn_drops.cli scrape    # daily: find drops, digest new ones
    python -m pkmn_drops.cli remind    # frequent: ping drops starting soon
    python -m pkmn_drops.cli upcoming  # local: what's on the books
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone

from . import store
from .config import LOCAL_TZ, REMINDER_LEAD_MINUTES
from .dropcal.parser import parse_serebii_english
from .dropcal.sources import fetch_serebii_english
from .relay import discord
from .relay import filter as wl_filter
from .relay.dedupe import dedupe
from .relay.ingest import bestbuy, nowinstock


def cmd_scrape(args) -> int:
    result = parse_serebii_english(fetch_serebii_english())
    drops = result.drops
    print(f"parsed {len(drops)} drops from serebii")

    if result.skipped:
        # Don't let a row we can't read decay silently into a missed drop.
        msg = "rows skipped by parser:\n" + "\n".join(result.skipped)
        print(msg, file=sys.stderr)
        if not args.dry_run:
            discord.send_error(msg)

    conn = store.connect()
    diff = store.upsert(conn, drops, commit=not args.dry_run)
    new, changed = diff["new"], diff["changed"]
    print(f"new={len(new)} changed={len(changed)}")

    # On a first run every drop is "new" -- don't dump the entire back catalogue
    # into Discord. Only announce drops that haven't happened yet.
    now = datetime.now(timezone.utc)
    keys = {d.key for d in new + changed if d.utc > now}
    rows = [r for r in store.upcoming(conn, limit=50) if r["key"] in keys]

    if args.dry_run:
        print(f"  {len(rows)} would be posted (past drops filtered out):")
        for r in rows:
            print(f"    {r['drop_datetime'][:10]}  {r['product_name']}")
        conn.rollback()  # leave no trace; see store.upsert(commit=...)
        return 0

    if rows:
        discord.send_digest(rows, title="New / rescheduled drops")
    return 0


def cmd_remind(args) -> int:
    conn = store.connect()
    due = store.due_for_reminder(conn, REMINDER_LEAD_MINUTES)
    print(f"{len(due)} reminder(s) due")

    if args.dry_run:
        for row, stage in due:
            print(f"  would send [{stage}]: {row['product_name']} @ {row['drop_datetime']}")
        return 0

    # Mark each stage sent immediately after it lands, not in one batch at the
    # end: if the run dies partway, the delivered pings must not re-fire.
    for row, stage in due:
        discord.send_reminder(row, stage)
        store.mark_sent(conn, [(row["key"], stage)])
    return 0


def cmd_set_time(args) -> int:
    """Pin a real drop time so the drop earns a true T-minus ping.

    Serebii only publishes dates, so this is the only way to get a genuine
    "30 minutes before" for a drop whose time you've learned elsewhere.
    """
    conn = store.connect()
    matches = store.find(conn, args.name)
    if not matches:
        print(f"no drop matching {args.name!r}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"{args.name!r} is ambiguous:", file=sys.stderr)
        for m in matches:
            print(f"  {m['drop_datetime'][:10]}  {m['product_name']}", file=sys.stderr)
        return 1

    row = matches[0]
    try:
        naive = datetime.strptime(args.when, "%Y-%m-%d %H:%M")
    except ValueError:
        print(f"could not parse {args.when!r}; expected 'YYYY-MM-DD HH:MM'",
              file=sys.stderr)
        return 1

    when = naive.replace(tzinfo=LOCAL_TZ)
    store.set_drop_time(conn, row["key"], when)
    print(f"{row['product_name']} pinned to {when:%Y-%m-%d %H:%M %Z}")
    print(f"  -> will ping ~{REMINDER_LEAD_MINUTES}min before, and the day before")
    return 0


def cmd_relay(args) -> int:
    """Phase 2: ingest -> normalize -> dedupe -> watchlist filter -> Discord."""
    watchlist = wl_filter.load()
    conn = store.connect()

    # NowInStock is the primary source: it already aggregates Amazon, Target,
    # Walmart and Best Buy, and every direct-retailer path is walled off (see
    # relay/ingest/nowinstock.py). Best Buy's own API is strictly better data
    # when available, so it layers on top when a key exists -- dedupe collapses
    # the overlap, which is exactly what it's for.
    result = nowinstock.ingest()
    raw = list(result.products)
    print(f"ingested {len(raw)} products from nowinstock")

    if result.skipped:
        # An unrecognised stock status decides whether an alert is real, so it
        # must never pass silently.
        msg = "nowinstock rows skipped:\n" + "\n".join(result.skipped[:20])
        print(msg, file=sys.stderr)
        if not args.dry_run:
            discord.send_error(msg)

    if os.environ.get("BESTBUY_API_KEY", "").strip():
        bb = bestbuy.ingest(watchlist.search_terms())
        print(f"  + {len(bb)} from the best buy API")
        raw.extend(bb)

    deduped = dedupe(raw, seen_at=datetime.now(timezone.utc))
    matched = [p for p in deduped if watchlist.matches(p)]
    print(f"  {len(deduped)} after dedupe, {len(matched)} match the watchlist")

    if not matched:
        # Nothing matching at all means the watchlist and the catalogue have
        # drifted apart. Fail loudly rather than look healthy while silent.
        raise RuntimeError(
            "no products matched the watchlist -- terms may be stale or the "
            "source's markup changed"
        )

    if args.dry_run:
        restocks = store.upsert_products(conn, matched, commit=False)
        for p in matched:
            mark = "IN STOCK" if p.in_stock else "sold out"
            price = f"${p.price:.2f}" if p.price is not None else "?"
            print(f"    [{mark:8}] {price:>8}  {p.name[:58]}")
        print(f"  would alert on {len(restocks)} restock(s)")
        conn.rollback()
        return 0

    restocks = store.upsert_products(conn, matched)
    print(f"  {len(restocks)} restock(s) to alert")
    discord.send_restocks(restocks)
    return 0


def cmd_status_vocab(args) -> int:
    """Report the retailer status strings we've actually observed.

    Neither source publishes its vocabulary, so this is how we learn it from
    real data rather than guessing -- and how a new status shows up before it
    silently costs a drop.
    """
    conn = store.connect()
    rows = store.status_vocabulary(conn)
    if not rows:
        print("no products recorded yet -- run `relay` first")
        return 0
    for label, n in rows:
        print(f"  {n:4}x  {label}")
    return 0


def cmd_upcoming(args) -> int:
    conn = store.connect()
    rows = store.upcoming(conn, limit=args.limit)
    if not rows:
        print("nothing upcoming -- run `scrape` first")
        return 0
    for r in rows:
        when = datetime.fromisoformat(r["drop_datetime"])
        tba = "" if r["time_confirmed"] else "  (time TBA)"
        print(f"{when.date()}  {r['product_name']:<28}{tba}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pkmn_drops")
    p.add_argument("--dry-run", action="store_true", help="print instead of posting")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scrape").set_defaults(fn=cmd_scrape)
    sub.add_parser("remind").set_defaults(fn=cmd_remind)

    up = sub.add_parser("upcoming")
    up.add_argument("--limit", type=int, default=10)
    up.set_defaults(fn=cmd_upcoming)

    sub.add_parser("relay", help="check watchlisted products for restocks").set_defaults(fn=cmd_relay)
    sub.add_parser(
        "status-vocab", help="observed Best Buy `orderable` values"
    ).set_defaults(fn=cmd_status_vocab)

    st = sub.add_parser(
        "set-time", help="pin a known drop time, e.g. set-time 'Pitch Black' '2026-07-17 09:00'"
    )
    st.add_argument("name", help="substring of the product name")
    st.add_argument("when", help="local time as 'YYYY-MM-DD HH:MM'")
    st.set_defaults(fn=cmd_set_time)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run:
            try:
                discord.send_error(tb)
            except Exception:
                pass  # never mask the original failure
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
