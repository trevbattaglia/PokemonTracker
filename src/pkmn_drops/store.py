"""SQLite state. Diff against this so we only act on new or changed drops."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH, LOCAL_TZ, MORNING_PING_HOUR
from .models import Drop

SCHEMA = """
CREATE TABLE IF NOT EXISTS drops (
    key            TEXT PRIMARY KEY,
    product_name   TEXT NOT NULL,
    set_name       TEXT,
    sku            TEXT,
    retailer       TEXT NOT NULL,
    drop_datetime  TEXT NOT NULL,   -- ISO 8601, UTC
    time_confirmed INTEGER NOT NULL,
    product_url    TEXT,
    msrp           REAL,
    source         TEXT NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    notified_at    TEXT             -- legacy; superseded by the sent table
);
CREATE INDEX IF NOT EXISTS idx_drops_when ON drops(drop_datetime);

-- One row per (drop, stage) actually delivered. A drop gets pinged more than
-- once (day before, then again close to the drop), so a single notified_at
-- column can't express "day_before sent, starting_soon still pending".
CREATE TABLE IF NOT EXISTS sent (
    drop_key TEXT NOT NULL,
    stage    TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (drop_key, stage)
);
"""

# Reminder stages, in the order a drop passes through them.
DAY_BEFORE = "day_before"
MORNING_OF = "morning_of"
STARTING_SOON = "starting_soon"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations. The DB is committed to the repo, so an existing
    file predates these columns and must be upgraded in place rather than
    recreated -- recreating would lose which reminders already fired."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(drops)")}

    if "time_override" not in cols:
        # Set when a human pins a real drop time (Serebii only has dates).
        # The daily scrape must not clobber it back to date-only midnight.
        conn.execute(
            "ALTER TABLE drops ADD COLUMN time_override INTEGER NOT NULL DEFAULT 0"
        )

    # Carry legacy notified_at forward so drops already pinged under the old
    # single-column scheme don't re-fire once as morning_of.
    if "notified_at" in cols:
        conn.execute(
            "INSERT OR IGNORE INTO sent (drop_key, stage, sent_at) "
            "SELECT key, ?, notified_at FROM drops WHERE notified_at IS NOT NULL",
            (MORNING_OF,),
        )
    conn.commit()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = Path(path or DB_PATH)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def upsert(
    conn: sqlite3.Connection, drops: list[Drop], *, commit: bool = True
) -> dict[str, list[Drop]]:
    """Insert/update drops. Returns {"new": [...], "changed": [...]}.

    "changed" means the drop_datetime moved -- a reschedule, which is the one
    change worth telling a human about.

    commit=False leaves the writes uncommitted so a caller can roll back; this
    is what makes --dry-run side-effect free. Without it a dry run would mark
    every drop as seen and the real run would then announce nothing.
    """
    new: list[Drop] = []
    changed: list[Drop] = []
    now = _now()

    for d in drops:
        when = d.utc.isoformat()
        row = conn.execute(
            "SELECT drop_datetime, time_override FROM drops WHERE key = ?", (d.key,)
        ).fetchone()

        if row is None:
            new.append(d)
            conn.execute(
                """INSERT INTO drops (key, product_name, set_name, sku, retailer,
                       drop_datetime, time_confirmed, product_url, msrp, source,
                       first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d.key, d.product_name, d.set_name, d.sku, d.retailer, when,
                 int(d.time_confirmed), d.product_url, d.msrp, d.source, now, now),
            )
        elif row["time_override"]:
            # A human pinned a real drop time. Serebii only knows the date, so
            # its midnight anchor is strictly worse information -- keep ours,
            # and don't report a reschedule we invented.
            conn.execute(
                "UPDATE drops SET last_seen=?, product_url=?, msrp=? WHERE key=?",
                (now, d.product_url, d.msrp, d.key),
            )
        elif row["drop_datetime"] != when:
            changed.append(d)
            # Reschedule: forget which stages fired so the new time re-pings.
            conn.execute(
                """UPDATE drops SET drop_datetime=?, time_confirmed=?, product_url=?,
                       msrp=?, source=?, last_seen=?, notified_at=NULL
                   WHERE key=?""",
                (when, int(d.time_confirmed), d.product_url, d.msrp, d.source,
                 now, d.key),
            )
            conn.execute("DELETE FROM sent WHERE drop_key=?", (d.key,))
        else:
            conn.execute(
                "UPDATE drops SET last_seen=?, product_url=?, msrp=? WHERE key=?",
                (now, d.product_url, d.msrp, d.key),
            )

    if commit:
        conn.commit()
    return {"new": new, "changed": changed}


