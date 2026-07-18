"""Configuration. Secrets come from the environment, never from source."""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# Local runs read .env; in GitHub Actions the secrets are already in the env
# and there is no .env file, so this is a no-op there.
load_dotenv(REPO_ROOT / ".env")

# Pokemon Center is Bellevue-based and announces drop times in Pacific, so PT
# is the natural default for this domain. Override with PKMN_TZ.
LOCAL_TZ = ZoneInfo(os.environ.get("PKMN_TZ", "America/Los_Angeles"))

DB_PATH = Path(os.environ.get("PKMN_DB", REPO_ROOT / "data" / "drops.db"))

WATCHLIST_PATH = Path(os.environ.get("PKMN_WATCHLIST", REPO_ROOT / "watchlist.yaml"))


def discord_webhook_url() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set. Put it in .env for local runs, or in "
            "GitHub Actions repository secrets for CI."
        )
    return url


# The window is sized to the poll interval: `starting_soon` fires on the first
# run that finds the drop within LEAD minutes ahead, so LEAD must exceed the
# gap between runs plus Actions' 5-15min drift, or a late runner skips the
# window entirely and pings nothing. The tick runs every 30min (see tick.yml),
# so 60 keeps at least two polls inside the window; the first qualifying run
# lands roughly 30-60min out -- early, never missed. (At the old */15 cadence
# this was 40.) Raise it in step if the interval ever widens again.
REMINDER_LEAD_MINUTES = 60

# Date-only drops (Serebii publishes dates, never times) are anchored to local
# midnight. A T-minus ping would fire ~11pm the night before, so they get a
# morning-of ping at this local hour instead.
MORNING_PING_HOUR = int(os.environ.get("PKMN_MORNING_HOUR", "8"))

# Cap outbound alerts; if this many fire in an hour something upstream broke.
MAX_ALERTS_PER_RUN = 10
