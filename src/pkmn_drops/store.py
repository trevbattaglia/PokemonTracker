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
    notified_at    TEXT             -- set once the reminder has fired
);
CREATE INDEX IF NOT EXISTS idx_drops_when ON drops(drop_datetime);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = Path(path or DB_PATH)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
            "SELECT drop_datetime FROM drops WHERE key = ?", (d.key,)
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
        elif row["drop_datetime"] != when:
            changed.append(d)
            # Reschedule: clear notified_at so the new time gets its own ping.
            conn.execute(
                """UPDATE drops SET drop_datetime=?, time_confirmed=?, product_url=?,
                       msrp=?, source=?, last_seen=?, notified_at=NULL
                   WHERE key=?""",
                (when, int(d.time_confirmed), d.product_url, d.msrp, d.source,
                 now, d.key),
            )
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
) -> list[sqlite3.Row]:
    """Un-pinged drops that should be announced right now.

    Two cases, because a date-only drop has no meaningful "T-minus":

    - time_confirmed: ping within `lead_minutes` of the real drop time.
    - date-only: the drop is anchored to local midnight, so a T-minus ping
      would fire late the *previous* night. Ping on the morning of instead.
    """
    now = now or datetime.now(timezone.utc)
    horizon = now.timestamp() + lead_minutes * 60
    local_now = now.astimezone(LOCAL_TZ)

    due: list[sqlite3.Row] = []
    for r in conn.execute(
        "SELECT * FROM drops WHERE notified_at IS NULL ORDER BY drop_datetime"
    ):
        when = datetime.fromisoformat(r["drop_datetime"])

        if r["time_confirmed"]:
            if now.timestamp() <= when.timestamp() <= horizon:
                due.append(r)
            continue

        local_when = when.astimezone(LOCAL_TZ)
        if (
            local_when.date() == local_now.date()
            and local_now.hour >= MORNING_PING_HOUR
        ):
            due.append(r)

    return due


def mark_notified(conn: sqlite3.Connection, keys: list[str]) -> None:
    now = _now()
    conn.executemany(
        "UPDATE drops SET notified_at=? WHERE key=?", [(now, k) for k in keys]
    )
    conn.commit()


def upcoming(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    now = datetime.now(timezone.utc).isoformat()
    return conn.execute(
        "SELECT * FROM drops WHERE drop_datetime >= ? ORDER BY drop_datetime LIMIT ?",
        (now, limit),
    ).fetchall()
