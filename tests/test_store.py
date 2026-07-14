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


def test_reschedule_clears_sent_so_it_pings_again(conn):
    d = make_drop()
    store.upsert(conn, [d])
    store.mark_sent(conn, [(d.key, store.MORNING_OF)])
    assert conn.execute("SELECT COUNT(*) FROM sent").fetchone()[0] == 1

    store.upsert(conn, [make_drop(when=datetime(2026, 11, 20, tzinfo=timezone.utc))])
    assert conn.execute("SELECT COUNT(*) FROM sent").fetchone()[0] == 0


# --- timed drops: classic T-minus window ---------------------------------


def timed(when) -> Drop:
    return Drop(
        product_name="Pitch Black ETB",
        retailer="pokemon_center",
        drop_datetime=when,
        time_confirmed=True,
        source="test",
    )


def at_local(y, m, d, hour, minute=0) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def stages(due) -> list[str]:
    return [stage for _row, stage in due]


def test_reminder_window_includes_imminent_drop(conn):
    soon = datetime.now(timezone.utc) + timedelta(minutes=20)
    store.upsert(conn, [timed(soon)])
    assert store.STARTING_SOON in stages(store.due_for_reminder(conn, 40))


def test_reminder_window_excludes_distant_drop(conn):
    later = datetime.now(timezone.utc) + timedelta(days=30)
    store.upsert(conn, [timed(later)])
    assert store.due_for_reminder(conn, 40) == []


def test_reminder_window_excludes_past_drop(conn):
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    store.upsert(conn, [timed(past)])
    assert store.due_for_reminder(conn, 40) == []


def test_sent_stage_does_not_ping_twice(conn):
    soon = datetime.now(timezone.utc) + timedelta(minutes=20)
    d = timed(soon)
    store.upsert(conn, [d])
    assert len(store.due_for_reminder(conn, 40)) == 1
    store.mark_sent(conn, [(d.key, store.STARTING_SOON)])
    assert store.due_for_reminder(conn, 40) == []


# --- day-before heads up --------------------------------------------------

DROP_DAY = datetime(2026, 11, 6, tzinfo=LOCAL_TZ)


def test_day_before_heads_up_fires(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    due = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 9))
    assert stages(due) == [store.DAY_BEFORE]


def test_day_before_does_not_fire_two_days_out(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    assert store.due_for_reminder(conn, 40, now=at_local(2026, 11, 4, 9)) == []


def test_day_before_does_not_fire_before_morning_hour(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    assert store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 3)) == []


def test_day_before_fires_once_not_every_15min(conn):
    """The cron runs 4x/hour; the day-before ping must not run 4x/hour too."""
    d = make_drop(when=DROP_DAY)
    store.upsert(conn, [d])
    due = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 9))
    assert stages(due) == [store.DAY_BEFORE]
    store.mark_sent(conn, [(d.key, store.DAY_BEFORE)])
    assert store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 9, 15)) == []


def test_day_before_and_morning_of_are_separate_pings(conn):
    d = make_drop(when=DROP_DAY)
    store.upsert(conn, [d])

    day_before = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 9))
    assert stages(day_before) == [store.DAY_BEFORE]
    store.mark_sent(conn, [(d.key, store.DAY_BEFORE)])

    # Sending the heads up must not consume the day-of ping.
    morning = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 6, 9))
    assert stages(morning) == [store.MORNING_OF]


# --- date-only drops: morning-of, never 11pm the night before -------------


def test_date_only_drop_pings_on_the_morning_of(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    due = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 6, 9))
    assert stages(due) == [store.MORNING_OF]


def test_date_only_drop_does_not_ping_the_night_before(conn):
    """Regression: anchored to local midnight, a T-40min window would fire at
    23:20 the previous night. That is the wrong day and a useless ping."""
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    due = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 5, 23))
    assert store.STARTING_SOON not in stages(due)
    assert store.MORNING_OF not in stages(due)


def test_date_only_drop_does_not_ping_before_morning_hour(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    assert store.due_for_reminder(conn, 40, now=at_local(2026, 11, 6, 3)) == []


def test_date_only_drop_does_not_ping_the_day_after(conn):
    store.upsert(conn, [make_drop(when=DROP_DAY)])
    assert store.due_for_reminder(conn, 40, now=at_local(2026, 11, 7, 9)) == []


# --- pinning a real drop time --------------------------------------------


def test_set_drop_time_enables_a_true_t_minus_ping(conn):
    d = make_drop(when=DROP_DAY)  # date-only: no meaningful T-minus
    store.upsert(conn, [d])

    store.set_drop_time(conn, d.key, datetime(2026, 11, 6, 10, 0, tzinfo=LOCAL_TZ))

    # 30 minutes out -> starting_soon now fires, which it never could before.
    due = store.due_for_reminder(conn, 40, now=at_local(2026, 11, 6, 9, 30))
    assert stages(due) == [store.STARTING_SOON]


def test_pinned_time_survives_the_daily_scrape(conn):
    """Regression: the scraper re-reports Serebii's date-only midnight every
    day. Without the override flag it would overwrite the pinned time, look
    like a reschedule, and re-ping."""
    d = make_drop(when=DROP_DAY)
    store.upsert(conn, [d])
    store.set_drop_time(conn, d.key, datetime(2026, 11, 6, 10, 0, tzinfo=LOCAL_TZ))

    result = store.upsert(conn, [make_drop(when=DROP_DAY)])  # scrape runs again

    assert result["changed"] == []  # not a real reschedule
    row = conn.execute("SELECT * FROM drops WHERE key=?", (d.key,)).fetchone()
    assert row["time_confirmed"] == 1
    assert datetime.fromisoformat(row["drop_datetime"]).astimezone(
        LOCAL_TZ
    ).hour == 10


def test_reschedule_clears_sent_stages(conn):
    d = make_drop(when=DROP_DAY)
    store.upsert(conn, [d])
    store.mark_sent(conn, [(d.key, store.DAY_BEFORE)])

    store.upsert(conn, [make_drop(when=datetime(2026, 12, 1, tzinfo=LOCAL_TZ))])

    assert conn.execute("SELECT COUNT(*) FROM sent").fetchone()[0] == 0


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
