"""Best Buy API client.

CAVEAT: tests/fixtures/bestbuy_search.json is SYNTHETIC -- built from the
published schema, not captured, because getting a key requires creating an
account. It pins our *contract expectations*, not observed reality. Replace it
via `python -m pkmn_drops.tools.capture_bestbuy` once a key exists; if the real
response differs, these tests are where that surfaces.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import responses

from pkmn_drops.relay.ingest import bestbuy

FIXTURE = Path(__file__).parent / "fixtures" / "bestbuy_search.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def products(payload):
    return bestbuy.parse(payload, term="Elite Trainer Box")


def test_fixture_is_labelled_synthetic(payload):
    """Guard against quietly trusting made-up data. When this fixture is
    replaced with a real capture, update this test to match."""
    assert "SYNTHETIC" in payload["_fixture_provenance"]


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BESTBUY_API_KEY", raising=False)
    with pytest.raises(bestbuy.BestBuyError, match="developer.bestbuy.com"):
        bestbuy.api_key()


# --- parsing --------------------------------------------------------------


def test_parses_every_product(products):
    assert len(products) == 4


def test_maps_online_availability_to_in_stock(products):
    by_sku = {p.sku: p for p in products}
    assert by_sku["6577554"].in_stock is False  # ComingSoon
    assert by_sku["6577555"].in_stock is True  # Available


def test_records_orderable_without_branching_on_it(products):
    """`orderable`'s vocabulary is undocumented, so it is captured for later
    study but must never decide in_stock."""
    by_sku = {p.sku: p for p in products}
    assert by_sku["6577554"].raw_status == "ComingSoon"
    # in_stock came from onlineAvailability, not from the status string.
    assert by_sku["6577554"].in_stock is False


def test_prefers_sale_price(products):
    plush = next(p for p in products if "Plush" in p.name)
    assert plush.price == 34.99  # salePrice, not the 39.99 regularPrice


def test_keeps_the_real_product_url(products):
    p = next(p for p in products if p.sku == "6577554")
    assert p.url.startswith("https://www.bestbuy.com/site/")
    assert "6577554" in p.url


def test_sku_is_a_string_not_an_int(products):
    # The API returns ints; the DB key is text. Mixing them silently breaks
    # the primary key lookup.
    assert all(isinstance(p.sku, str) for p in products)


def test_source_records_which_term_found_it(products):
    assert all(p.source == "bestbuy_api:Elite Trainer Box" for p in products)


def test_products_without_sku_or_name_are_skipped():
    out = bestbuy.parse(
        {"products": [{"name": "no sku"}, {"sku": 1}, {"sku": 2, "name": "ok"}]},
        term="t",
    )
    assert [p.sku for p in out] == ["2"]


def test_null_price_is_preserved_as_none():
    out = bestbuy.parse(
        {"products": [{"sku": 1, "name": "x", "onlineAvailability": True}]}, term="t"
    )
    assert out[0].price is None


def test_unexpected_payload_shape_fails_loudly():
    with pytest.raises(bestbuy.BestBuyError, match="unexpected payload shape"):
        bestbuy.parse({"error": "nope"}, term="t")


# --- HTTP behaviour -------------------------------------------------------


def test_search_url_puts_term_inside_the_parens():
    url = bestbuy._search_url("Elite Trainer Box")
    assert url.startswith("https://api.bestbuy.com/v1/products((search=")
    assert unquote(url).endswith("((search=Elite Trainer Box))")


@responses.activate
def test_fetch_sends_key_and_field_selection(payload):
    responses.add(
        responses.GET,
        bestbuy._search_url("Elite Trainer Box"),
        json=payload,
        status=200,
    )
    bestbuy.fetch("Elite Trainer Box", key="TESTKEY")

    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["apiKey"] == ["TESTKEY"]
    assert q["format"] == ["json"]
    assert "onlineAvailability" in q["show"][0]


@responses.activate
def test_bad_key_gives_an_actionable_error():
    responses.add(responses.GET, bestbuy._search_url("x"), status=403, json={})
    with pytest.raises(bestbuy.BestBuyError, match="rejected the API key"):
        bestbuy.fetch("x", key="BAD")


@responses.activate
def test_rate_limit_says_back_off():
    """The doc is explicit: if a source pushes back, back off -- don't escalate."""
    responses.add(responses.GET, bestbuy._search_url("x"), status=429, json={})
    with pytest.raises(bestbuy.BestBuyError, match="back off"):
        bestbuy.fetch("x", key="K")


@responses.activate
def test_ingest_queries_once_per_term(payload):
    for term in ("Elite Trainer Box", "Booster Bundle"):
        responses.add(responses.GET, bestbuy._search_url(term), json=payload, status=200)

    out = bestbuy.ingest(["Elite Trainer Box", "Booster Bundle"], key="K")
    assert len(responses.calls) == 2
    assert len(out) == 8
