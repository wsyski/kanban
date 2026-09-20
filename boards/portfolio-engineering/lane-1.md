## Idea 1: No Silent Gaps — runs, reports, and the research pass

A degraded report must not be indistinguishable from a complete one. Three mechanisms in
this profile produce exactly that: a run killed before it delivers, a report block that
renders identically when it was **skipped** and when it legitimately found nothing, and a
watchdog that can only see jobs it already knows about. This idea closes the class, not
one instance of it.

### You are working in the profile, on what is already there

The work directory **is** the `trader` profile. Not a staging copy of it — the
tree itself, with its six running cron jobs, its `shared_lib/`, its `scripts/` and
its own git history. This idea is a change to a system that runs, made in place,
the way you would make it by hand.

So there is no copying, no install step and no second version to keep in sync.
The existing jobs are not prior art to be read and reimplemented elsewhere; they are
the code you are editing. Work with the skills, scripts and modules that are
there: `cron_watchdog.py` is already the alerting path, `shared_lib/runpaths.py`
already owns day-scoped run state and heartbeats, `shared_lib/llm.py` is already the
model client, `analyst.py` the research pass, `cron/executions.db` already records
every attempt with its `scheduled_instant`. Reach for a new module only where the
existing ones genuinely cannot carry the change, and say why in the plan.

The tree is git-backed, which is what makes this safe to work in: every change is
an ordinary staged diff, reviewers read `git diff --cached` here as they would in
any repository, and the gate commit lands in the profile's own history. The two
things that follow:

- **The index must be clean before the board is armed, and yours to leave alone
  while it runs.** `git diff --cached` lists the whole index, so a pending edit of
  your own becomes this lane's evidence and a reviewer will judge the lane on it.
- **The autocommit cron must be paused for the board's lifetime.**
  `sync-hermes-profiles.sh` commits and pushes hourly; the driver's staged index is
  board state, and a cron that commits it takes the gate's decision away and
  pushes a half-finished change to the second workstation. This is the board's one
  human precondition — see its `README.md`.

Nothing here is ever cleared or rebuilt. Six jobs run in this tree and this idea
owns none of their behaviour: it adds a healer around them, makes one pass report
itself, and leaves everything else exactly as it was. No tool in the template
deletes a work directory, so nothing will undo a mistake for you — git in this
repository is the only way back.

### What exists today

The `trader` profile runs six cron jobs, all `no-agent`, all delivering to
Telegram. Three report on holdings (`portfolio-degiro` 10:00,
`portfolio-avanza-private` 12:00, `portfolio-avanza-jfusion` 14:00). One
screens (`gpw-radar`, Saturdays 11:00). Two keep house
(`portfolio-cron-watchdog` hourly, `portfolio-cleanup` 15:30).

The scheduler records every attempt in `cron/executions.db` (`executions`,
`cron_incidents`): `status`, `claimed_at`, `started_at`, `finished_at`,
`scheduled_instant`, `delivery_outcome`. Each digest job touches
`run/<date>/heartbeat-<slug>` on completion, and `cron_watchdog.py` — hourly,
registration-based, four slugs by name — alerts when a job due earlier today has no
heartbeat. Empty stdout is silence, which is also the healthy case.

The digests are rendered by a deterministic engine plus one LLM pass: `analyst.py`
writes a <=150-word note per held ticker into a day-scoped `deep_dive` cache, and the
renderer emits a `## 🔬 Research Follow-up (LLM analyst)` section between
`📈 History & Trends` and `📰 Portfolio News`.

### The three gaps this idea closes

**A non-terminal execution is a dead end.** The gateway's shutdown does not wait for
in-flight script executions (`cron_at_start=0` in the drain log at 11:49:20 on
2026-09-19 while a job had started 59 seconds earlier, then `final-cleanup tool kill
done`), so a restart mid-run leaves the row `unknown` — "whether side effects ran is
unknown" — with no output file and `delivery_outcome=NULL`. There are **12 such rows
since 2026-07-22**, including whole-scheduler batches (2026-08-31 20:34, four jobs;
2026-09-03 20:15, three jobs). Nothing re-runs them. The 2026-09-19 pair
(`gpw-radar` 11:48, `portfolio-avanza-jfusion` 14:04) was replayed **by hand**, hours
later, and delivered correctly.

**Skipped renders identically to empty — and it has shipped days of
complete-looking digests.** The research block is resolved **by model name, never
verified live**, and its absence is reported nowhere:

    llm.py:23           MODEL = os.environ.get("LLAMA_MODEL", "ornith-35b")
    llm.py:119-127      health() is `MODEL in served_ids` — membership, not liveness
    analyst.py:119-121  skip on unhealthy → research = ([], None)
    analyst.py:183      note attribution hardcodes "written by ornith-35b"
    analyst.py:187-206  digest_section / research_section_md return [] when both empty
    degiro_summary.py:750-751  drops the block

