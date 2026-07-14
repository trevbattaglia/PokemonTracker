"""Watchlist filter. Per the doc: test the exclusions especially -- a false
negative here means you miss a drop."""

from __future__ import annotations

import pytest

from pkmn_drops.models import Product
from pkmn_drops.relay.filter import Rule, Watchlist, WatchlistError, load


def product(name: str, *, retailer="best_buy", price=49.99) -> Product:
    return Product(
        sku="6577554",
        name=name,
        retailer=retailer,
        in_stock=True,
        url="https://www.bestbuy.com/site/x.p",
        price=price,
        source="test",
    )


@pytest.fixture
def wl() -> Watchlist:
    return Watchlist(
        rules=(
            Rule("Elite Trainer Box", retailers=("best_buy",), max_price=75.00),
            Rule("Booster Bundle", retailers=("best_buy",), max_price=40.00),
        ),
        exclude=("plush", "pin collection", "figure"),
    )


def test_matches_a_watchlisted_product(wl):
    assert wl.matches(product("Pokémon TCG: Mega Evolution - Pitch Black Elite Trainer Box"))


def test_matching_is_case_insensitive(wl):
    assert wl.matches(product("pokemon tcg pitch black ELITE TRAINER BOX"))


def test_ignores_unwatched_product_type(wl):
    assert not wl.matches(product("Pokémon TCG: Pitch Black Single Booster Pack"))


# --- exclusions: the ones that matter ------------------------------------


def test_exclusion_beats_a_match(wl):
    # Matches "Elite Trainer Box" but is merch, not sealed product.
    assert not wl.matches(product("Pikachu Plush with Elite Trainer Box"))


def test_exclusion_is_case_insensitive(wl):
    assert not wl.matches(product("Elite Trainer Box + PLUSH bundle"))


def test_exclusion_applies_even_under_max_price(wl):
    assert not wl.matches(product("Elite Trainer Box Figure", price=9.99))


# --- price and retailer scoping ------------------------------------------


def test_over_max_price_is_filtered(wl):
    assert not wl.matches(product("Pitch Black Elite Trainer Box", price=120.00))


def test_at_max_price_is_included(wl):
    assert wl.matches(product("Pitch Black Elite Trainer Box", price=75.00))


def test_unknown_price_does_not_pass_a_max_price_rule(wl):
    """If we can't prove it's under budget, don't claim it is -- otherwise a
    scalper-priced listing with a null price sails through."""
    assert not wl.matches(product("Pitch Black Elite Trainer Box", price=None))


def test_wrong_retailer_is_filtered(wl):
    assert not wl.matches(product("Pitch Black Elite Trainer Box", retailer="walmart"))


def test_rule_without_retailers_matches_any_retailer():
    wl = Watchlist(rules=(Rule("Elite Trainer Box"),), exclude=())
    assert wl.matches(product("Elite Trainer Box", retailer="anywhere"))


def test_rule_without_max_price_allows_unknown_price():
    wl = Watchlist(rules=(Rule("Elite Trainer Box"),), exclude=())
    assert wl.matches(product("Elite Trainer Box", price=None))


def test_search_terms_drive_the_ingest(wl):
    assert wl.search_terms() == ["Elite Trainer Box", "Booster Bundle"]


# --- loading --------------------------------------------------------------


def test_loads_the_real_watchlist_file():
    wl = load()  # the committed watchlist.yaml must always be valid
    assert wl.rules
    assert "plush" in wl.exclude


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(WatchlistError, match="no watchlist at"):
        load(tmp_path / "nope.yaml")


def test_empty_watchlist_fails_loudly(tmp_path):
    """An empty watchlist matches nothing, so the relay would look healthy
    while alerting on nothing at all."""
    p = tmp_path / "w.yaml"
    p.write_text("watchlist: []\n", encoding="utf-8")
    with pytest.raises(WatchlistError, match="no-op"):
        load(p)


def test_entry_without_match_fails_loudly(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("watchlist:\n  - max_price: 60\n", encoding="utf-8")
    with pytest.raises(WatchlistError, match="missing 'match'"):
        load(p)
