"""Shared HTTP GET with retry on a transient network blip.

Both sources are polled on a schedule -- the relay every 30 minutes, the drop
scrape daily -- so a single connect/read timeout is a hiccup to ride out, not a
failure worth announcing. Without this, one momentary timeout crashed a run and
posted a full traceback to Discord: a false alarm for something the next run 15
minutes later would have picked up on its own.

Only transient failures are retried. An HTTP error status (4xx/5xx) is raised
on the spot -- retrying it a second later won't change the answer -- and once
the retries are spent the last error propagates, so a genuine outage still
fails loudly. This is the "silent decay is the failure mode we care about"
rule from CLAUDE.md, minus the noise from momentary network flumes.
"""

from __future__ import annotations

import time

import requests

# ConnectTimeout / ReadTimeout and dropped connections are the transient blips.
# HTTPError (raised by raise_for_status) is deliberately absent, so a bad status
# propagates on the first attempt instead of being retried pointlessly.
_TRANSIENT = (requests.ConnectionError, requests.Timeout)

RETRIES = 3
BACKOFF = 2.0  # seconds between attempts: 2, then 4 -- ~6s across three tries


def get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    retries: int = RETRIES,
    backoff: float = BACKOFF,
    sleep=time.sleep,
) -> requests.Response:
    """GET `url`, retrying a transient network failure with exponential backoff.

    Returns the raised-for-status Response. Re-raises the last transient error
    once `retries` attempts are spent, and raises any non-transient
    RequestException (including a 4xx/5xx) immediately. Callers wrap whatever
    comes out in their own source-specific error.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except _TRANSIENT:
            if attempt == retries - 1:
                raise  # retries spent -- let a real outage fail loudly
            sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")  # pragma: no cover
