# Example ideas — portfolio engineering

Documentation of the work the original hand-filed `portfolio` board produced
(R1 skills survey, R2 pipeline audit), rewritten as a runnable idea. The
research findings below are preserved as of 2026-09-05; verify before acting.

    mission/create-board.sh --slug portfolio --title "Portfolio Engineering" \
        --lanes 3 --skip-integration-tests --ideas docs/example-ideas/portfolio.md

## Idea 1: portfolio pipeline improvements

Fix the trader-profile portfolio cron pipeline (6 cron jobs, 6 skills) using
the findings of a read-only audit, and adopt a short list of externally
surveyed skills where they genuinely close a gap. Two source documents:
R1 (skill survey) and R2 (pipeline audit), both dated 2026-09-05.

### R1 — skills to install

Three candidate skill sets were surveyed from their own public repositories
(primary sources; the Claude Financial Services six were out of scope —
waitlist-gated, presuppose paid feeds — and are pattern-reference only).

1. **tradermonty/claude-trading-skills** (github.com/tradermonty/claude-trading-skills,
   MIT) — INSTALL, the backbone. Start with: us-undervalued-growth-screener,
   dividend-growth-pullback-screener, drawdown-circuit-breaker,
   breakout-trade-planner, trader-memory-core. Data deps: FMP API free tier
   (250 req/day), optional FINVIZ Elite (paid, skip), optional Alpaca paper
   account for execution templates. Install per-skill from the repo, not
   wholesale — most verification fields in its skills-index.yaml are
   `not_verified`.
2. **claude-office-skills stock-analysis**
   (github.com/claude-office-skills/skills, MIT) — INSTALL as an L2
   report-template skill. One file (`SKILL.md`), no code, no data access of
   its own. Borrow its report skeleton (metrics-at-a-glance table, thesis
   vs sector baseline, bull/bear, explicit limitations section). Do not
   treat its heuristic valuation thresholds as model logic — keep real
   computation in scripts, not the prompt.
3. **K-Dense-AI/scientific-agent-skills** (github.com/K-Dense-AI/scientific-agent-skills,
   MIT repo-level, per-skill licenses vary) — CONDITIONAL, cherry-pick only:
   database-lookup (FRED/Treasury macro data), statistical-analysis,
   statsmodels, matplotlib. It is a bio/chem/medicine/materials library, not
   a finance suite — do not install the other ~157 skills.

### R2 — pipeline findings and fixes

Read-only audit of `~/.hermes/profiles/trader/scripts/degiro_summary.py`
and the `investments-daily-portfolio-summary` skill (6 cron jobs: 3 book
summaries, gpw-radar weekly screener, cron-watchdog, cleanup).

**F1 — missed scheduled runs are silent and unrecovered.** Executions-db
and output-dir evidence showed a fully missed run (no execution row at
all), a claim-race failure with no retry, and a manual same-day rescue of
all three summary jobs — none of it surfaced anywhere a reader could see.
Root causes: `catch_up_occurrences` (cron misfire recovery) exists but is
unconfigured; `last_status: ok` reflects only the newest run, masking an
earlier miss; the watchdog checks heartbeats only against fixed deadlines
and cannot see executions-db claim failures at all.

**F2 — the "Buy/Sell Recommendations" section delivers noise.** On a real
day, the parkiet.com/analizy scrape contained zero recommendation-keyword
titles; the extraction fallback dumped generic macro headlines under a
misleading "recommendations" header, with URLs preserved on only some
bullets.

**F3 — doc/reality drift.** `SKILL.md` still lists a cron job
(`deep_dive.py`) retired weeks earlier; the orphaned script's
`rotation_queue()` is consumed only by its own dead code path; three
installed skills are wired to no cron job at all.

**F5 — layer gaps.** No fundamentals layer anywhere (P/E, margins, net
debt, EPS) — the LLM notes get "no coverage" for essentially every
holding; sentiment/news exists but is rendered raw with no per-holding
association or scoring; no peer-comps (sector-relative valuation) view.

### What to change

1. **Missed-run resilience** — configure cron catch-up/misfire recovery
   for the three summary jobs; extend the watchdog to alert on an
   executions-db claim-failed/failed execution with no successful retry,
   and on a missing output file by each job's morning deadline.
2. **Parkiet extraction fix** — preserve URLs on every bullet, extend the
   keyword regex to match real corpus forms, and emit an explicit
   "no broker recommendations today" line instead of dumping unrelated
   headlines under a recommendations header.
3. **Hygiene** — correct `SKILL.md`'s entry-points table; retire or
   rewire `deep_dive.py` and `rotation_queue()`; decide the fate of the
   three unwired skills.
4. **Fundamentals layer** — day-cached fetch of P/E, margins, net debt,
   EPS per holding (Yahoo quoteSummary financialData, already used for
   analyst targets; FMP free tier for foreign names per the R1 survey),
   surfaced in the holdings table and fed into the existing rule-based
   insight scorer.
5. **Report template** — adopt the stock-analysis skill's report skeleton
   into the analyst prompts (metrics table, thesis vs sector baseline,
   bull/bear, limitations section).

### Done means

- A scheduler-level or watchdog-level miss on any of the three summary
  jobs produces an alert within the hour, with either an automatic
  catch-up or a documented manual-rescue path — no more silent gaps.
- A day with zero real broker recommendations in the source scrape
  produces zero false "recommendation" lines and no dropped URLs.
- `SKILL.md`'s entry-points table matches the live cron jobs; no skill is
  installed but unreferenced without a recorded reason.
- The holdings table carries a valuation snapshot (P/E, margins, net
  debt, EPS) for names with available coverage.
- New/adopted skills are the ones verdicted INSTALL or CONDITIONAL above,
  installed per-skill (not repo-wide), sourced from the repositories
  named above.
