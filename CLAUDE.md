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

Phase 1 (drop calendar → Discord) and Phase 2 (restock relay) are both built.
Phase 2 is **idle until `BESTBUY_API_KEY` is set** — the workflow warns rather
than failing.

## How it works

Phase 1 — *when does it come out?*

```
serebii → parser → Drop → SQLite (diff) → Discord webhook
```

Phase 2 — *can I buy it right now?*

```
Best Buy API → parse → dedupe → watchlist filter → restock diff → Discord
```

Phase 1 tells you a date. Phase 2 is the one you can act on: Pokémon Center had
every Pitch Black product sold out three days before Pitch Black's own release
date, so a release-date calendar alone would have pinged you for something
already gone.

Crons:

| Workflow       | When              | Does                                             |
| -------------- | ----------------- | ------------------------------------------------ |
| `calendar.yml` | daily 15:17 UTC   | scrape, diff, post digest of new/rescheduled     |
| `remind.yml`   | every 15 min      | post any due reminder stage                      |
| `relay.yml`    | every 15 min      | Phase 2: alert on watchlisted restocks           |

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
python -m pkmn_drops.cli relay                      # Phase 2: check for restocks
python -m pkmn_drops.cli status-vocab               # observed `orderable` values
python -m pkmn_drops.cli --dry-run relay            # print instead of posting
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

## Buy links

Each embed carries a `Buy` field: deterministic **search** URLs for Pokémon
Center, Best Buy, Target, Walmart, Amazon. Not scraped product URLs, for two
reasons:

1. **Pokémon Center is behind Imperva Incapsula** and serves a JS challenge to
   any non-browser client — even `robots.txt`. Getting product URLs out of it
   means defeating that, which is the anti-bot evasion this project refuses to
   do. We back off, per the non-goals.
2. **The link doesn't need to be fetchable by us** — only tappable by a human.
   Incapsula blocks bots, not browsers. So a search URL works fine, costs zero
   requests, and can't decay when a retailer reshuffles its catalogue.

Formats in `relay/buylinks.py` are hand-verified against real browser searches.
PC takes the term in the *path* (so path-encoding, not `quote_plus`) and skips
the "Pokemon TCG" prefix, since it only sells Pokémon and the extra words just
narrow results. Everywhere else needs the prefix — a bare "Pitch Black" on
Amazon returns paint.

## Phase 2 — restock relay

Ingests the **official Best Buy Products API**. Not a scraper: it's keyed,
sanctioned, and allows 5 req/sec and 50k req/day. Three search terms every 15
minutes is ~288 requests/day. The "no high-frequency polling" non-goal is about
hammering retailers who never invited you; Best Buy publishes this API and
documents the quota. Pokémon Center stays off-limits (Incapsula) and Target's
RedSky is an undocumented internal API, so neither is polled.

Two rules do the real work:

- **Alert on the transition into stock, never on being in stock.** The cron
  runs every 15min; without this one restock pings you forever.
- **Seed silently on first contact with a retailer.** Otherwise run one alerts
  on Best Buy's entire in-stock catalogue at once.

`watchlist.yaml` is the filter. Matching is deliberately dumb — case-insensitive
substring, no fuzzy logic. A false negative means you miss a drop, so if
something slips through, add an `exclude` term rather than making the matcher
clever. An unknown price never satisfies a `max_price` rule: if we can't prove
it's under budget, we don't claim it is.

### Best Buy's `orderable` field is undocumented

`onlineAvailability` is a documented boolean and is the stock signal.
`orderable` is recorded in `products.raw_status` but **never branched on** — its
value vocabulary isn't published, and guessing it means guessing whether an
alert is real. After a real run:

```bash
python -m pkmn_drops.cli status-vocab   # learn the vocabulary from real data
```

### The fixture is synthetic

`tests/fixtures/bestbuy_search.json` was built from the published schema, not
captured, because getting a key requires creating an account. That breaks this
project's own rule that fixtures be real. Replace it as soon as a key exists:

```bash
python -m pkmn_drops.tools.capture_bestbuy > tests/fixtures/bestbuy_search.json
```

If the real response differs from the schema, `tests/test_bestbuy.py` is where
it surfaces.

## Known gaps

- **Phase 1 tracks sets; Phase 2 tracks products.** They are not yet joined —
  a Pitch Black restock doesn't know it belongs to the Pitch Black drop. Fine
  for now, worth doing if the calendar and relay start disagreeing.
- **Drop MSRP is always null.** It's per-product, not per-set; Phase 2 has real
  prices, Phase 1 doesn't.
- **Best Buy only.** It's the one retailer here with a sanctioned API. Adding a
  second source is what `dedupe.py` exists for.

## Source gotchas

- The page declares **no charset** and is **windows-1252**. `requests` guesses
  ISO-8859-1 and mangles "Pokémon". `sources.py` forces the encoding.
- Serebii has **typos in its own dates** — "Februrary 14th 2007" on EX Power
  Keepers. Known typos are aliased in `parser.py`; unknown ones skip that row
  and post a warning rather than killing the other 127 rows.
- `api.pokemontcg.io` looks tempting but is **useless here**: it only publishes
  a set on/after release day, so it never knows about a drop in advance.
