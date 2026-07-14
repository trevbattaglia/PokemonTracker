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


def discord_webhook_url() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set. Put it in .env for local runs, or in "
            "GitHub Actions repository secrets for CI."
        )
    return url


# Target is "about 30 minutes before". The window is wider than 30 on purpose:
# the cron runs every 15min and Actions drifts 5-15min under load, so a strict
# 30 would let a late runner skip the window entirely and ping nothing. At 40
# the first qualifying run lands roughly 25-40min out -- early, never missed.
REMINDER_LEAD_MINUTES = 40

# Date-only drops (Serebii publishes dates, never times) are anchored to local
# midnight. A T-minus ping would fire ~11pm the night before, so they get a
# morning-of ping at this local hour instead.
MORNING_PING_HOUR = int(os.environ.get("PKMN_MORNING_HOUR", "8"))

# Cap outbound alerts; if this many fire in an hour something upstream broke.
MAX_ALERTS_PER_RUN = 10
