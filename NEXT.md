# Next — the Pokémon Center gap

Written 2026-07-14. Everything else is done and live; this is the one open
thread. See `CLAUDE.md` for how the built system works.

## Where things stand

Both phases are running on GitHub Actions cron, no API keys, 127 tests green:

- **Phase 1** — Serebii → drop calendar → Discord (day-before + morning-of pings)
- **Phase 2** — NowInStock → watchlist filter → Discord (restock alerts, watching 15 products)

**Next scheduled signal:** Thu 2026-07-16, 08:00 PT — Pitch Black day-before heads up.

## The question

> Can we predict when Pokémon Center will open preorders for the next set?

**No.** Not predictively, and not with anything we can legitimately collect.
Any date would be fabrication dressed as a forecast.

### Why — the evidence

We have **exactly one PC data point**: on 2026-07-14, all Pitch Black PC
products were already SOLD OUT for a 07-17 release. That tells us preorders
opened *before* Jul 14 — not when. One lower bound from one observation is an
anecdote, not a model.

And we can't collect more. Verified 2026-07-14:

| Source | PC coverage | Notes |
| --- | --- | --- |
| NowInStock | **zero mentions** across 225KB | tracks Amazon, Target, Walmart, Best Buy, Sam's Club |
| TrackaLacker | **zero mentions** (Target 13, Amazon 3) | same gap |
| PokéBeach | zero "preorder" mentions on front page | news/strategy site, not a tracker |
| Pokémon Center itself | — | `robots.txt` disallows `/availabilities`, `/prices`, `/items`, `/offers`; Incapsula JS challenge |

**The trackers don't cover PC because they hit the same Incapsula wall we did.**
Nobody scrapes PC. That's not a gap in our tooling — it's the shape of the
problem.

Even with data, PC preorder openings are ad-hoc business decisions, not a
schedule. Predicting it means predicting a marketing call.

The common wisdom is "PC opens preorders 4–8 weeks before release." There is
**no evidence for this** in anything we've gathered. Don't build on it.

## The reframe

**Notification, not prediction.** Something that reaches you *because* PC
decided to open, requiring no inference.

### Option A — Pokémon Center's own notify-me / email list

The sanctioned channel, built by PC for exactly this. Two-minute signup, costs
nothing, works alongside this tool. The original handover doc anticipated the
next step: *"Email alerts → parse via IMAP."* If PC mail starts landing in
Gmail, feeding it into the relay is real — needs mail credentials, so it's a
deliberate decision, not a default.

**Do this regardless of everything below.** It's free and it's the only source
that is unambiguously permitted.

### Option B — a public restock Discord

The handover doc's other suggestion: *"Public Discord restock servers (many
expose webhook-relayable channels)."*

Verified 2026-07-14 via Discord's public invite API (read-only, no account
action):

| Server | Members | Online | Features |
| --- | --- | --- | --- |
| [Pokemon Restocks and Alerts](https://discord.com/invite/pkmnalerts) | ~75,960 | ~15,300 | `NEWS`, `COMMUNITY`, `DISCOVERABLE` |
| [PokePings - Restock Alerts](https://discord.com/invite/pokemonrestocks) | ~43,180 | ~7,800 | `NEWS`, `COMMUNITY`, `DISCOVERABLE` |

**`NEWS` is the important bit** — it means announcement channels exist, so
Discord's built-in **Follow** works. Without it this whole plan collapses.

**Claimed but NOT verified** (would require joining):

- that they actually alert on Pokémon Center (PokePings advertises "monitors
  across major Pokémon stores such as Pokémon Center, Target, BestBuy, Amazon")
- alert latency and quality
- whether they're alert-only or bot/cook-group adjacent

### The ethical note, stated plainly

PC is Incapsula-protected and nobody scrapes it. If these servers really do
alert on PC, they're getting it by means this project's non-goals reject —
proxies, anti-bot evasion.

Consuming their public output is precisely what the handover doc prescribes
("don't fight Akamai/PerimeterX for a signal you can get for free — aggregate
instead"), and reading a public message is not the same as defeating a bot wall
yourself. But the signal exists because someone else is doing the fighting.
That shouldn't be invisible. Decide with it in view.

Also: those servers' own rules may restrict redistributing alerts. Personal use
in a private channel is a different thing from republishing, but worth a glance
at their #rules.

## The catch

**Follow alone is a firehose.** A 76k-member server alerting across 100+
retailers will bury the ~3 relevant pings/week the whole project exists to
produce. That's exactly what `watchlist.yaml` was built to fix.

## Two shapes

**Zero code** — Follow their announcement channel into a muted `#raw` channel.
Works today. You skim it. No filtering.

**Filtered** — same Follow, plus a small bot polling `#raw` every 15 min via
Discord's REST API (`GET /channels/{id}/messages` — no persistent gateway
needed, fits the existing cron), run through the *existing* watchlist → dedupe →
restock pipeline, posting clean alerts to the Pikachu channel.

The NowInStock swap already proved the pipeline is source-agnostic — that was
one new file, with watchlist/dedupe/restock/seeding untouched. A Discord ingest
is the same size. **The blocker is a bot token, not the code.**

## Recommended next step

**Do the zero-code Follow first.**

1. Sign up for PC's notify-me on the products you want (Option A — do this anyway).
2. Join one server — start with Pokemon Restocks and Alerts (larger, more online).
3. Check its `#rules` for redistribution terms.
4. Follow its announcement channel into a **new, muted** `#raw` channel in your server.
   (Needs: you in their server + Manage Webhooks in yours.)
5. Watch for a few days.

That answers the two things research can't:

- **do they genuinely alert on PC?**
- **how bad is the volume really?**

If PC alerts show up and the noise is real → build the filtered ingest (needs a
Discord application + bot token, which only you can create). If PC coverage is
poor → we found out for free, and Option A is the answer.

**Do not** build the Discord ingest before step 5. We'd be guessing at a message
format we've never seen — the same mistake as the synthetic Best Buy fixture
(see `CLAUDE.md` § Fixture provenance).

## Handy

```bash
python -m pkmn_drops.cli upcoming          # confirmed release dates
python -m pkmn_drops.cli --dry-run relay   # what the relay sees right now
python -m pkmn_drops.cli status-vocab      # observed stock statuses
```

Confirmed releases: **30th Celebration — Sep 16**, **Delta Reign — Nov 6**.

Still outstanding from earlier: the Discord webhook URL was pasted in plaintext
into a chat session. Regenerating it in Discord + `gh secret set
DISCORD_WEBHOOK_URL` + a one-line `.env` edit closes that off.