`localhost:8081` serves `nex-n25-mini` and `qwen38-27b`; `ornith-35b` and
`muse-glimmer-30b` are gone from the roster (both still declared in `config.yaml`), so
the pass has been skipped, unannounced, for days. Measured against the retained
summaries: **13 degraded files** lack the exact `## 🔬 Research Follow-up (LLM analyst)`
heading, in **two regimes**:

- **The pin window** — jfusion/private 09-17/18/19 and degiro 09-18/19/20, where the
  `deep_dive` cache is empty as well: the pass genuinely did not run.
- **A second writer owns the vault — the sync, not the pipeline.** Both Avanza books on
  09-08 and 09-14, four instances, one signature: the `deep_dive` cache holds **47 notes**
  for the day and the **delivered digest carries the block**, while the **vault file for the
  same date has no `🔬` at all**. The writer is the vault's own git sync: `git reflog` shows
  `merge origin/main: Fast-forward` at **exactly the mtimes those two files share**
  (2026-09-08 20:56:49, 2026-09-14 20:57:14), merging commits authored on the second
  workstation (`wos@axiell.com`) at **16:53:07** and **17:02:26** — hours *before* this
  machine's 20:01/20:41 runs — and each summary's **entire history is that one commit**,
  whose content has no `🔬`. So `intl_summary.py:1072-1077` and `:1503-1504` are excluded by
  mechanism, not by guess: the digest is intact because neither fired, and the locally
  written, correct render was replaced afterwards by a sync fast-forward carrying the other
  machine's copy. That sync is **`obsidian-git`** (vault
  `.obsidian/plugins/obsidian-git/data.json`: `pullBeforePush: true`, `syncMethod: merge`,
  `autoPullOnBoot: true`), which commits as `vault backup: <timestamp>`. Evidence parked at
  `/opt/backup/agents/20260920-112451-research-section-evidence/`. Still unresolved: which
  step of that sync discarded the uncommitted local write (the plugin keeps no log), and
  whether the second machine's 16:53 render was itself section-less for the same pin reason.

The last healthy renders carrying the section are 09-15/09-16. The comments already
record the same shape once before: the retired 16:00 job serving a stale
`analyst-note-latest.md` (`degiro_summary.py:279-283`, `:695-697`). Three mechanisms —
pin, vault render, stale file — one symptom: silence where a section belongs.

**The watcher has the same blind spot it was built for.** `cron_watchdog.py` monitors
four slugs by name and is blind to anything else in the profile — `portfolio-cleanup`,
itself, and any job added later (`portfolio-analyst` was removed from the list in
2026-08-28 and the code comment is the only record). A healer added by this idea
inherits that blind spot unless it is registered, and the watchdog cannot notice a job
that stopped existing. A content-level degradation is invisible to it entirely.

### Constraints that shape any solution

- **Select by capability, not by name.** The replacement for `health()` is a probe that
  picks a served model returning **non-empty content at the real call shape**
  (`max_tokens=600`, thinking off), with `LLAMA_MODEL` as an override only. That survives
  the next roster change instead of dropping the pass.
- **Measured twice, on `analyst.py`'s call shape** (cap 600, real note prompt):

      qwen38-27b, default                 reasoning 635/802 chars · content 745/855 · 17.6/19.5s
      qwen38-27b, enable_thinking:false   reasoning 0/0 chars     · content 825/835 ·  5.2/ 5.9s
      nex-n25-mini, default               reasoning 982/1550      · content 350/431 · 10.5/ 4.9s
      nex-n25-mini, enable_thinking:false reasoning 1139/1550     · content 530/431 ·  4.2/ 4.9s

  `nex-n25-mini` returns content *sometimes*: its reasoning and content share the same
  600-token budget, so it sits at the cap and whether you get a note or a
  `length`/600-token empty result is prompt luck (its server entry at
  `config.yaml:229-235` carries no `--chat-template-kwargs`, so the flag is ignored).
  Coin-flip behaviour at the cap is disqualifying in a cron job. `qwen38-27b` with
  thinking off is deterministic: reasoning empty, a complete ~830-char note, ~5-6s —
  so a book of 40-50 holdings is ~5-8 min, not the 20-40 min the cap-edge behaviour
  suggests.
- **The request shape is already right.** `llm.py:58-60` already sends
  `chat_template_kwargs:{"enable_thinking":false}` and `llm.py:47` already treats
  empty/whitespace content as a failure, so no empty note is ever cached. This is a
  pin-and-probe change, not a request-shape change.
- **One model is resident at a time** (`llama-swap`, `ttl: 1800`): probing two candidates
  in sequence evicts weights for ~5s apiece. Probe **once per book run**, stop at the
  first candidate that answers with non-empty content, and never alongside another local
  consumer.
