> **Scope note (2026-09-11):** the profile work in §6 (persona override, skill trims) and §7 (coder leak) is done — `~/.hermes/profiles` commit `ca09514`, pushed; apollo reset to it. The TI `integration-testing` skill for tester, the `--model` lever and moving `kanban-worker` into this repo are deferred. Everything else below is implemented by `docs/superpowers/plans/2026-09-11-kanban-review-fixes.md`.

# Kanban review — prompts, ideas, skills, coder leak (2026-09-11)

Scope: `mission/card-bodies/*`, `mission/{lanes,file_lanes,run}.py`, the three boards' ideas, the five
Hermes kanban profiles (SOUL.md persona, enabled skills), and the last recorded run
(`boards/minimal-development/runs/`, 2026-09-10 23:04–23:31).

**Dating caveat — read first.** The last run's cards were filed with *older* bodies: P1 got the
verify-everything clause ("every statement … you must have VERIFIED — by running it"), I1 had no
TOOLCHAIN INVENTORY / MISSING TOOLCHAIN, RVp1's body was 1.8 KB (now 2.8 KB). The clause was inverted
in `4c445f5` (23:53, after the run) and the TECH STACK split added in `dbe41ae`. The idea in
`lane-1.md` also changed after the run (one HTML file → ES modules + Jest + run.sh).
So: **the current researcher/manager split and current RVp criteria have never been exercised by a
run.** Evidence below is labelled "run showed" vs "current text says".

**Null result.** On all preserved evidence, plan review has not been the bottleneck on this board —
runtime ceilings have: three driver halts on 2026-09-10 (P1 22:56, P1 23:12, TW1 23:23, all at the 4 m
limit), and RVp1 passed first time. `runs/halt.txt` ("Gp1: rounds exhausted", 23:50) is not backed by
anything in `driver.log`. The only recorded REJECT texts (ERRORS #15: pytest count from memory, stale
staged-state, broken pathspec) predate the current bodies. §1 is therefore reasoned from the prompt
texts, not from observed rejections; §3.6 and the ceiling (§5) are backed by the run.

---

## 0. Top fixes

Backed by the run, do first: stop halting the driver on the first `timed_out` while retries remain
(§3.6), and give the smoke board an idea that fits its ceiling (§5).

Then, ranked by expected effect on first-attempt plan PASS:

1. **One shared plan-acceptance checklist**, injected verbatim into p-body (self-check before
   completing) and rvp-body (the only REJECT grounds). Today the manager never sees what RVp checks. (§1)
2. **Neutralise the writing-plans template in p-body** — its `Commit` step, the `For agentic workers:
   REQUIRED SUB-SKILL` header line, and the `Execution Handoff`. Run showed the header line shipped in
   the plan. (§1.3)
3. **Mechanical PLAN-ONLY check**: before TW, `git diff --cached --name-only -- <WORKDIR>` must be empty.
   Run showed P1 created + staged the deliverable, RVp1 passed it anyway. (§1.4)
4. **Replace the transient/inline machinery with one rule: scratch lives in /tmp, never under WORKDIR;
   deliverables = union of the plan's Files blocks (tests included).** The current rules are a fossil
   of the old one-file idea and are mechanically broken (run showed 2 staged "transients" → PASS). (§1.5)
5. **Fix the engine bugs that make prompts lie** — revision cards are filed with raw `<PLACEHOLDERS>`,
   the RVp re-review is told to act "as a gate-holder", the idea REWORK loop can never fire. (§3)
6. **Drop `--skill brainstorming` from I; fix the four kanban personas** — they, not the card bodies,
   are the real researcher↔manager duplication. (§2, §6)
7. **Researcher owns the verification recipe** (runner + command per success criterion), so the
   manager has no gap to probe. Run showed Findings said "no tooling fact needed" → planner probed Node. (§2.3)
8. **minimal-development idea contradicts itself** ("page not tested" vs page behaviours in Done means)
   → REJECT baked in. Plus a 4 m ceiling that halted the driver three times that evening. (§5)

---

## 1. P ↔ RVp contract (the first-attempt question)

### 1.1 The manager cannot satisfy criteria it never sees
RVp rejects on things p-body never states: "every plan task has a RED-then-GREEN step" (rvp (c)),
"a plan with no cleanup step is a (d) finding", "product files staged before the first tester card",
"files land under this lane's own target paths". Reviewer persona (SOUL.md) adds a fifth: "check …
that the stated risks are the real ones" — no card asks for a Risks section.

