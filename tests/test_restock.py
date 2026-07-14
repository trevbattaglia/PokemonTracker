"""Restock detection and dedupe.

The core rule: alert on the *transition* into stock, never on the state of
being in stock. Getting this wrong means either a ping every 15 minutes for a
week, or silence through the one restock you cared about.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pkmn_drops import store
from pkmn_drops.models import Product
from pkmn_drops.relay.dedupe import dedupe


def product(sku="6577554", *, in_stock, name="Pitch Black Elite Trainer Box",
            retailer="best_buy", price=49.99, source="bestbuy_api:test") -> Product:
    return Product(
        sku=sku,
        name=name,
        retailer=retailer,
        in_stock=in_stock,
        url=f"https://www.bestbuy.com/site/{sku}.p",
        price=price,
        source=source,
    )


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "t.db")
    yield c
    c.close()


def seed(conn, *products):
    """First contact with a retailer seeds silently; do that explicitly so the
    tests below are about transitions, not about seeding."""
    store.upsert_products(conn, list(products) or [product(in_stock=False)])


# --- the seeding rule -----------------------------------------------------


def test_first_ever_run_does_not_alert_on_the_whole_catalogue(conn):
    """Otherwise run one pings every in-stock item at Best Buy at once."""
    restocks = store.upsert_products(
        conn,
        [product("1", in_stock=True), product("2", in_stock=True)],
    )
    assert restocks == []


def test_seeding_still_records_state(conn):
    store.upsert_products(conn, [product("1", in_stock=True)])
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


# --- transitions ----------------------------------------------------------


def test_out_of_stock_to_in_stock_alerts(conn):
    seed(conn, product(in_stock=False))
    restocks = store.upsert_products(conn, [product(in_stock=True)])
    assert [p.sku for p in restocks] == ["6577554"]


def test_staying_in_stock_does_not_re_alert(conn):
    """The cron runs every 15min. Without this, one restock pings forever."""
    seed(conn, product(in_stock=False))
    assert len(store.upsert_products(conn, [product(in_stock=True)])) == 1
    assert store.upsert_products(conn, [product(in_stock=True)]) == []
    assert store.upsert_products(conn, [product(in_stock=True)]) == []


def test_staying_out_of_stock_does_not_alert(conn):
    seed(conn, product(in_stock=False))
    assert store.upsert_products(conn, [product(in_stock=False)]) == []


def test_going_out_of_stock_does_not_alert(conn):
    seed(conn, product(in_stock=False))
    store.upsert_products(conn, [product(in_stock=True)])
    assert store.upsert_products(conn, [product(in_stock=False)]) == []


def test_restock_after_selling_out_alerts_again(conn):
    seed(conn, product(in_stock=False))
    store.upsert_products(conn, [product(in_stock=True)])
    store.upsert_products(conn, [product(in_stock=False)])
    assert len(store.upsert_products(conn, [product(in_stock=True)])) == 1


def test_new_sku_in_stock_alerts_once_the_retailer_is_known(conn):
    """A product that appears already buyable is news -- but only after the
    seeding run, or the first run alerts on everything."""
    seed(conn, product("1", in_stock=False))
    restocks = store.upsert_products(conn, [product("2", in_stock=True)])
    assert [p.sku for p in restocks] == ["2"]


def test_price_change_is_recorded_not_alerted(conn):
    seed(conn, product(in_stock=True, price=49.99))
    assert store.upsert_products(conn, [product(in_stock=True, price=39.99)]) == []
    row = conn.execute("SELECT price FROM products").fetchone()
    assert row["price"] == 39.99


def test_same_sku_at_different_retailers_is_tracked_separately(conn):
    seed(conn, product("1", in_stock=False, retailer="best_buy"))
    # Different retailer -> its own first run -> seeded silently.
    assert store.upsert_products(conn, [product("1", in_stock=True, retailer="target")]) == []
    rows = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert rows == 2


# --- undocumented status vocabulary --------------------------------------


def test_status_vocabulary_reports_observed_orderable_values(conn):
    store.upsert_products(
        conn,
        [
            Product(sku="1", name="a", retailer="best_buy", in_stock=True,
                    url="u", source="s", raw_status="Available"),
            Product(sku="2", name="b", retailer="best_buy", in_stock=False,
                    url="u", source="s", raw_status="ComingSoon"),
        ],
    )
    vocab = dict(store.status_vocabulary(conn))
    assert "Available (in_stock=1)" in vocab
    assert "ComingSoon (in_stock=0)" in vocab


# --- dedupe ---------------------------------------------------------------

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def test_dedupe_collapses_same_sku_within_a_bucket():
    dupes = [product(in_stock=True, source="feed_a"),
             product(in_stock=True, source="feed_b")]
    assert len(dedupe(dupes, seen_at=NOW)) == 1


def test_dedupe_keeps_the_first_reporter():
    dupes = [product(in_stock=True, source="feed_a"),
             product(in_stock=True, source="feed_b")]
    assert dedupe(dupes, seen_at=NOW)[0].source == "feed_a"


def test_dedupe_keeps_distinct_skus():
    items = [product("1", in_stock=True), product("2", in_stock=True)]
    assert len(dedupe(items, seen_at=NOW)) == 2


def test_dedupe_keeps_same_sku_at_different_retailers():
    items = [product("1", in_stock=True, retailer="best_buy"),
             product("1", in_stock=True, retailer="target")]
    assert len(dedupe(items, seen_at=NOW)) == 2


def test_dedupe_does_not_suppress_a_later_bucket():
    """A real restock 10 minutes later is a separate event, not a duplicate."""
    first = dedupe([product(in_stock=True)], seen_at=NOW)
    later = dedupe([product(in_stock=True)], seen_at=NOW + timedelta(minutes=10))
    assert len(first) == 1 and len(later) == 1
