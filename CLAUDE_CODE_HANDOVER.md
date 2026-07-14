# `pkmn_drops/` — Claude Code Handover

## What this is

A two-phase personal tool for Pokémon TCG sealed drops:

1. **Drop calendar** — scrape announced release/drop dates, write to Google Calendar with reminders.
2. **Alert relay** — ingest existing public restock feeds, filter to a SKU watchlist, push clean alerts to a private Discord channel.

Human does all purchasing. Manually. In a normal browser.

---

## Non-goals (do not build these)

These are explicit. If a future prompt drifts toward them, stop and flag it.

- ❌ **No auto-checkout.** No cart automation, no payment autofill, no order submission.
- ❌ **No Queue-it bypass.** Pokémon Center queue positions are randomized; bypass violates ToS and gets accounts flagged and orders cancelled.
- ❌ **No anti-bot evasion.** No stealth plugins, no fingerprint spoofing, no residential proxy rotation against Pokémon Center. If a scrape gets 403'd, back off — don't escalate.
- ❌ **No high-frequency polling** of any retailer. Respect `robots.txt`, honest User-Agent, generous intervals.

The value of this tool is *knowing about the drop early enough to show up*. Not winning a latency race.

---

## Phase 1 — Drop Calendar

### Goal
Never miss a drop because you didn't know it was happening.

### Data sources (in priority order)
- Official Pokémon TCG release schedule (announced months ahead — this is public, static, and low-frequency).
- Pokémon Center "coming soon" / preorder pages.
- Community drop calendars (PokéBeach, r/PokeInvesting sidebar, TCG drop trackers) as a cross-check.

### Behavior
- Run **once daily** via GitHub Actions cron. This is not time-sensitive data.
- Parse into a normalized schema:

```python
@dataclass
class Drop:
    sku: str | None
    product_name: str
    set_name: str | None
    retailer: str            # "pokemon_center" | "target" | "walmart" | ...
    drop_datetime: datetime  # UTC; may be date-only if time unannounced
    time_confirmed: bool
    product_url: str | None
    msrp: float | None
    source: str              # provenance, for debugging bad parses
```

- Diff against stored state. Only act on **new or changed** drops.
- Write to Google Calendar:
  - Event at `drop_datetime`
  - Reminders at **T-30min** and **T-5min**
  - Description = product URL + MSRP + source
  - If `time_confirmed == False`, create an all-day event instead and mark it clearly.

### Storage
SQLite is sufficient. Supabase only if you want to query this from somewhere else later. **Decision needed.**

### Success criterion
You get a calendar ping 30 minutes before a drop, with the direct product link in the event body, without having thought about it.

---

## Phase 2 — Alert Relay

### Goal
Turn a firehose of public restock alerts into ~3 relevant pings a week.

### Why a relay and not a scraper
The monitoring problem is already solved by people with dedicated infrastructure. Re-solving it means fighting Akamai/PerimeterX for a signal you can get for free. Don't. Aggregate instead.

### Ingest
Pick 2–3 sources. Candidates:
- Public Discord restock servers (many expose webhook-relayable channels)
- RSS from restock trackers
- Email alerts → parse via IMAP

**Decision needed:** which sources. Start with one, prove the pipeline, then add.

### Pipeline

```
ingest → normalize → dedupe → watchlist filter → Discord webhook
```

- **Normalize** to the same `Drop`-adjacent schema. Every source formats differently; this is most of the work.
- **Dedupe** on `(retailer, sku, ~5min time bucket)`. The same restock will hit you from three sources within seconds.
- **Watchlist filter** — a YAML file. This is the whole point:

```yaml
watchlist:
  - match: "Elite Trainer Box"
    retailers: [pokemon_center, target, best_buy]
    max_price: 60.00
  - match: "Booster Bundle"
    retailers: [pokemon_center]
exclude:
  - "plush"
  - "pin collection"
  - "figure"
```

- **Output** to a private Discord channel. Embed with: product name, retailer, price, **direct link**, timestamp. Link must be one tap from the notification.

### Rate limiting
Cap outbound alerts. If >10 fire in an hour, something upstream is broken or you're being spammed — send one summary message and mute rather than blowing up your phone.

---

## Repo shape

```
pkmn_drops/
├── CLAUDE.md
├── pyproject.toml
├── watchlist.yaml
├── src/pkmn_drops/
│   ├── models.py          # Drop dataclass, shared schema
│   ├── calendar/
│   │   ├── sources.py     # scrapers, one fn per source
│   │   ├── parser.py      # → Drop
│   │   └── gcal.py        # Google Calendar client
│   ├── relay/
│   │   ├── ingest/        # one module per feed source
│   │   ├── normalize.py
│   │   ├── dedupe.py
│   │   ├── filter.py      # watchlist.yaml
│   │   └── discord.py
│   └── store.py           # SQLite
├── tests/
└── .github/workflows/
    ├── calendar.yml       # daily cron
    └── relay.yml          # continuous or frequent cron
```

---

## Testing

Match the standard from `bpp_bot`:

- **Parser tests are non-negotiable.** Save real HTML/JSON fixtures for every source. Sources change their markup without warning; fixtures are how you find out before the drop, not after.
- Dedupe tests with synthetic multi-source collisions.
- Watchlist filter tests — especially the exclusions. A false negative here means you miss a drop.
- Mock the Google Calendar and Discord clients. Never hit them in CI.
- **A source returning zero results should fail loudly, not silently pass.** Silent scraper decay is the #1 failure mode for this kind of tool.

---

## Open decisions

| Decision | Options | Notes |
|---|---|---|
| Storage | SQLite / Supabase | SQLite unless you want cross-device reads |
| Relay sources | ? | Start with exactly one |
| Relay cadence | Continuous worker / GH Actions cron | Cron is cheaper; latency doesn't matter much here |
| Calendar target | Google Calendar / .ics file | GCal has better mobile push |

---

## Build order

1. `models.py` — lock the schema first.
2. Calendar: one source → parser → tests → GCal writer → cron.
3. **Ship it. Use it for two weeks.** See if it actually changes behavior.
4. Only then start Phase 2.

Resist building both at once. Phase 1 has standalone value; Phase 2 without Phase 1 is just noise.