**Fix:** `mission/card-bodies/_plan-checklist.txt`, substituted as `<PLAN_CHECKLIST>` into both
bodies by the one render helper (§3.1). Underscore, not hyphen: `test_card_bodies.py:24` matches
placeholders with `<[A-Z_]+>`, so a hyphenated name would go unguarded — add it to
`ALLOWED_PLACEHOLDERS`. p-body: "before completing, walk every item; fix, don't
explain". rvp-body: "REJECT only on a numbered item; cite it; anything else is a NOTE in a PASS".
The last sentence is what bounds the reviewer (and neutralises persona-injected criteria).

Draft:

```
PLAN ACCEPTANCE CHECKLIST — the plan passes when every item holds.
1. Header: Goal, Architecture, Tech Stack, Spec: <REFINED>; a Global Constraints section.
   No "For agentic workers" line.
2. Coverage: every SCn in <REFINED> Success criteria is named by >=1 test step ("covers SC2")
   or is marked there "checked: manual at Gc". Nothing outside Scope-in. Scope-out and
   Assumptions are not gaps.
3. Stack: every tool in Tech Stack cites a Findings line (Fn) that shows it present; every Run
   command is the one the refined Verification recipe gives.
4. Tasks: Files (exact paths under <WORKDIR>), Interfaces, and steps tagged [TW] (write test,
   run -> FAIL with the stated message) or [C] (code, run -> PASS). A task with no behaviour
   (scaffold, config) is folded into the task that needs it.
5. Real code in every code step; no TBD/TODO/"similar to Task N". A fact Findings do not cover
   is written "UNVERIFIED — executor confirms by: <command>" — allowed, not a placeholder;
   never allowed for a Tech Stack tool.
6. Stage-only: no step commits, branches, pushes. No kanban mechanics (attach, complete, card ids).
7. Scratch only in /tmp. Deliverables = union of the Files blocks; nothing else under <WORKDIR>.
8. Index: before TW runs, `git diff --cached --name-only -- <WORKDIR>` is empty (the plan card
   produced only <PLAN>).
```

### 1.2 Contradictions inside the current criteria (current text)
- rvp-body.txt:9 "A plan with **no cleanup step** is a (d) finding" — unconditional. A plan that
  creates no transient file must still invent a cleanup step or be rejected. Manufactured finding.
- p-body.txt:19 "deleted by **the task that created it**" vs rvp-body.txt:9 "deleted by **a later
  task**" vs writing-plans "fold setup/scaffolding into the task that needs it".
- rvp-body.txt:8 (c): opening sentence "**every** plan task has a RED-then-GREEN step" is broader than
  (c)'s own enumerated finding list — inconsistent within the paragraph; a cleanup/scaffold task is
  ambiguous.
- p-body.txt:15 mandates `UNVERIFIED — executor confirms by:` lines; rvp-body (b) "no TBD/TODO/
  placeholder" does not say those are legal → reviewer may read them as placeholders.
- "this lane's own target paths" (rvp (d), rva (c)) is defined nowhere. Run showed RVa1 PASS while
  `mission/card-bodies` edits were staged: "lane-scoped boilerplate, pre-existing".
- p-body.txt:15 "flag it **for the idea gate**" — impossible: Gi is done before P starts. Say: mark
  UNVERIFIED, list it in the result so Gp sees it, or `block --kind needs_input`.
- p-body.txt:13 "must map 1:1 onto them (TW, C)" while the template interleaves test→code per task;
  TW writes *all* tests, then C *all* code. The [TW]/[C] step tags (item 4) make the split explicit.

### 1.3 writing-plans skill vs the lane (P is filed with `--skill writing-plans`)
Template parts that fight the card, none neutralised in p-body:
- `Step 5: Commit` with `git commit -m …` → rvp (d) REJECT. (Run showed the manager rewrote it as
  "Do NOT commit." — p-body never asks for that; its hard rule covers the card, not plan steps.)
- Header line "REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development …" — **run showed it in
  the plan (line 3)**; TW/C read the plan and are invited to dispatch subagents.
- "Execution Handoff: offer execution choice … Which approach?" → in a worker: a question to nobody,
  or starting execution (the PLAN-ONLY violation p-body already cites).
