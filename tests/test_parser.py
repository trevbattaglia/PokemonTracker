"""Fixture-backed parser tests. The fixture is real HTML pulled from serebii;
when they change their markup, these fail -- which is the point."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pkmn_drops.dropcal.parser import ParseError, parse_serebii_english

FIXTURE = Path(__file__).parent / "fixtures" / "serebii_english.html"


@pytest.fixture(scope="module")
def html() -> str:
    # cp1252, not utf-8 -- the page declares no charset.
    return FIXTURE.read_text(encoding="windows-1252")


@pytest.fixture(scope="module")
def result(html):
    return parse_serebii_english(html)


@pytest.fixture(scope="module")
def drops(result):
    return result.drops


def test_parses_every_row(drops):
    assert len(drops) == 128


def test_no_rows_skipped_on_current_fixture(result):
    # If this trips, serebii introduced a new date string we don't understand.
    assert result.skipped == []


def test_source_typo_februrary_is_handled(drops):
    # Serebii genuinely spells it "Februrary 14th 2007" on the EX Power Keepers row.
    pk = next(d for d in drops if d.product_name == "EX Power Keepers")
    assert pk.drop_datetime.date().isoformat() == "2007-02-14"


def test_one_bad_row_does_not_lose_the_good_rows():
    mixed = """<table><tr><td>Release Date</td></tr>
    <tr><td></td><td></td><td>Good Set</td><td>1</td><td>November 6th 2026</td></tr>
    <tr><td></td><td></td><td>Bad Set</td><td>1</td><td>Coming Soon</td></tr>
    </table>"""
    res = parse_serebii_english(mixed)
    assert [d.product_name for d in res.drops] == ["Good Set"]
    assert len(res.skipped) == 1
    assert "Bad Set" in res.skipped[0]


def test_known_future_set_is_present(drops):
    by_name = {d.product_name: d for d in drops}
    delta = by_name["Delta Reign"]
    assert delta.drop_datetime.astimezone(timezone.utc).date().isoformat() == "2026-11-06"
    assert delta.time_confirmed is False
    assert delta.product_url == "https://www.serebii.net/card/deltareign"
    assert delta.source == "serebii:english_sets"


def test_accented_characters_survive_decoding(html):
    # If encoding is mishandled this becomes "PokÃ©mon".
    assert "Pokémon" in html


def test_dates_are_timezone_aware(drops):
    assert all(d.drop_datetime.tzinfo is not None for d in drops)


def test_release_dates_are_all_date_only(drops):
    # Serebii publishes no times; anything else means the schema drifted.
    assert all(d.time_confirmed is False for d in drops)


def test_keys_are_unique(drops):
    keys = [d.key for d in drops]
    assert len(keys) == len(set(keys))


def test_empty_table_fails_loudly():
    # Silent scraper decay is the #1 failure mode -- assert we raise.
    with pytest.raises(ParseError, match="0 drops|markup changed"):
        parse_serebii_english("<html><table><tr><td>Release Date</td></tr></table></html>")


def test_missing_table_fails_loudly():
    with pytest.raises(ParseError, match="markup changed"):
        parse_serebii_english("<html><body>nothing here</body></html>")


def test_all_rows_unparseable_fails_loudly():
    bad = """<table><tr><td>Release Date</td></tr>
    <tr><td></td><td></td><td>Weird Set</td><td>99</td><td>Coming Soon</td></tr>
    </table>"""
    with pytest.raises(ParseError, match="0 drops"):
        parse_serebii_english(bad)
