## Idea 1: GPW small-cap candidate research

Build a research pipeline that proposes *new* Polish small-cap investment
candidates with a written thesis, and that can be measured after the fact.

### Where the work happens, and where it lands

These are two different places and the split is deliberate.

**The work happens in this board's own work directory** — the board's
`workdir`, inside the kanban repository. Every card stages there: the module,
its tests, its config, its build descriptor. Nothing this board generates lands
anywhere else in the repository, so deleting the work directory is a clean start.

**The result updates the Hermes `trader` profile, and doing so is part of this
idea** — not a follow-up, not a document for someone else to act on. The lane
installs the module into `~/.hermes/profiles/trader/`, registers the cron job,
and wires the watchdog. It is finished when the job runs there, not when the
code compiles here.

One rule governs that second tree: **the driver never runs git in it.**
`~/.hermes/profiles` is a git repository with an hourly autocommit-and-push
cron (`sync-hermes-profiles.sh`) feeding a second workstation. Work there is
file edits only — no `git add`, no commit, no branch. Pause that cron before
starting this board (see this board's `README.md`).

So the module must be self-contained and configured from outside, with no
assumption about where it sits on disk.

### What exists today

The `trader` profile runs six cron jobs, all `no-agent`, all delivering to
Telegram. Three report on holdings (`portfolio-degiro` 10:00,
`portfolio-avanza-private` 12:00, `portfolio-avanza-jfusion` 14:00). One
screens (`gpw-radar`, Saturdays 11:00). Two keep house
(`portfolio-cron-watchdog` hourly, `portfolio-cleanup` 15:30).

`scripts/gpw_screen.py` is the profile's only candidate generator. It scrapes
the GPW main-market company list from gpw.pl (cached 7 days to
`Data/gpw-universe.csv`, currently 331 tickers), pulls a year of Yahoo bars for
every non-held name at 1.0s pacing, and ranks on price and volume alone:
relative strength vs WIG20 over 60d/20d, distance to the 52-week high, RSI<=35
within an uptrend, volume surge >=2.5x, bullish RSI divergence. Score >=2.0
gets hinted, with a 14-day per-ticker cooldown.

Reusable machinery in `shared_lib/`: `stock_cache.py` (day-scoped per-ticker
cache with independent sections), `shared_analytics.py` (one bar fetch per
symbol per day, shared across jobs), `analytics.py` (technical metrics),
`insights.py` (deterministic rule engine), `llm.py` (local LLM client),
`analyst.py` (LLM research pass over held tickers), `runpaths.py` (day-scoped
run state and heartbeats), `history.py`.

### The three gaps this idea closes

**No fundamentals exist anywhere in the profile.** Searching every
`investments-*` skill, `scripts/` and `shared_lib/` for `pe_ratio`,
`ev_ebitda`, `price_to_book`, `trailingPE` or `marketCap` returns nothing. So
"small cap" is not currently expressible — the radar cannot distinguish Orlen
from a 200m-PLN industrial. Yahoo v10 `quoteSummary` carries what is needed,
free, through the cookie/crumb handshake `fetch_all_market_data.py:376-456`
already performs. Verified against real GPW micro caps, denominated in PLN:

    4MS.WA   mcap 117,400,304   PE 10.82   PB 1.48   debt 2.5M    rev 107M
    3RG.WA   mcap  57,028,992   PE 14.04   PB 2.57   debt 0       rev 9.5M
    ZUE.WA   mcap 275,461,728   PE 35.59   PB 1.33   debt 55M     rev 940M
    11B.WA   mcap 315,686,208   PE null    PB 1.34   debt 3.9M    rev 128M
    KGN.WA   mcap 1,062,370,048 PE 2.93    PB 0.38   debt 0       rev 2.9B

A null `trailingPE` means no trailing earnings — a signal, not a coverage hole.

**The LLM never sees a candidate.** `analyst.py` is the only production LLM
caller and it iterates *held* tickers, writing a <=150-word buy-side note per
position. The radar's output is a markdown file no model reads. The one step
that could turn "RSI 32, volume 3x" into a reason to look never runs on the
names that need it.

**Nothing is measured.** `Data/gpw-radar-hints.json` stores `{last, score}` per
hinted ticker, used only for the cooldown. No forward return, no hit rate. The
radar has run weekly for months and there is no way to say whether it has ever
been right — which means it cannot be wrong either.

### Constraints that shape any solution

- **The LLM is serialized.** `shared_lib/llm.py` runs one inference at a time
  against a local llama-swap box that the firecrawl scraper also shares. An
  LLM pass over a universe-sized list is not physically available; only a
  small number of candidates per run can get one.
- **Yahoo is paced at 1.0s per call**, so a full pass over the 331-name
  universe is minutes, not seconds.
- **Free sources only.** Yahoo, gpw.pl, NBP and the existing Polish RSS feeds
  (bankier ESPI and gielda, money.pl, strefainwestorow, pb.pl, parkiet.com)
  cost nothing and need no keys. `MASSIVE_API_KEY` is referenced by
  `intl_summary.py:475` and absent from `.env`, so that path already skips.
- **`shared_lib` is coupled by absolute `sys.path.insert`** from every entry
  point. The new module must not add a seventh caller to that pattern — reuse
  the profile's ideas, not its import graph.
- **The watchdog is registration-based.** `cron_watchdog.py` monitors four job
  slugs by name and is blind to anything not listed, so an unregistered weekly
  job that silently stops leaves an unexplained gap.

### Open questions

- **How far can the universe reach?** Today it is gpw.pl's 331 main-market
  names. NewConnect, where Polish micro caps actually list (~350 companies),
  is entirely absent — so the pipeline cannot see most of the market this idea
  is about. investing.com is the identified candidate source: good Polish
  coverage, reachable through the profile's local firecrawl at
  `localhost:3002`, verified returning a live table. But its market tabs are
  JavaScript-driven — scraping
  `pl.investing.com/equities/poland?market=newconnect` ignored the parameter
  and returned the same default 20 WIG20 rows — and its terms prohibit
  automated scraping while Cloudflare fronts it. Establish whether a full
  NewConnect universe can be pulled reliably; if not, name the fallback.
- **Where are the small-cap bounds?** A band has to be chosen and it should be
  configuration, not a literal.
- **How many candidates per run is useful?** Few enough for the serialized LLM,
  many enough to be worth reading.
- **How is a forward return attributed** — against WIG, sWIG80, or both, and
  over what horizons?

### Explicitly out of scope

- **The Swedish market.** `intl_summary.py:535-570` scrapes
  tradedesk.se/svenska-aktier for name/signal/score and discards every
  non-held row at `:562` — a ready-made Swedish candidate source thrown on the
  floor — and there is no OMX universe list to build on. Obvious second market,
  separate work.
- **Broker integration.** Holdings are hand-exported CSVs
  (`portfolio_config.py:22,43,62`). Not this.
- **Repairs to the existing pipeline** — the parkiet "recommendations"
  extraction, the retired `deep_dive.py`, the unwired skills, the watchdog's
  own blind spots (`portfolio-cleanup` and itself). Real findings, different
  work.
- **Execution of any kind.** This job proposes reading material. No position
  sizing, no price targets, no orders.

### Done means

- A weekly run emits Polish small-cap candidates, each with a market cap
  inside the configured band, each with a written thesis naming the specific
  facts that surfaced it, each with a bear case and an explicit statement of
  what could not be verified.
- Any candidate can be traced back to the exact values that passed it. No
  unexplained entries.
- Fundamentals are available from the day cache for any GPW ticker without a
  second network call in the same day.
- Every candidate ever proposed has a row in a durable ledger, and the weekly
  output states the running excess return against a named benchmark over
  stated horizons.
- The universe question is answered either way: NewConnect names are in, or
  the reason they are not is written down with the fallback.
- The module's test suite is green and it imports without any `sys.path`
  manipulation.
- The job is installed in the trader profile, listed by
  `hermes --profile trader cron list`, and has produced one verified run
  against scratch run state.
- `cron_watchdog.py` alerts when the new job's heartbeat is missing, verified
  by running the watchdog with it absent.
- No git command was run in `~/.hermes/profiles`, and every change made there
  is written down with its undo.
