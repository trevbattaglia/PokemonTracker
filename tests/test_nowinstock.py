"""NowInStock ingest, against a REAL captured fixture.

Unlike tests/fixtures/bestbuy_search.json (synthetic, unusable without a key),
this one is a genuine capture from 2026-07-14. When NowInStock changes markup,
these fail -- which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pkmn_drops.relay.ingest import nowinstock
from pkmn_drops.relay.ingest.nowinstock import NowInStockError, parse

FIXTURE = Path(__file__).parent / "fixtures" / "nowinstock_pokemoncards.html"


@pytest.fixture(scope="module")
def html() -> str:
    # Honestly UTF-8 -- declared in both the meta tag and Content-Type header.
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def result(html):
    return parse(html)


@pytest.fixture(scope="module")
def products(result):
    return result.products


def test_parses_the_whole_table(products):
    assert len(products) == 226


def test_no_unknown_statuses_in_the_capture(result):
    """If this trips, NowInStock introduced a stock status we don't understand
    -- which decides whether an alert is real."""
    assert result.skipped == []


def test_accented_characters_survive(html):
    assert "Pokémon" in html


# --- the stock signal -----------------------------------------------------


def test_in_stock_is_buyable(products):
    row = next(p for p in products if p.raw_status == "In Stock")
    assert row.in_stock is True


def test_out_of_stock_is_not_buyable(products):
    row = next(p for p in products if p.raw_status == "Out of Stock")
    assert row.in_stock is False


def test_preorder_counts_as_buyable():
    """A live preorder IS the buying moment -- Pokemon Center sold out of Pitch
    Black at preorder, days before release."""
    out = parse(_row("Mega Charizard Tin : Amazon", "Preorder", "$44.99")).products
    assert out[0].in_stock is True


def test_preorder_keeps_its_real_status_in_raw_status():
    """It must never masquerade as 'In Stock' in the alert."""
    out = parse(_row("Mega Charizard Tin : Amazon", "Preorder", "$44.99")).products
    assert out[0].raw_status == "Preorder"


def test_stock_available_is_buyable():
    out = parse(_row("Thing : Amazon", "Stock Available", "$5.00")).products
    assert out[0].in_stock is True


def test_unknown_status_is_skipped_not_guessed():
    res = parse(
        _row("Good : Amazon", "In Stock", "$5.00")
        + _row("Weird : Target", "Backordered Maybe", "$9.99")
    )
    assert [p.name for p in res.products] == ["Good"]
    assert len(res.skipped) == 1
    assert "Backordered Maybe" in res.skipped[0]


# --- prices ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$54.99", 54.99),
        ("$1,160.99", 1160.99),
        ("-", None),
        ("See Site", None),
        ("", None),
    ],
)
def test_price_formats(text, expected):
    out = parse(_row("X : Amazon", "In Stock", text)).products
    assert out[0].price == expected


def test_unknown_price_is_none_not_zero():
    """0.0 would satisfy every max_price rule and alert on scalper listings;
    None correctly fails 'prove it's under budget'."""
    out = parse(_row("X : Amazon", "In Stock", "See Site")).products
    assert out[0].price is None


# --- identity -------------------------------------------------------------


def test_sku_is_stable_across_price_and_stock_changes():
    """A shifting sku would look like a brand-new product on every restock."""
    a = parse(_row("Pitch Black ETB : Target", "Out of Stock", "$49.99")).products[0]
    b = parse(_row("Pitch Black ETB : Target", "In Stock", "$59.99")).products[0]
    assert a.sku == b.sku


def test_same_product_at_different_retailers_gets_different_skus():
    a = parse(_row("Pitch Black ETB : Target", "In Stock", "$49.99")).products[0]
    b = parse(_row("Pitch Black ETB : Amazon", "In Stock", "$49.99")).products[0]
    assert a.sku != b.sku


def test_retailer_names_are_normalised(products):
    assert {p.retailer for p in products} <= {
        "amazon", "target", "walmart", "best_buy", "sams_club", "costco", "gamestop",
    }


def test_product_name_excludes_the_retailer_suffix(products):
    assert all(not p.name.endswith(": Amazon") for p in products)


def test_aggregate_pseudo_row_is_dropped(products):
    # NowInStock lists "Ebay : All Models", which isn't a purchasable product.
    assert all(p.retailer != "all_models" for p in products)


# --- links ----------------------------------------------------------------


def test_affiliate_links_are_passed_through_not_stripped(products):
    """They do the monitoring we get for free; keeping their commission is the
    polite way to repay that."""
    hosts = {p.url.split("/")[2] for p in products if p.url.startswith("http")}
    assert any("mavely" in h or "skimresources" in h for h in hosts)


def test_every_product_has_a_tappable_url(products):
    assert all(p.url.startswith("https://") for p in products)


# --- failure modes --------------------------------------------------------


def test_empty_page_fails_loudly():
    with pytest.raises(NowInStockError, match="0 products"):
        parse("<html><table></table></html>")


def test_all_rows_unknown_status_fails_loudly():
    with pytest.raises(NowInStockError, match="0 products"):
        parse(_row("X : Amazon", "Quantum Superposition", "$1.00"))


def _row(label: str, status: str, price: str) -> str:
    return (
        "<table><tr>"
        f'<td><a href="https://mavely.app.link/e/x">{label}</a></td>'
        f"<td>{status}</td><td>{price}</td><td>Jul 14 26 - 1:00 PM</td>"
        "</tr></table>"
    )