- **Attribution must quote the model actually used.** `analyst.py:183` hardcodes
  `written by ornith-35b` into the vault, so a capability probe makes that line lie in the
  opposite direction. `llm.py:72` already logs `resp['model']` but does not return it —
  surface it, and let both the note attribution and the new status line quote that.
- **A report is only useful if it is retained — and the sinks have different clocks.** Name
  the sink and its window, or "retained" quietly means "retained until the next prune":

      cache/stocks/<date>/   30d   stock_cache.py:25 MAX_RETENTION_DAYS (via fetch_all_market_data.py:821)
      vault summaries        14d   portfolio_cleanup.py:24-25 KEEP_DAYS (vault_summaries.py:52 keep_days)
      run/<date>/            10d   runpaths.py:32 RETENTION_DAYS (via degiro_summary.py:782)
      cron/output/<job_id>/  50 runs, NOT days — cadence-dependent

  So the longest-lived of the three day-scoped sinks is the `deep_dive` cache, the vault is
  exactly 3 books × 14 days (42 files), and a status artifact parked in `run/<date>/`
  disappears at 10 days — before a two-week outage could be diagnosed. `cron/output/` is
  capped by **run count**, so it is already a long-lived sink for a daily job (~2 months on
  `87ed28ea20bb`) and only days for an hourly one (`ee40dd6115a2`): the digest capture is a
  sink for whatever it prints, at a cadence-dependent horizon.
- **Two sinks, sized separately — and the vault is not a safe one.** The vault body is
  writable by a second writer (`obsidian-git` sync, proven above), so a status line parked
  there is exactly as erasable as the research section was; the vault summary is the
  human-visible surface, not the durable record. The consecutive-skip counter needs its own
  **non-day-scoped, non-count-capped** file **outside the vault and outside its sync** — the
  `ticker_heartbeat` / `catch_up_occurrences` pattern in the profile's own cron state
  (`~/.hermes/profiles/trader`, a different repo) — because a counter in a day-scoped dir
  cannot report history beyond 10-14 days, a counter in `cron/output/` inherits the cadence
  trap, and a counter in the vault can be overwritten by a sync from a machine that ran the
  same job hours earlier. Do not size them together.
- **The pipeline dates everything by `scheduled_instant`, not wall clock.** Verified end
  to end: the 2026-09-19 manual replay at 22:11 wrote
  `portfolio-avanza-jfusion-2026-09-19.md` with frontmatter
  `generated.at: 2026-09-19T12:00:00Z`. A replay is safe days late **only as long as
  that binding holds** — a re-queued row must never be rewritten under the replay date,
  or the vault's retention pass will prune or mislabel it. Prove it with a replay
  executed on a later day, not only same-evening.
- **At most once, and no 03:00 Telegram.** Replaying an execution whose digest was
  already delivered is a duplicate message and a rewritten artifact; a late-night replay
  is worse than the gap it closes. The replay window and the wording of a "window
  closed" report are decisions, not defaults.
- **Do not reach into the scheduler's tables.** `cron/executions.db` is Hermes core's
  schema. Read it; heal by triggering work through the supported surface
  (`hermes --profile trader cron run <job-id>` schedules the job on the next tick), not
  by editing rows the running scheduler may also be writing.
