# pkmn_drops

Personal tool for Pokémon TCG sealed drops. See `CLAUDE_CODE_HANDOVER.md` for
the original design brief and rationale; this file is the working state.

## Non-goals — do not build these

Restating because they are the point:

- **No auto-checkout.** No cart automation, no payment autofill, no order submission.
- **No Queue-it bypass.** Violates ToS; gets accounts flagged and orders cancelled.
- **No anti-bot evasion.** If a scrape 403s, back off — don't escalate.
- **No high-frequency polling.** Respect robots.txt, honest User-Agent, generous intervals.

The value is *knowing about the drop early enough to show up*, not winning a
latency race. Human does all purchasing, manually, in a normal browser.

## Status

Phase 1 (drop calendar → Discord) is built. Phase 2 (alert relay) is **not**,
deliberately — ship Phase 1, use it for two weeks, then decide.

## How it works

```
serebii → parser → Drop → SQLite (diff) → Discord webhook
```

Two crons:

| Workflow       | When              | Does                                             |
| -------------- | ----------------- | ------------------------------------------------ |
| `calendar.yml` | daily 15:17 UTC   | scrape, diff, post digest of new/rescheduled     |
| `remind.yml`   | hourly at :08     | post "drop starting soon" for anything due       |

State lives in `data/drops.db`, committed back to the repo by each run because
Actions runners are ephemeral. `notified_at` in that file is what stops a
reminder firing every hour — losing it means duplicate pings.

## Reminder timing (the non-obvious bit)

Serebii publishes release **dates**, never times, so every drop currently has
`time_confirmed=False` and is anchored to local midnight. A naive T-30min
reminder would therefore fire at ~23:30 the *night before*. It doesn't:

- `time_confirmed=True` → ping within `REMINDER_LEAD_MINUTES` (45) of the drop.
- `time_confirmed=False` → ping at `MORNING_PING_HOUR` (08:00) local on the day.

The 45min lead is wider than the nominal T-30 on purpose: GitHub Actions cron
drifts 5–15 minutes under load, and a late runner must not skip the window.

## Commands

```bash
python -m pkmn_drops.cli scrape            # find drops, post digest
python -m pkmn_drops.cli remind            # post due reminders
python -m pkmn_drops.cli upcoming          # what's on the books (local, no posting)
python -m pkmn_drops.cli --dry-run scrape  # print instead of posting; no DB writes
```

`--dry-run` rolls back its DB writes. It has to: if it committed, the real run
would then see `new=0` and announce nothing.

## Secrets

`DISCORD_WEBHOOK_URL` — anyone holding this URL can post to the channel.
Local: `.env` (gitignored). CI: repo secret. Never in source.

## Testing

- **Parser tests are non-negotiable.** `tests/fixtures/serebii_english.html` is
  real captured HTML. When Serebii changes markup, these fail — that's the point.
- **A source returning zero results fails loudly.** Silent scraper decay is the
  #1 failure mode; `cli.py` catches exceptions and posts them to Discord.
- Discord and network are mocked. CI never posts to the real channel.

## Source gotchas

- The page declares **no charset** and is **windows-1252**. `requests` guesses
  ISO-8859-1 and mangles "Pokémon". `sources.py` forces the encoding.
- Serebii has **typos in its own dates** — "Februrary 14th 2007" on EX Power
  Keepers. Known typos are aliased in `parser.py`; unknown ones skip that row
  and post a warning rather than killing the other 127 rows.
- `api.pokemontcg.io` looks tempting but is **useless here**: it only publishes
  a set on/after release day, so it never knows about a drop in advance.
