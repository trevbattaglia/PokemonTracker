"""Buy links. These are constructed, never fetched -- the failure mode is a
silently malformed URL, so the shapes are pinned here.

The formats were verified by hand in a real browser against real searches.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

import pytest

from pkmn_drops.relay.buylinks import buy_field, buy_links


def links(name="Pitch Black") -> dict[str, str]:
    return dict(buy_links(name))


def test_covers_the_retailers_that_actually_stock_sealed():
    assert set(links()) == {
        "Pokémon Center",
        "Best Buy",
        "Target",
        "Walmart",
        "Amazon",
    }


def test_pokemon_center_uses_path_encoding_not_plus():
    """PC puts the term in the path. quote_plus there would emit a literal '+'
    and search for the wrong string."""
    url = links()["Pokémon Center"]
    assert url == "https://www.pokemoncenter.com/search/Pitch%20Black"
    assert "+" not in urlparse(url).path


def test_pokemon_center_query_is_not_padded_with_pokemon_tcg():
    # PC only sells Pokemon; the extra words needlessly narrow results.
    assert "Pokemon" not in unquote(urlparse(links()["Pokémon Center"]).path).replace(
        "Pitch Black", ""
    )


def test_other_retailers_scope_the_query_to_pokemon_tcg():
    # A bare "Pitch Black" on Amazon returns paint and movies.
    for label in ("Best Buy", "Target", "Walmart", "Amazon"):
        url = links()[label]
        term = next(iter(parse_qs(urlparse(url).query).values()))[0]
        assert term == "Pokemon TCG Pitch Black", label


@pytest.mark.parametrize(
    "label,host,param",
    [
        ("Best Buy", "www.bestbuy.com", "st"),
        ("Target", "www.target.com", "searchTerm"),
        ("Walmart", "www.walmart.com", "q"),
        ("Amazon", "www.amazon.com", "k"),
    ],
)
def test_verified_url_shapes(label, host, param):
    parsed = urlparse(links()[label])
    assert parsed.scheme == "https"
    assert parsed.netloc == host
    assert param in parse_qs(parsed.query)


def test_names_with_ampersands_are_encoded():
    """'Scarlet & Violet' must not inject a query param boundary."""
    url = links("Scarlet & Violet")["Target"]
    assert parse_qs(urlparse(url).query)["searchTerm"] == [
        "Pokemon TCG Scarlet & Violet"
    ]


def test_buy_field_renders_tappable_markdown():
    field = buy_field("Pitch Black")
    assert field["name"] == "Buy"
    assert field["value"].count("](") == 5
    assert "[Pokémon Center](https://www.pokemoncenter.com/search/" in field["value"]


def test_buy_field_fits_discord_field_value_limit():
    # Discord rejects embed field values over 1024 chars.
    assert len(buy_field("Mega Evolution Pitch Black Elite Trainer Box")["value"]) < 1024
