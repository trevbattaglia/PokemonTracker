"""Shared HTTP fetch: a transient timeout is ridden out, a bad status is not.

Regression cover for the connect-timeout incident -- one momentary timeout to
nowinstock.net used to crash a whole relay run and post a traceback to Discord.
"""

from __future__ import annotations

import pytest
import requests

from pkmn_drops import net


class _FakeResp:
    def __init__(self, status: int = 200) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def _fake_get(outcomes):
    """A requests.get stand-in that yields each outcome in turn.

    An outcome is either an exception instance (raised) or a response (returned).
    """
    calls: list[str] = []

    def fake(url, headers=None, timeout=None):
        calls.append(url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fake.calls = calls
    return fake


def test_retries_transient_timeout_then_succeeds(monkeypatch):
    slept: list[float] = []
    ok = _FakeResp()
    fake = _fake_get(
        [requests.ConnectTimeout("blip"), requests.ConnectTimeout("blip"), ok]
    )
    monkeypatch.setattr(net.requests, "get", fake)

    resp = net.get("http://x", headers={}, timeout=1, sleep=slept.append)

    assert resp is ok
    assert len(fake.calls) == 3
    assert slept == [2.0, 4.0]  # exponential backoff between the three tries


def test_gives_up_after_retries_and_reraises_transient(monkeypatch):
    fake = _fake_get([requests.ReadTimeout("still down")] * 3)
    monkeypatch.setattr(net.requests, "get", fake)

    # A real outage that outlasts the retries must still surface, loudly.
    with pytest.raises(requests.ReadTimeout):
        net.get("http://x", headers={}, timeout=1, retries=3, sleep=lambda _: None)
    assert len(fake.calls) == 3


def test_bad_status_is_not_retried(monkeypatch):
    slept: list[float] = []
    fake = _fake_get([_FakeResp(503), _FakeResp(200)])
    monkeypatch.setattr(net.requests, "get", fake)

    with pytest.raises(requests.HTTPError):
        net.get("http://x", headers={}, timeout=1, sleep=slept.append)
    assert len(fake.calls) == 1  # a 5xx won't fix itself on an immediate retry
    assert slept == []


def test_success_on_first_try_does_not_sleep(monkeypatch):
    slept: list[float] = []
    fake = _fake_get([_FakeResp(200)])
    monkeypatch.setattr(net.requests, "get", fake)

    net.get("http://x", headers={}, timeout=1, sleep=slept.append)
    assert len(fake.calls) == 1
    assert slept == []
