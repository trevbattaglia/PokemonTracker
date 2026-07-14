"""Discord webhook client. Link must be one tap from the notification."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..config import MAX_ALERTS_PER_RUN, discord_webhook_url

TIMEOUT = 15
COLOR_NEW = 0xFFCB05      # Pokemon yellow
COLOR_REMINDER = 0xEE1515  # Pokemon red


class DiscordError(RuntimeError):
    pass


def _post(payload: dict) -> None:
    resp = requests.post(discord_webhook_url(), json=payload, timeout=TIMEOUT)
    if resp.status_code not in (200, 204):
        raise DiscordError(f"webhook returned {resp.status_code}: {resp.text[:200]}")


def _field(row, name: str, value, inline: bool = True) -> dict | None:
    return {"name": name, "value": str(value), "inline": inline} if value else None


def _embed(row, *, color: int, title_prefix: str) -> dict:
    when = datetime.fromisoformat(row["drop_datetime"])
    ts = int(when.timestamp())
    # Discord renders <t:...> in the reader's own timezone.
    when_text = f"<t:{ts}:F>" if row["time_confirmed"] else f"<t:{ts}:D> (time TBA)"

    fields = [
        f
        for f in (
            {"name": "When", "value": when_text, "inline": False},
            _field(row, "Retailer", row["retailer"]),
            _field(row, "MSRP", f"${row['msrp']:.2f}" if row["msrp"] else None),
            _field(row, "Set", row["set_name"]),
        )
        if f
    ]

    embed = {
        "title": f"{title_prefix} {row['product_name']}",
        "color": color,
        "fields": fields,
        "footer": {"text": f"source: {row['source']}"},
    }
    if row["product_url"]:
        embed["url"] = row["product_url"]
    return embed


def send_digest(rows: list, *, title: str) -> None:
    """One message summarising newly-discovered or rescheduled drops."""
    if not rows:
        return

    if len(rows) > MAX_ALERTS_PER_RUN:
        _post(
            {
                "content": (
                    f"**{title}** — {len(rows)} drops found, which is more than "
                    f"expected. Muting detail to avoid spam; check the DB. "
                    f"Something upstream may be broken."
                )
            }
        )
        return

    _post(
        {
            "content": f"**{title}**",
            "embeds": [_embed(r, color=COLOR_NEW, title_prefix="📅") for r in rows],
        }
    )


def send_reminder(row) -> None:
    """Fires shortly before a drop. This is the message that matters."""
    _post(
        {
            "content": "⏰ **Drop starting soon**",
            "embeds": [_embed(row, color=COLOR_REMINDER, title_prefix="🔥")],
        }
    )


def send_error(message: str) -> None:
    """Loud failure. Silent decay is the failure mode we care most about."""
    _post({"content": f"⚠️ **pkmn_drops error**\n```\n{message[:1800]}\n```"})
