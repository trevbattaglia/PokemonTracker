"""Diff behaviour: only act on new or changed drops."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pkmn_drops import store
from pkmn_drops.config import LOCAL_TZ
from pkmn_drops.models import Drop


def make_drop(name="Delta Reign", when=None, **kw) -> Drop:
    return Drop(
        product_name=name,
        retailer="tcg_release",
        drop_datetime=when or datetime(2026, 11, 6, tzinfo=timezone.utc),
        time_confirmed=False,
        source="test",
        **kw,
    )


@pytest.fixture
def conn(tmp_path):
    c = store.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_drop(when=datetime(2026, 11, 6))


def test_first_insert_is_new(conn):
    result = store.upsert(conn, [make_drop()])
    assert len(result["new"]) == 1
    assert result["changed"] == []


def test_reinsert_is_neither_new_nor_changed(conn):
    store.upsert(conn, [make_drop()])
    result = store.upsert(conn, [make_drop()])
    assert result["new"] == []
    assert result["changed"] == []


def test_reschedule_is_changed_not_new(conn):
    store.upsert(conn, [make_drop()])
    moved = make_drop(when=datetime(2026, 11, 20, tzinfo=timezone.utc))
    result = store.upsert(conn, [moved])
    assert result["new"] == []
    assert len(result["changed"]) == 1


def test_reschedule_clears_notified_so_it_pings_again(conn):
    d = make_drop()
    store.upsert(conn, [d])
    store.mark_notified(conn, [d.key])
    assert conn.execute("SELECT notified_at FROM drops").fetchone()[0] is not None

    store.upsert(conn, [make_drop(when=datetime(2026, 11, 20, tzinfo=timezone.utc))])
    assert conn.execute("SELECT notified_at FROM drops").fetchone()[0] is None


# --- timed drops: classic T-minus window ---------------------------------


def timed(when) -> Drop:
    return Drop(
        product_name="Pitch Black ETB",
        retailer="pokemon_center",
        drop_datetime=when,
        time_confirmed=True,
        source="test",
    )


def test_reminder_window_includes_imminent_drop(conn):
    soon = datetime.now(timezone.utc) + timedelta(minutes=20)
    store.upsert(conn, [timed(soon)])
    assert len(store.due_for_reminder(conn, 45)) == 1


def test_reminder_window_excludes_distant_drop(conn):
    later = datetime.now(timezone.utc) + timedelta(days=30)
    store.upsert(conn, [timed(later)])
    assert store.due_for_reminder(conn, 45) == []


def test_reminder_window_excludes_past_drop(conn):
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    store.upsert(conn, [timed(past)])
    assert store.due_for_reminder(conn, 45) == []


def test_notified_drop_does_not_ping_twice(conn):
    soon = datetime.now(timezone.utc) + timedelta(minutes=20)
    d = timed(soon)
    store.upsert(conn, [d])
    assert len(store.due_for_reminder(conn, 45)) == 1
    store.mark_notified(conn, [d.key])
    assert store.due_for_reminder(conn, 45) == []


# --- date-only drops: morning-of, never 11pm the night before -------------


def at_local(y, m, d, hour) -> datetime:
    return datetime(y, m, d, hour, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def test_date_only_drop_pings_on_the_morning_of(conn):
    # Drop lands 2026-11-06 (date only). It is now 9am local that day.
    store.upsert(conn, [make_drop(when=datetime(2026, 11, 6, tzinfo=LOCAL_TZ))])
    due = store.due_for_reminder(conn, 45, now=at_local(2026, 11, 6, 9))
    assert len(due) == 1


def test_date_only_drop_does_not_ping_the_night_before(conn):
    """Regression: anchored to local midnight, a T-45min window would fire at
    23:15 the previous night. That is the wrong day and a useless ping."""
    store.upsert(conn, [make_drop(when=datetime(2026, 11, 6, tzinfo=LOCAL_TZ))])
    due = store.due_for_reminder(conn, 45, now=at_local(2026, 11, 5, 23))
    assert due == []


def test_date_only_drop_does_not_ping_before_morning_hour(conn):
    store.upsert(conn, [make_drop(when=datetime(2026, 11, 6, tzinfo=LOCAL_TZ))])
    due = store.due_for_reminder(conn, 45, now=at_local(2026, 11, 6, 3))
    assert due == []


def test_date_only_drop_does_not_ping_the_day_after(conn):
    store.upsert(conn, [make_drop(when=datetime(2026, 11, 6, tzinfo=LOCAL_TZ))])
    due = store.due_for_reminder(conn, 45, now=at_local(2026, 11, 7, 9))
    assert due == []


def test_different_products_get_different_keys(conn):
    result = store.upsert(conn, [make_drop("Delta Reign"), make_drop("Pitch Black")])
    assert len(result["new"]) == 2


def test_uncommitted_upsert_can_be_rolled_back(conn):
    """--dry-run must not consume drops. If it committed, the subsequent real
    run would see new=0 and announce nothing -- a silent missed drop."""
    store.upsert(conn, [make_drop()], commit=False)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM drops").fetchone()[0] == 0

    # And the real run afterwards still sees it as new.
    assert len(store.upsert(conn, [make_drop()])["new"]) == 1
