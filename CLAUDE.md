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
| `remind.yml`   | every 15 min      | post any due reminder stage                      |

State lives in `data/drops.db`, committed back to the repo by each run because
Actions runners are ephemeral. The `sent` table is what stops a reminder firing
every 15 minutes — losing it means duplicate pings.

## Reminder timing (the non-obvious bit)

**Serebii publishes release dates, never times.** So a literal "30 minutes
before" is undefined for a drop we only know the date of — there is no
timestamp to count back from, and the local-midnight anchor means a naive
T-minus window would fire at ~23:20 the *night before*.

Each drop passes through stages, tracked per-stage in the `sent` table:

| Stage           | Fires                                    | Applies to |
| --------------- | ---------------------------------------- | ---------- |
| `day_before`    | 08:00 local, the day before              | every drop |
| `starting_soon` | within `REMINDER_LEAD_MINUTES` (40)      | timed only |
| `morning_of`    | 08:00 local, on the day                  | date-only  |

So a date-only drop gets *day before* + *morning of*; a drop with a known time
gets *day before* + *~30 min before*.

The 40min lead is wider than the nominal 30 on purpose: the cron runs every
15min and Actions drifts 5–15min under load, so a strict 30 would let a late
runner skip the window entirely. In practice the ping lands ~25–40min ahead.
Hourly cron cannot do this at all — the drop is 60min out on one run and 0min
out on the next — which is why `remind.yml` is `*/15`.

## Getting a true "30 minutes before"

Pin a real time once you learn one (Pokémon Center announcements, etc.):

```bash
python -m pkmn_drops.cli set-time "Pitch Black" "2026-07-17 09:00"
```

That flips the drop to `time_confirmed` and sets `time_override=1`, which stops
the daily scrape from resetting it to Serebii's date-only midnight — without
that flag the scrape would look like a reschedule and re-ping. Times are in
`PKMN_TZ`. Run it locally, then commit `data/drops.db`.

## Commands

```bash
python -m pkmn_drops.cli scrape                     # find drops, post digest
python -m pkmn_drops.cli remind                     # post due reminder stages
python -m pkmn_drops.cli upcoming                   # what's on the books (no posting)
python -m pkmn_drops.cli set-time NAME "Y-M-D H:M"  # pin a real drop time
python -m pkmn_drops.cli --dry-run scrape           # print instead of posting
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
