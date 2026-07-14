"""Discord client. Mocked -- CI must never hit the real webhook."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import responses

from pkmn_drops.relay import discord

WEBHOOK = "https://discord.com/api/webhooks/fake/fake"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)


def row(**kw) -> dict:
    base = {
        "key": "abc123",
        "product_name": "Delta Reign",
        "set_name": "Delta Reign",
        "retailer": "tcg_release",
        "drop_datetime": datetime(2026, 11, 6, tzinfo=timezone.utc).isoformat(),
        "time_confirmed": 0,
        "product_url": "https://www.serebii.net/card/deltareign",
        "msrp": None,
        "source": "serebii:english_sets",
    }
    return {**base, **kw}


def test_missing_webhook_env_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    with pytest.raises(RuntimeError, match="DISCORD_WEBHOOK_URL is not set"):
        discord.discord_webhook_url()


@responses.activate
def test_reminder_posts_embed_with_direct_link():
    responses.add(responses.POST, WEBHOOK, status=204)
    discord.send_reminder(row())

    body = responses.calls[0].request.body
    import json

    payload = json.loads(body)
    embed = payload["embeds"][0]
    assert embed["url"] == "https://www.serebii.net/card/deltareign"
    assert "Delta Reign" in embed["title"]


@responses.activate
def test_date_only_drop_is_marked_time_tba():
    responses.add(responses.POST, WEBHOOK, status=204)
    discord.send_reminder(row(time_confirmed=0))

    import json

    embed = json.loads(responses.calls[0].request.body)["embeds"][0]
    when = next(f for f in embed["fields"] if f["name"] == "When")
    assert "time TBA" in when["value"]


@responses.activate
def test_confirmed_time_is_not_marked_tba():
    responses.add(responses.POST, WEBHOOK, status=204)
    discord.send_reminder(row(time_confirmed=1))

    import json

    embed = json.loads(responses.calls[0].request.body)["embeds"][0]
    when = next(f for f in embed["fields"] if f["name"] == "When")
    assert "time TBA" not in when["value"]


@responses.activate
def test_empty_digest_sends_nothing():
    responses.add(responses.POST, WEBHOOK, status=204)
    discord.send_digest([], title="New drops")
    assert len(responses.calls) == 0


@responses.activate
def test_digest_over_cap_sends_one_summary_not_a_flood():
    responses.add(responses.POST, WEBHOOK, status=204)
    discord.send_digest([row() for _ in range(25)], title="New drops")

    import json

    assert len(responses.calls) == 1
    payload = json.loads(responses.calls[0].request.body)
    assert "embeds" not in payload
    assert "25 drops found" in payload["content"]


@responses.activate
def test_http_error_raises():
    responses.add(responses.POST, WEBHOOK, status=404, body="Unknown Webhook")
    with pytest.raises(discord.DiscordError, match="404"):
        discord.send_reminder(row())