- **The `deep_dive` cache is day-scoped** (`analyst.py:127` read / `:145` write). Clear
  the day's cache when the pin changes **and that day already has notes**; an
  unconditional clear would throw away a healthy day's research. Nothing is at risk
  today (today's cache holds zero notes), so that rule is for the next change, not this
  one.
- **The core defect stays upstream.** The drain and the startup re-queue belong to
  Hermes core, are filed separately (`t_09625ef9`), and must not be fixed by shadowing
  or patching the installed package — in this fork a core change is a carried patch
  asset in the vault applied to the working tree, never a commit on `main`. This lane is
  the profile-side half: it heals and it reports, it does not prevent the kill, and it
  should say so where a reader will see it.
- **The fleet is live while you work in it.** Six jobs fire on their schedule
  throughout; a healer that runs while a job is mid-flight must not mistake "running"
  for "dead". Grace periods are required, not optional.
- **The LLM is serialized** (`shared_lib/llm.py`, one inference at a time against the
  local llama-swap box) and **Yahoo is paced at 1.0s per call**, so replays must be
  serialized too — recovering three dead jobs at once is not three parallel runs.
- **`shared_lib` is coupled by absolute `sys.path.insert`** from every entry point. That
  is the house pattern here and this idea is not a refactor of it.
- **`hermes cron run` needs the scheduler up** (gateway on this host). The healer's
  failure mode when the gateway is down must be visible, not another silent skip.

### Open questions

- **The 09-08 / 09-14 overwrite is identified to the writer, not to the step — keep it
  separate from the pin window.** The writer is the vault's `obsidian-git` sync (fast-forward
  from the second workstation at the files' exact mtimes, proven in the gap above), which
  means the vault body has two producers: this profile's pipeline and that sync. What is not
  provable from what survives is *which step* of that sync discarded the uncommitted local
  write, and whether the other machine's copy was itself section-less for the same stale pin.
  The lane must therefore either make the vault write path non-clobberable (identify and gate
  the writer first) or keep the durable record outside the vault entirely, and hand the
  mechanism on as a filed finding with the evidence path. A fix that only swaps models leaves
  this regime live and silently reopens the class.
- **What is the replay window?** Same calendar day, until the job's next scheduled
  fire, or a fixed horizon — and after that, is a closed window a Telegram line or a
  line inside the next day's digest? Silence is what this idea exists to remove.
- **Which jobs are healable?** Replaying a digest is useful; replaying
  `portfolio-cleanup` or the watchdog is not, and a policy per job is better than a
  hardcoded list that rots (the `portfolio-analyst` comment proves the rot).
- **Does core already expose a sanctioned re-queue?** Establish this first. If a
  supported "re-run orphaned execution" surface exists, use it instead of inventing a
  second mechanism on top of `executions.db`.
- **How does the watcher stay true?** Registration by hand is what failed; decide
  whether the watchdog derives its list from the scheduler's own job table, or the
  healer and the jobs each register in one place.
- **Where does the healer's own heartbeat live**, and what alerts when *it* stops?

### Explicitly out of scope

- **The core drain and startup re-queue.** Filed as `t_09625ef9`; upstream work, and a
  carried patch asset if it lands in this fork at all.
- **The DeGiro pre-run gate.** Fixed and verified (`t_dce7e5eb`): Firecrawl demoted to a
  warning, fatal Yahoo and NBP checks added. Not reopened here.
- **Repairs to the existing pipeline beyond the research pass** — the parkiet
  "recommendations" extraction, the retired `deep_dive.py`, the unwired skills.
- **Execution of any kind.** This job reports. No orders, no position sizing.

### Done means

- **The baseline is exact.** The marker is the literal string
  `## 🔬 Research Follow-up (LLM analyst)`; `## 🎯 Analyst Targets (largest holdings with
  coverage)` — a different, deterministic section still present in 10 of the 13 degraded
  files — makes any fuzzy "analyst" match pass on degraded output. The healthy reference
  is the last renders that carried the section with notes (09-15/09-16); 09-19/09-20 are
  degraded and cannot serve as the comparison, and the comparison is **structural, not
  textual** — their notes are one model's prose, the fixed ones another's.
- **Four regimes render differently:** skipped, ran-and-found-nothing, ran-partially, and
  healthy. The skipped case always carries a status line — in **both** the vault markdown
  and the Telegram digest, e.g.
  `🔬 Research: skipped — model not served (serving: nex-n25-mini, qwen38-27b)` — and the
  note attribution quotes the model id the call actually returned. That line is also
  **persisted in the named sinks** — the digest capture and the vault summary for the
  human-visible line, a non-day-scoped file for the consecutive-skip counter — so a
  degradation stays diagnosable past the 10/14/30-day sweeps and past the
  cadence-dependent digest horizon.
- **Selection self-heals.** Remove the pinned model from the roster and the pass still
  runs on a served model that answers with non-empty content at the real call shape;
  `LLAMA_MODEL` stays an override, not the mechanism.
- **A digest job killed mid-run is detected and replayed exactly once**, and its artifact
  lands under the **missed day's** name and frontmatter — proved by an induced failure
  (the job interrupted, or a synthetic non-terminal row) and by a replay executed on a
  *later* day, not only same-evening.
- An execution that already delivered is never replayed again: the same induced state run
  twice produces one digest, not two.
- A closed replay window is reported where a person will read it; no path in the new code
  ends in silence.
- The healer is registered and listed by `hermes --profile trader cron list`, writes its
  own heartbeat, and `cron_watchdog.py` alerts when that heartbeat is missing — verified
  by running the watchdog with it absent.
- The watchdog's blind spot is either closed (its list derived from the scheduler's own
  job table) or written down with the reason it is not.
- Every existing job still works: the six this idea does not change run unchanged, and no
  job's output shape changes except for the added status line.
- The change's tests are green, run the way the profile already runs its own
  (`skills/investments-daily-portfolio-summary/tests/`, `/usr/bin/python3 -m pytest`), and
  they cover the idempotence, the date binding, and the four render regimes — not just the
  happy path.
- The staged diff is this lane's work and nothing else — no unrelated file, no autocommit
  in the middle of it. What the gate commits is what the plan named.
