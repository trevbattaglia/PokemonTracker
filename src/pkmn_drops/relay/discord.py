"""Discord webhook client. Link must be one tap from the notification."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..config import MAX_ALERTS_PER_RUN, discord_webhook_url
from . import buylinks

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
            _field(row, "MSRP", f"${row['msrp']:.2f}" if row["msrp"] else None),
            _field(row, "Set", row["set_name"]),
        )
        if f
    ]

    # The whole point of the notification: get to a checkout page in one tap.
    # Goes last so it sits closest to the thumb.
    fields.append(buylinks.buy_field(row["set_name"] or row["product_name"]))

    embed = {
        "title": f"{title_prefix} {row['product_name']}",
        "color": color,
        "fields": fields,
        "footer": {"text": f"source: {row['source']}"},
    }
    if row["product_url"]:
        # Serebii's set page -- reference info, not a store. The Buy field is
        # what you actually tap.
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


# How each reminder stage presents itself. The lead text is the part you read
# from a phone notification without opening Discord, so it carries the timing.
_STAGE_STYLE = {
    "day_before": ("📣 **Tomorrow**", COLOR_NEW, "📅"),
    "morning_of": ("🎯 **Today**", COLOR_REMINDER, "🔥"),
    "starting_soon": ("⏰ **Drop starting soon**", COLOR_REMINDER, "🔥"),
}


def send_reminder(row, stage: str) -> None:
    """Fires ahead of a drop. This is the message that matters."""
    try:
        content, color, prefix = _STAGE_STYLE[stage]
    except KeyError:
        raise ValueError(f"unknown reminder stage: {stage!r}") from None

    _post(
        {
            "content": content,
            "embeds": [_embed(row, color=color, title_prefix=prefix)],
        }
    )


def send_error(message: str) -> None:
    """Loud failure. Silent decay is the failure mode we care most about."""
    _post({"content": f"⚠️ **pkmn_drops error**\n```\n{message[:1800]}\n```"})