Add to p-body: "Using writing-plans: omit the agentic-workers line; replace Commit with nothing
(staging is the card's job); skip Execution Handoff."

### 1.4 PLAN ONLY is asserted, never checked (run showed)
Plan Global Constraints: deliverable "created and staged; verified `git add -f`"; Task 2 Step 6
"already `A`, staged at plan time". TW1: "the HTML deliverable already passes them (already staged by
another card)" → RED-first void for Task 2. RVp1: "(d) stage-only — … only `git add -f` of
roman-evaluator.html" → **PASS**. Make it mechanical (checklist item 8), ideally in the driver before
RVp unblocks, not in reviewer prose.

### 1.5 Transient/inline machinery = one old idea baked into the generic engine
p-body CLEAN DELIVERABLE ("extracted modules … inlined"), c-body TRANSIENT FILES ("inlines/merges a
temporary extract"), rva (a), rvp (d) all encode the old "one HTML file only" idea's workaround
(extract module → test → inline → delete). It cannot work: TW/C hard rules *require* staging what they
create, so "transients" end staged. Run showed plan Step 5 `rm` (no `git rm --cached`) → RVa1 PASS with
"one non-blocking flag: two transient work files are staged" → Gc "5 files staged": plan, refined,
the HTML and both "transients" (intended under work/: the HTML only).
rva-body.txt:6 "Blocking only if the plan never scheduled cleanup at all" reads inverted, and a
binary PASS/REJECT has no "non-blocking finding".
**Fix:** delete all four passages; one rule in the checklist (item 7).

### 1.6 Verdict cards — incomplete must mean REJECT
rva has "BLOCKING CARD, NOT DOING THE WORK"; rvp/rvc do not. The kanban-worker skill (in every profile)
says "Hit the budget? Complete with what is verified … complete-with-caveats beats a timeout" — on a
verdict card that yields PASS-with-caveats and `verdict_token` opens the gate. Add to all three
verdict bodies: "Cannot finish every check → `REJECT: incomplete review — <what is missing>`."
Also: reviewers write `/tmp/<id>.review` but nothing attaches or reads it — attach it; the revision
card should read it (findings are truncated to 1200 chars, run.py:583/600).

---

## 2. Researcher ↔ manager duplication

### 2.1 The bodies narrate each other
i-body.txt:12, :16, :20, :36 describe what the manager does; p-body.txt:9, :15 describe what the
researcher does. Every rule exists twice, and has already drifted: README §4 and ERRORS.md #15 still
credit first-time PASS to "NO UNVERIFIED CLAIMS" meaning *run everything* — the current clause means the
opposite. **Fix:** each body states its own inputs, outputs and done-condition. The contract ("Findings
is the only source of environment facts") lives once — in the refined-idea template the researcher
fills and the manager reads.

### 2.2 The real duplication is skills + personas, not the bodies
- **I is filed with `--skill brainstorming`** (lanes.py:20). Its checklist: ask the user questions one
  at a time, propose 2–3 approaches, present a design for approval, write + commit a spec, then invoke
  writing-plans — i.e. design and planning, the manager's job, with a human who is not there. A large
  share of i-body (REFINEMENT IS NOT DESIGN, IF THE IDEA IS ALREADY CLEAR, SIZE THE WORK, THE FILE
  THAT SHIPS IS THE BEST PASS) exists to fight it. Drop the skill, then cut those paragraphs.
- **manager SOUL.md**: "produce a written implementation plan using the **brainstorming** and
  writing-plans skills" (= re-refine the idea), "file a research card and wait", "decompose the approved
  plan into cards, wire dependencies" (= the driver's job).
- **researcher SOUL.md**: "enumerate the competing framings … and the trade-offs" (= design);
  "submit the dossier for reviewer verdict through the same-card review lifecycle" (no reviewer before
  Gi; `request-review` ≠ `complete`).
- **tester/coder SOUL.md**: "commit them on the card's test branch", "commit logical units" vs stage-only.
- **reviewer SOUL.md**: "stated risks are the real ones" — an extra plan criterion (§1.1).
Fix (outside the managed block): one line per persona — "On a kanban card the card body is the entire
contract and overrides this section: no branches, commits, request-review or card filing." Better,
rewrite the role text to match the board.

### 2.3 Findings gap → manager probing (run showed)
Refined Findings: "No browser/tooling fact needed". Plan Tech Stack: "Node 22 (verified v22.22.2) runs
verification via a small vm-based DOM shim"; P1 result "verified live against Node 22". Cause: the
toolchain inventory is keyed to tools *the idea* names; the test harness is implied by *the lane*, not
the idea. Under today's p-body the manager may not probe, so the same gap would now surface as a
downstream failure instead. **Fix:** refined template gains a **Verification recipe**: for each SCn,
the runner, version, exact command, present/absent — or "manual at Gc". Researcher owns it; manager copies.

### 2.4 Copy by reference, not by value
i-body tells the manager to copy Findings and Success criteria "straight into the plan" — two copies of
the contract. Number them (F1…, SC1…) and cite IDs; RVp coverage becomes mechanical (checklist 2–3).

Proposed refined-idea shape (headings exactly as the Gi gate parses them, run.py:356-365 — i-body today
gives a bullet shape and never says "## headings"; a researcher writing **bold labels** stalls Gi forever):

```
## Problem
## Scope            (In: … / Out: …)
## Open questions   (or: none)
## Assumptions
## Findings         - F1: <fact> — evidence: `<command>` → `<output>`
## Verification recipe   - SC1: `<command>` (runner vX, present) | manual at Gc
## Prior art        (or: none)
## Success criteria - SC1: <observable assertion>
```

---

## 3. Engine bugs that make the prompts lie (verified)

1. **Revision/re-review cards get raw placeholders** — `file_revision` (run.py:272, :282) and
   `file_coder_revision` (:679, :688) `open().read()` the body and never substitute. Simulated with `kb`
   stubbed: P1-rev-1 carries `<BOARD> <IDEA> <N> <PLAN> <REFINED> <WORKDIR>` literally; RVp1-r2, C1-rev-1,
   RVa1-r2 likewise. Also `--workspace dir:{REPO}` instead of WORKDIR, hardcoded 60m/45m ignoring
   `max_runtime`, no `--skill`. Fix: one `render_body(file, lane, board)` used by file_lanes and run.py.
2. **RVp re-review told to act as a gate-holder** — run.py:283-285 appends "complete this card exactly
   as a gate-holder would" to `rvp-body.txt` too. A re-review without PASS/REJECT → `verdict_token` ""
   → Gp waits forever, no further round. (`file_coder_revision`'s text is correct — contrast.)
3. **Idea REWORK loop can never fire** — gi-body tells the human `REWORK:`; tick() tests
   `verdict_token(v) == "REJECT"` (run.py:612) and `verdict_token` only knows PASS|REJECT (:336). Also P
   is unblocked in step 1 (Gi done) before step 2 reads the verdict — race even once fixed. No test
   covers REWORK. Fix in the idea loop itself (match `REWORK` at :612), not by widening the shared
   `verdict_token`, which also feeds the gp/gc `!= "PASS"` checks.
4. **REJECT without the literal `REJECT:`** → `v.split("REJECT:", 1)[1]` IndexError (run.py:583, :600)
   → the catch-all logs it every 20 s, the lane stalls. verdict_token's own docstring says reviewers
   drift in format.
5. **Findings truncated to 1200 chars** (:583, :600) — long numbered REJECTs arrive partial → another
   REJECT.
6. **Driver halts on the first `timed_out` even with retries left** (`_exhaustion_event`, :806-823).
   Run showed three halts in one evening (P1 22:56, P1 23:12, TW1 23:23), each a manual restart.
7. **Integration lanes**: RVa REJECT leaves TI's parent (RVa) done → TI runs concurrently with C-rev;
   an RVc REJECT loops through RVa-r only, so the final suite review is never repeated.
8. **Path forms mixed** (latent, not broken): `<REFINED>` repo-relative, `<PLAN>` absolute
   (file_lanes.py:93-94), workers' cwd = WORKDIR. Run's refined.md landed correctly, but the plan
   hardcoded `/opt/projects/...` and "Run (from repo root)". Make every placeholder absolute.
9. kb() error text truncated to 200 chars (run.py:111) — the live driver.log shows the real error hidden
   behind the "hermes update … did not restart running gateways" banner. `hermes gateway restart`
   is the operational fix today.
10. Tests: `test_rework_loop.py:153` is a tautology (`… == "REJECT" if False else True`);
    `test_plan_body_requires_verified_claims` checks the clause *text*, not its meaning.

---

## 4. Other card bodies
- i-body: `LOOP_COMPLETE` (:24) is a `/loop` leftover (ERRORS O5 says /loop is gone); `--goal`'s judge
  reads title/body. Give every worker body (I, P, TW, C, TI) one explicit `DONE WHEN:` line instead.
- Results: run showed I1 and C1 completed with an **empty result** despite bodies mandating one.
  Put the exact `complete … --result "…"` command in every body (TW/C/TI have only the shape).
- c-body.txt:9 "Keep <WORKDIR>/plans/" — plans moved to runs/artifacts; stale.
- ti-body lacks TOOLCHAIN BOUNDARY and a scratch rule; rvc lacks "reproduce" and the contract reference.
- Toolchain boundary exists in 4–5 differently-worded copies (i/p/tw/c/rvp). One fragment.
- rva: add "(e) TW's tests unmodified by C" (c-body rule 3 is otherwise unchecked).

## 5. Ideas (boards) — "only ideas change"
- **minimal-development/lane-1.md:66 vs :102-105**: "the HTML page itself is not tested" vs Done means
  requiring page behaviours in both launches → rvp (c) "criterion with NO test" or (a) "extra" either way.
  And `./run.sh --headless --dump-dom` cannot click Evaluate. With the engine's "checked: manual at Gc"
  (§2.4) the idea just marks those lines manual.
- Ideas restate engine policy (lane-1.md:68-81: "preferred stack is whatever exists", "never installed…
  names what is missing… fails", "project-level packages may be fetched") — duplicates of i/p/tw/c.
  Drop from ideas; ideas carry what, why, preferences, done.
- Ideas hardcode `boards/minimal-development/work/...` — write paths relative to the work dir so an
  idea is portable between boards.
- The smoke board is no longer minimal (npm + Jest + optional Bootstrap + Chrome + run.sh, two launch
  modes) with `max_runtime: "4m"`; README.md:199 still says "a single Python function … no
  dependencies". Keep the smoke idea trivial; give the roman page its own board.
- `boards/minimal-development/work/roman-evaluator.html` is **tracked** (added in `4c445f5`) inside a
  gitignored scratch dir → every run starts with the deliverable present. `git rm --cached` it.
- portfolio-engineering: the idea *requires* writing `~/.hermes/profiles/trader` and registering a cron
  job; engine rules forbid changing the machine ("services, daemons", c-body — a cron job arguably is
  one) and anything outside "this lane's target paths" (rvp/rva) → REJECT by construction. Engine-level fix: board.json `targets: [...]` = extra write roots
  the reviewers treat as lane paths.
- test-driven-development (2 lanes): nothing commits under auto-gates, so lane 2 inherits lane 1's
  staged files and rvc (b) "this lane's files and nothing else" fails. Lane path sets must come from the
  plan's Files blocks, not "whatever is staged".

## 6. Skills per role — add a few, remove more
Mechanism: `--skill` is per card and repeatable (`hermes kanban create --skill a --skill b`);
`skills.disabled` is per profile and hits every use of that profile. Prefer the card flag.

| card | today | suggestion |
|---|---|---|
| I researcher | `brainstorming` | **drop** (§2.2). context7-helper / vcs-helper already enabled for Prior art |
| P manager | `writing-plans` | keep + three neutralisers (§1.3). Never brainstorming |
| RVp | — | none (verification-before-completion would push re-running env checks rvp forbids) |
| TW | `test-driven-development` | keep |
| C | — | none needed; make sure the hub TDD is not shadowed in coder (§7) |
| RVa / RVc | — | optional `verification-before-completion` (= "reproduce, don't skim") |
| TI | — | **the one real gap**: `integration-testing` exists in researcher and coder, not tester. Review it (skills.sh, third-party), add to tester, `--skill integration-testing` on TI |

- manager, reviewer and tester have brainstorming, writing-plans, subagent-driven-development,
  executing-plans, using-git-worktrees, finishing-a-development-branch enabled (reviewer disables only
  `plan`, `web-pentest`); researcher already disables all of them except brainstorming. For stage-only
  verdict/plan cards those are risk, not help. Disable per profile **only if** the profile serves nothing but this board — manager
  holds `hermes-kanban-missions`, `kanban-mission-board`, `hermes-multi-profile-ops`, which looks like
  broader ops use.
- `kanban-worker` is a private, identical copy in five profiles, and stale ("~30 iteration budget";
  goal ceiling is 40). It is kanban-specific → ship it with this repo (project scope, `hermes skills
  trust`; verify discovery from a `boards/<slug>/work` cwd first) and add the verdict-card rule (§1.6).
- researcher: root `autoresearch` (skills.sh) shares a name with the hub manual skill → a long
  autonomous research loop is model-visible on a 4 m card.
- Model lever: all five profiles run `glm-5.3-flash`; `hermes kanban create --model/--provider` pins a
  card. P and RVp are where a stronger — or at least a *different* — model buys first-attempt acceptance
  (same model reviewing itself shares its blind spots).

## 7. Coder leak — confirmed
**Root cause:** `~/.hermes/profiles` is a git repo with hourly autocommit + push between hosts.
`830ebaa` (2026-09-10, "profiles autocommit **apollo**", +768 files) re-added `coder/skills/**` that
this host removed in `f64f783` (2026-09-06, "record the hub migration … the parked wiki-* wrappers"),
plus `coder/plugins/sync-claude` (retired mirror; present, not enabled — inert). Other four profiles:
nothing from that commit; researcher's root `autoresearch` is the one name clash (§6).

Enabled and model-visible in coder now:

| what | count | examples | handled by |
|---|---|---|---|
| hub **manual** skills/wrappers mirrored as skills (`synced_from: claude-command/cli`) | 36 | wiki-*, save, skill-sync, audit-vault-config, review-pr, owasp-review, firecrawl, defuddle, grill-* | `/skill-sync` check 12 (dry-run: "park the mirrored wrappers") |
| copies of hub **automatic** skills (`synced_from`) — shadow the hub (local wins) | 16 | brainstorming, writing-plans, TDD, using-superpowers | not itemised by the dry-run — check the apply output |
| retired mirror residue, no hub source | 13 | understand-*, crawl4ai, postman, helper-pattern, ingest-project | `/skill-sync -p` check 21 (dry-run lists all 13) |
| **marker-less** shadows of hub names | 13 | software-development/{test-driven-development, systematic-debugging, requesting-code-review, using-git-worktrees, finishing-a-development-branch, rtk-tdd}, root finishing-a-development-branch, root autoresearch, autonomous-ai-agents/ponytail, development-tools/{context7-cli, playwright-cli, semble, semble-helper} | **not** prune — sync lists TDD/using-git-worktrees as "skills of its own". Manual park |
| Hermes bundled categories (creative/, mlops/, apple/ …) | 69 | 68 disabled, `hermes-agent` enabled | inert bloat; park with the rest if wanted |

Why it matters here: `skill-sync` (applies repairs by default) and `wiki-save` are auto-invocable from
a kanban coder card; `.skills_prompt_snapshot.json` is 102 KB (researcher 13 KB) — paid on every C card;
C's TDD may be the bundled or stale copy, not the hub's.

Removal (proposed, not executed):
1. Dry-run already done (read-only): `HERMES_HOME=~/.hermes/profiles/coder
   ~/.agents/manual-skills/skill-sync/scripts/skill-sync.sh -n -p` → 16 repairs, 2 human findings.
   Apply with `-p` (parks, never deletes — RULES rule 8: never hand-remove mirrored content).
   The same run also applies checks 12/13, including "mirror the hub into hermes:coder (skills,
   agents, commands)" — read the 16 PLAN lines in `coder-prune-dryrun.txt` before applying.
2. Marker-less shadows: manual park under `/opt/backup/agents/<ts>-coder-skill-leak/` (Backups rule).
   **Never `skills.disabled` for a shadow** — name-keyed, filters the hub copy too (google-workspace).
3. **Same on apollo before its next autocommit**, or the +768 returns. Cleanup on this host is itself
   autocommitted and pushed.
4. Side note: check 21c reports the Hermes category dirs (apple/, autonomous-ai-agents/ …) as "no
   SKILL.md — nothing loads it" — the loader reads `<category>/<name>/SKILL.md`, so likely a false
   positive in the check.

## 8. Doc drift (one line each)
README:42 vs :92 plan path (`work/plans/…` vs code `runs/artifacts/lane-<k>/plan.md`);
README:160-163 "refined idea … tracked" vs runs/ ignored; README ASCII `lane-1-refined.md`;
README:478 and ERRORS O5 `--goal-max-turns 20` vs lanes.py:83 `40`; README §4 and ERRORS #15 describe
the inverted clause; render-flow.py:40 "failsafe ITs" (Maven, in the generic engine) and its own label
table already drifted from `lanes.LABELS` ("integration tests", "reviewer verdict").

## 9. Suggested order
1. Engine: render helper (§3.1–2), REWORK token + race (§3.3), REJECT parsing (§3.4), halt-on-gave_up (§3.6).
2. Contract: checklist fragment + p/rvp wiring (§1.1), writing-plans neutralisers (§1.3), /tmp rule (§1.5),
   index check (§1.4), refined template with IDs + verification recipe (§2.3–2.4).
3. Skills/personas: drop brainstorming on I, persona override line, TI integration-testing.
4. Coder: prune + manual park, on both hosts.
5. Re-run minimal-development with a trivial idea and a sane ceiling; then the roman page on its own board.