def due_for_reminder(
    conn: sqlite3.Connection,
    lead_minutes: int,
    *,
    now: datetime | None = None,
) -> list[tuple[sqlite3.Row, str]]:
    """Un-sent (drop, stage) pairs that should be announced right now.

    Every drop gets a day-before heads up. What it gets after that depends on
    whether we know a real time:

    - time_confirmed -> STARTING_SOON, within `lead_minutes` of the drop.
    - date-only      -> MORNING_OF at MORNING_PING_HOUR. There is no timestamp
      to count back from, and the midnight anchor means a T-minus window would
      fire the previous night.
    """
    now = now or datetime.now(timezone.utc)
    horizon = now.timestamp() + lead_minutes * 60
    local_now = now.astimezone(LOCAL_TZ)
    today = local_now.date()

    already = {
        (r["drop_key"], r["stage"]) for r in conn.execute("SELECT * FROM sent")
    }

    due: list[tuple[sqlite3.Row, str]] = []
    for r in conn.execute("SELECT * FROM drops ORDER BY drop_datetime"):
        when = datetime.fromisoformat(r["drop_datetime"])
        local_when = when.astimezone(LOCAL_TZ)
        days_out = (local_when.date() - today).days

        def pending(stage: str) -> bool:
            return (r["key"], stage) not in already

        # Heads up the day before, once we're past the morning hour.
        if (
            days_out == 1
            and local_now.hour >= MORNING_PING_HOUR
            and pending(DAY_BEFORE)
        ):
            due.append((r, DAY_BEFORE))

        if r["time_confirmed"]:
            if (
                now.timestamp() <= when.timestamp() <= horizon
                and pending(STARTING_SOON)
            ):
                due.append((r, STARTING_SOON))
        elif (
            days_out == 0
            and local_now.hour >= MORNING_PING_HOUR
            and pending(MORNING_OF)
        ):
            due.append((r, MORNING_OF))

    return due


def mark_sent(conn: sqlite3.Connection, pairs: list[tuple[str, str]]) -> None:
    now = _now()
    conn.executemany(
        "INSERT OR IGNORE INTO sent (drop_key, stage, sent_at) VALUES (?,?,?)",
        [(key, stage, now) for key, stage in pairs],
    )
    conn.commit()


def set_drop_time(
    conn: sqlite3.Connection, key: str, when: datetime
) -> None:
    """Pin a real drop time. Flips the drop to time_confirmed so it earns a
    true T-minus ping, and marks it as overridden so the daily scrape won't
    reset it to Serebii's date-only midnight."""
    if when.tzinfo is None:
        raise ValueError("drop time must be timezone-aware")
    conn.execute(
        """UPDATE drops SET drop_datetime=?, time_confirmed=1, time_override=1
           WHERE key=?""",
        (when.astimezone(timezone.utc).isoformat(), key),
    )
    # New time, so any "starting soon" already sent no longer applies.
    conn.execute("DELETE FROM sent WHERE drop_key=? AND stage=?", (key, STARTING_SOON))
    conn.commit()


def find(conn: sqlite3.Connection, needle: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM drops WHERE product_name LIKE ? ORDER BY drop_datetime",
        (f"%{needle}%",),
    ).fetchall()


def upcoming(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    now = datetime.now(timezone.utc).isoformat()
    return conn.execute(
        "SELECT * FROM drops WHERE drop_datetime >= ? ORDER BY drop_datetime LIMIT ?",
        (now, limit),
    ).fetchall()
