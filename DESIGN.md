# kanban — design and internals

The reasoning behind the board, the driver's behaviour in detail, the known traps and
the timing instrumentation. The operator's guide — boards, prerequisites, how to
create and run a board, run records, operational rules, gate discipline — is
[README.md](README.md); section numbers (§N) refer to it.

## What the board enforces

**Plan-first, stage-only, every lane gated.**

| rule | where it lives, and why |
|---|---|
| Workers STAGE only (`git add -- own paths`), never commit or push | card bodies' HARD RULES; checked by the reviews. The commit is the human's authorization record (§6) |
| Per-card patch = OWN paths only (`git diff --cached -- <own paths>`) | card bodies — a bare diff bundles every earlier card's staged files |
| The board's only git writes are stage and unstage | `mission/run.py`: `git add` by workers, `restore --staged` for its own leftovers. Never commit, branch, checkout, reset or push: a work directory that moves under a live run is REPORTED, not corrected (see [work directory pinning](#work-directory-pinning)) |
| Nothing is deleted — not `work/`, not a run directory | `mission/reset.sh` archives cards and unstages; deleting either tree is a human's own `rm`. `work/` may be the input of a follow-up fix, and an old run is the evidence for why something wedged — no tool has an opinion about when either stops being useful |
| One run, one directory — `runs/<run-id>/`, minted when an idea is armed | `run.py` `mint_run`; `runs/current` names the live run. `create-board.sh` mints the run it files into and REUSES one a previous filing left unstarted (`file_lanes.next_run_key`) rather than adding a second; a directory any driver has written into is never reused. A fresh directory cannot hold a previous run's hand-off, so stale-document safety is a property of the paths rather than of a deletion someone must remember |
| A run's directory disappearing stops the board | `run.py` — nothing here removes one, so a missing `runs/<run-id>/` is someone else's `rm`: the driver halts instead of recording into a fresh directory and pointing `current` at evidence that is gone |
| Options are validated before anything is filed — manifest and idea headers alike | `mission/board_schema.py`, at all three doors: `create-board.sh`, `start-board.sh`, and the driver when a Triage card is armed (findings go back as a comment on that card). One declaration of the option set, because a second one drifts |
| Nobody commits before the gate — not even the driver | gate cards; `auto-gates` completes gates with "NOTHING COMMITTED" |
| Lane N+1's root is parented to lane N's code gate | `mission/lanes.py` — the board itself is the sequencer, no orchestrator |
| The plan card never sees an unreviewed idea | `lanes.py` — `I` is the lane root and `Gi` stands between it and `P`. With `refinement: false` the plan card is the root and plans from the raw idea (see [refinement](#refinement-off)) |
| Every hand-off is a file, never a card comment | `runs/<run-id>/artifacts/lane-<k>/refined.md`, `…/plan.md`, patches — written to `runs/<run-id>/scratch/<card-id>/` and attached to their card BY THE DRIVER, never staged; the only thing a card stages is the lane's own work |
| Every card's evidence is its `git diff --cached` patch, attached to the card — and on a lane the plan proves was already satisfied there is nothing to attach: `NO CHANGE:` in the result is the evidence, and the empty-patch ceremony is retired (doc chain F5) | card bodies; `mission/doc-chain.py` |
| A worker never attaches: it writes its hand-off into its own scratch directory, and the driver attaches every `run.HANDOFF_NAMES` file it finds there once the card is done | `run.attach_hand_offs`, `_worker-contract.txt` — Hermes fences dispatcher-owned children, so `hermes kanban attach` is refused inside a worker, and the `kanban_attach` tool takes the bytes INLINE. That made a worker copy kilobytes of base64 out of its own tool output: on is-even (2026-09-13/15) four local-model cards wrote a correct `refined.md` and all four then died in that copy. An empty file is not attached, and a failed attach is retried on the next tick |
| Verdicts go in the result field | review card bodies (`_result-field.txt`) |
| The plan is judged on what it was told | `mission/card-bodies/_plan-checklist.txt` — the plan card's self-check and the plan review's only REJECT grounds |
| Rules every worker shares exist once | `mission/card-bodies/_worker-contract.txt`, included as `<WORKER_CONTRACT>` (see [profiles](#profiles-and-the-worker-contract)) |

## Lane shape

Without integration tests the plan gate releases the unit-test card and the
implementation card TOGETHER, and the review waits for both:
`I → Gi → P → RVp → Gp → (TW ∥ C) → RVa → Gc`.
With integration tests, `TI` and a final `RVc` follow the code review, before `Gc`.
Optional levels take their cards with them, archived when the lane opens:

- no unit tests — no `TW`; the `TW → RVa` edge is unlinked and the review waits on `C`
  alone. `C` needs no surgery: its parent is the plan gate in the graph itself.
- no integration tests — `TI` and `RVc` are archived (`RVc` reviews nothing else),
  `RVc → Gc` is unlinked and `RVa → Gc` linked, because archiving a card does not drop
  its dependency edge and the gate would wait forever on an archived parent.
- `refinement: false` — `I` and `Gi` are archived and `P` is the root.

`TW ∥ C` is the template's one deliberate fork. The plan already carries the real
code (the checklist forbids a TBD), so the coder never waits on a test file, and
"the tests are green" is not the lane's done criterion — the review verdict is, and it
re-derives the suite itself. The RED observation (a test failing while the
implementation does not exist) is a prediction in the plan, re-derived by `RVa` from
the two patches (`mission/card-bodies/rva-body.txt`, check f).

Three gates per lane, in the order the cost of being wrong falls: `Gi` (is this the
right idea?), `Gp` (the right plan?), `Gc` (the right code?). Fixing an idea costs one
card; fixing a plan built on a bad idea costs the lane.

### Refinement off

`refinement: false` suits an idea that is already specified. The give-ups are real,
so the bodies state them: the human's first veto moves from the idea gate to the plan
gate, and with no researcher the plan card is the only card that can establish a
fact — on those lanes it may probe, and it cites every fact it relies on. The idea
file must still say what done means: its `### Done means` section is what the code
gate judges against.

## Rework loops

Three loops, one shape — newest verdict → revision card + re-check card, linked to the
gate, bounded, then escalation:

```
RVp(n)     ──REJECT───────→ P(n)-rev-N          → RVp(n)-r(N+1) ──PASS───→ Gp(n) opens
RVa/RVc(n) ──REJECT+OWNER─→ (C|TW|TI)(n)-rev-N  → RVa(n)-r(N+1) ──PASS───→ Gc(n) opens
Gi(n)      ──REWORK───────→ I(n)-rev-N          → Gi(n)-r(N+1)  ──PASS───→ P(n) opens
```

- **Cap:** all three loops read `lanes.max_reworks` for the lane — `max-reworks` from
  the idea header or manifest, default 3. It is distinct from `max-retries`, the engine's per-card ATTEMPT budget,
  which is pinned to 1 because a failed card is final — the board's only retry is a
  review that sends work back. The review and gate bodies say "up to the board's rework
  cap", never a number: a lane's cap comes from its idea header, which does not exist
  yet when the cards are filed (`test_no_body_hardcodes_a_rework_cap`).
- **Live-guard:** a round is filed only when the previous round's cards are all done
  (`rework_hold`). A REJECT as the latest verdict alone does not trigger filing, or
  every round would be filed at once.
- **Downstream hold:** the card after a live round waits on the graph, not on a block:
  Gp's parents include the plan round (`lane_graph`), TW and C wait for Gp, and P waits
  for the idea gate's verdict (`held_by_verdict`). A `block --kind dependency` would not
  hold — the engine sends it to `todo` and `recompute_ready` promotes it back as soon as
  the parents are done (`kanban_db._route_block`).
- **Rendering:** a revision card is rendered exactly like the card it revises — same
  paths, workdir, ceiling and skill — plus the numbered findings and a pointer to the
  full verdict.
- **Owner:** the code loop's revision goes to the card the verdict names
  (`OWNER: C` / `TW` / `TI`). The implementation review judges the C patch and the TW
  tests in one pass, and C corrects a TW test only under c-body hard rule 3 (TW `done`,
  evidence, a separate `test-fix.diff` that RVa checks against the plan), so a test
  defect C did not correct, filed against C, could never be fixed. No usable owner
  line means `C`.
- On a lane with integration tests the code re-review also repeats the final review,
  and `TI` waits until the newest implementation verdict is PASS. `P` stays parked while
  the newest idea verdict is REWORK.
- **Pins:** a re-review is a review, so it carries the same `model_override` as the
  review it repeats, and a revision card carries the model the card it repeats ran on
  (`lanes.model_args` with the lane's own header pair); otherwise a rework round would
  silently drop back to the worker's profile model.
- **Plan revisions** carry turn-diet guidance: targeted patches to the existing file,
  re-verify only the fixed lines. Framed as "re-verify everything", a plan fix dies at
  the turn ceiling.
- **Escalation:** when the rounds are exhausted the driver comments `ESCALATION` on
  the card, records it in `verdicts.jsonl`, and halts the board ([stall classes](#stall-classes)).

## Profiles and the worker contract

The graph addresses profiles, not roles (`lanes.assignee_for`), so a role is only as
distinct as the profile behind it:

| profile | cards |
|---|---|
| `researcher` | `I` and its revision rounds |
| `coder` | every other work card: `P`, `TW`, `C`, `TI`, `RVp`, `RVa`, `RVc` and their rounds |
| `trader` | no card — the domain authority `portfolio-engineering` builds into |
| — | gates: a person answers them with a `PASS` comment (or completes them), or the driver when `auto-gates` is on |

One work profile is what you maintain; each job is kept apart by the CARD that names
it — a review runs in its own session, from the plan alone, with its own patch —
rather than by a second profile to keep in sync. `create-board.sh` derives the
profiles a board needs from its manifest (`lanes.required_profiles`), and a manifest's
`assignees` remaps a role per board. A card whose assignee is not a profile is never
spawned and nothing reports it, so a role that loses its profile must be remapped in
the same change.

**Two models, one precedence.** `model`/`provider` is the board's WORK model: filed on
every card it files, board-level with a per-lane header override, and re-pointed onto a
lane's parked cards by `run.open_lane` when the idea names its own pair (a board files
IT-complete, before any idea exists). `model_override`/`provider_override` — the engine's
own task-property names — is the REVIEW pin, board-level only, and it wins wherever it is
set: the review cards (`lanes.JUDGE_CODES` = RVp, RVa, RVc, and their rework rounds)
carry it, author cards run the work model, and the shipped boards pin `glm-5.3-flash` on
`opencode-go` so the model that reviews is not the model that wrote the work. Neither is
required: omit both and no flag is filed, every card running its profile's own model.

Measured 2026-09-13 and 2026-09-15 (`boards/is-even` README has the full record): four
cards on local models (`ornith-35b`, then `qwen38-27b`) filed and dispatched correctly,
each worker really carried its `-m … --provider llama-swap`, and each wrote a correct
`refined.md` in minutes. All four then died handing that file to the card, in the
inline-base64 copy the old contract forced — not on the work, and not on tool-call
formatting, which was valid JSON in every one of the 77 calls. The driver-side attach
above removes that copy, so a local model as a worker is unproven again rather than
disproven: on 2026-09-16 `qwen38-27b` carried `I1` (6 min) and `P1` (11 min) with the
driver attaching both hand-offs, which is further than any local run had reached.

**A local model must serve the lane's fork.** `TW ∥ C` puts two cards in flight at once, so
a llama.cpp slot with `--parallel 1` serialises them and both ceilings run in wall time —
measured the same day, both fork cards timed out at 1202s of a 20m limit on `qwen38-27b`,
which halts the board. Name a model with two or more parallel slots (`ornith-35b` here), or
drop the fork with `unit-tests: false`. The per-card ceiling is also wall time against a
COLD model: the first card on a slot pays the load (~48 s on the 24 GB rig). `board_schema` refuses a provider without a model beside it in the same scope, as the
engine does, and reports (never refuses) a board that names a work model and no pin —
its reviews have quietly become the author's model. `lanes.model_args` is the single
lookup for the whole precedence, so filing, the rework rounds and the lane-open re-point
cannot disagree about it.
The review model is not the *goal judge* (see [the goal judge](#the-goal-judge)).
Reasoning depth is not pinned: stock `hermes kanban create` has no flag for it, and
carrying a Hermes patch for it costs more to maintain than the depth is worth, so every
card runs at its profile's configured effort.

**Worker contract.** The rules every worker shares — board access through
`kanban_show` or the CLI, no branches/commits/follow-up cards, no questions, a block
only for a missing decision or tool and never `--kind dependency`, no caches
in `work/`, full sentences, no memory/skill/config writes, end the card as the body
says — live once in `mission/card-bodies/_worker-contract.txt`, included by every
worker and verdict body as `<WORKER_CONTRACT>`. The profile SOUL's `## Kanban Cards`
is only a short precedence paragraph: the card wins. Reasons: only kanban sessions pay
the tokens for the rules; there is one copy to maintain; and precedence has to sit in
the system prompt, because the card body arrives as a tool result. SOUL maintenance is
in [mission/roles/README.md](mission/roles/README.md).

**Worker sessions** are tagged `source=kanban` and hidden by Hermes Desktop; §4 shows
how to read them.

## Driver behaviour

- **Serve mode.** The driver releases nothing until a Triage card is promoted. Arming
  validates headers and manifest, adopts the text into `lane-<k>.md`, mints
  `runs/<run-id>/`, archives the previous run's cards and files a fresh lane set. The
  `specify` button is not a go signal because it rewrites the idea with an auxiliary
  LLM before the researcher reads it.
- **Refile clears per-run state first** (opened lanes, timers, drift findings,
  announced gates), before filing — filing can fail, and the next tick must not treat
  the new run's lanes as already open, carry the last run's drift into this run's
  summary, or skip announcing a gate whose title repeats across runs.
- **Lane/run agreement.** Cards are filed with their run's paths in their bodies. A lane
  whose root card names a different run is refused before anything is archived, linked
  or written, and is never released: every hand-off would be written where nothing
  reads it.
- **Restart rejoins.** A lane already opened on this run (a `lane_open` record in
  `chain.jsonl`) is rejoined, not re-opened, so a running card's snapshots are not
  rewritten and the lane is not commented on twice. The lane/run agreement check runs
  first, so a rejoin never releases a mismatched lane. What a restart keeps and which
  halts it repeats: [restart and reset](#restart-and-reset).
- **A recorded halt stops the loop before any refile**, so an armed idea is not adopted
  into a fresh run that the same exit would abandon.
- **Snapshots before release.** At open the driver writes the idea snapshot and the
  work directory as the lane finds it, then releases the root — so no worker reads a
  mutable or half-written input, and lane 2 sees the tree lane 1 left rather than the
  tree at filing time.
- **Stops, halts and the deadman.** Promotion releases only the parking brake; a
  worker's stop is re-promoted once; everything else halts naming the cause. The
  whole algorithm, with its decision tables, is
  [how a lane avoids and escapes a stall](#how-a-lane-avoids-and-escapes-a-stall).
- **CLI timeouts.** Every `hermes` and `git` call has a 60 s timeout
  (`CLI_TIMEOUT_S`): a hung CLI would otherwise stall the driver while its lock stays
  live and `start-board.sh` keeps seeing a healthy driver.
- **One `show` per card per board snapshot.** Every block reader (`card_record`,
  `_blocked_event_payload`, `live_worker_pid`, the chain's attachment read) goes through
  `run.card_show`, memoised inside `show_memo` — one per `tick` and one per
  `deadman_check`. A `show` is 0.25 s, and the readers asked per card several times a
  tick (~80 calls on a 2-lane board). A fresh `list` (`board()`) empties the memo, so a
  card read while `running` and `blocked` in the next snapshot is read again; a driver
  write through `kb` drops the memo entry of every card it names. A failed read is not
  remembered.
- **Index sweep.** Every tick the driver unstages anything under the board's `runs/`
  (all runs, in the kanban repo), because a staged hand-off reaches every later card's
  `git diff --cached` and the operator's `git status`. `run-audit.py` fails a run that
  leaves one staged (E14).

### Work directory pinning

When a run's first lane opens, the driver pins the work directory's repository, branch
and HEAD (`runs/<run-id>/workdir.json`) and checks them every tick. A branch switch, a
commit or reset under the board, or a path staged in an external work directory that
is not the lane's is logged once as a WARNING, recorded as `workdir_drift` in
`run-summary.json`, and fails `run-audit.py` (E17). It is reported, never corrected:
switching a branch back would make the board a second writer fighting the operator,
and a staged path is the human's. Every gate result and `commit_target` in the summary
name the repository, branch and HEAD the work was staged into, so a board with an
external `default-workdir` says where its deliverable went.

Inside the work directory (and declared `targets`) the lane owns the tree: it may
change, replace or delete anything there, and no staged or uncommitted file is
promised to survive. Outside those roots the board touches nothing.

## How a lane avoids and escapes a stall

A stall is a lane that cannot advance while the board says nothing, and it looks exactly
like a slow lane. The board works against it in three layers. The card bodies take away
the reasons to stall. The driver gets a card moving again, once, only where the cause is
known to heal. Everything else halts the board and names the cause. There is never an
unbounded wait or retry: driving on would only file more work against a broken step, and
polling would hide the stall.

### Prevention: filing and the card bodies

| rule | where | why |
|---|---|---|
| Goal mode is opt-in: `"goal"` is a board-level key, default `false`, read at filing | `board_schema.OPTIONS`, `file_lanes.file_board` → `lanes.goal_args` | a goal judge that cannot answer wedges every worker card ([the goal judge](#the-goal-judge)). Changing the key means re-creating the board. Restarting the driver does not change it |
| Goal flags go on worker cards only (I, P, TW, C, TI and their rounds), never on reviews or gates | `lanes.goal_args` | a goal judge can push a card whose success case is *blocking* into completing, which silently opens the gate it guards |
| `goal-cards` narrows goal mode to listed worker codes; the gate/review refusal is checked before the list | `lanes.goal_args`, `board_schema` kind `cards` | a list is a per-board choice of *which* workers need the judge (long `C`/`TI` cards end turns without calling `kanban_complete`; short `I`/`P` cards rarely do), and a typo in it must not arm a gate |
| A human gate reads a verdict only from a non-driver comment whose first word is `PASS`/`ACCEPT`/`REWORK` (alone or followed by `:` or a dash), posted after the driver's `GATE READY` for the gate's current readiness. A plan or code gate's `GATE READY` names the review card it rests on (`[RVp1-r2]`) | `run.apply_comment_verdict`, `answer_early_verdicts`, `gate_rework` | a comment is the one write every surface offers (the desktop app cannot complete a card). Reading only after `GATE READY` keeps an early `PASS` from opening a gate on input nobody judged, and the tag keeps a comment written under an earlier round from counting after the next one. The driver answers each verdict once (`NOT APPLIED` / `REWORK APPLIED (comment #n)`), keyed in the thread so a restart does not repeat it |
| A person's `REWORK` at Gp/Gc files the round the gate's own loop files after a review `REJECT`, and leaves the gate held; at Gi it completes the gate with `REWORK: …` | `run.gate_rework` → `file_revision` / `file_code_revision` | one loop per gate, bounded by the same `max-reworks`. Completing Gp or Gc would release `TW` or the next lane, and the rework loops only run while the gate is parked |
| Every card is bounded: the per-card `max-runtime` (default 60m), the global `agent.max_turns` (80), and under goal mode `goal-max-turns` (default 40). `max-retries` is pinned to 1 | `board_schema.OPTIONS`, `file_lanes.file_board` | nothing else bounds a worker. A card that reaches its ceiling has failed for good, and nothing retries it |
| Each worker body's FINISH paragraph sits in the first 2000 characters of title + body | card bodies; `test_card_bodies.test_the_goal_judge_sees_that_a_failing_test_is_a_finish` | the goal judge reads the card cut at 2000 characters (`goals.judge_goal`), so a rule past the cut does not exist for it |
| `result` is the report. A `summary`, if written, repeats every failing-test, TEST FIX and TEST DEFECT line | `_result-field.txt` | the completion gate judges `summary or result` (`tools/kanban_tools._goal_gate`), so a short summary hides the evidence that the card is finished |
| For TW and C a failing test still finishes the card: name each failing test and complete. Only a review rejects | `tw-body.txt`, `c-body.txt` FINISH | TW's tests are red by design while C works (`TW ∥ C`). A card that blocks or loops on a red test burns its budget and keeps the defect from the review that would route it |
| C may correct a TW test only under c-body hard rule 3. Conditions: TW is `done`, a run shows the assertion is unsatisfiable, the intent is kept and no coverage is lost. The fix goes in a separate `test-fix.diff`, which RVa checks against the plan (check e) | `c-body.txt`, `rva-body.txt` | without this, a wrong test leaves C a choice between failing and fudging. The separate diff keeps the correction reviewable |
| TI may change any file in the work tree. It must get the integration suite green with the unit suite still green. If it cannot after genuine effort, it completes and names each failure | `ti-body.txt` FINISH, hard rule 2 | some gaps show up only end to end. RVc requires green and rejects with `OWNER: TI` |
| Workers `block` only for a missing external decision or tool, with `--kind needs_input`, never `--kind dependency`. A plan step believed wrong, or another card's defect, goes in the result and the card completes | `_worker-contract.txt` | the review can route an upstream defect back to its owner; a block cannot. A dependency block never even reaches `blocked` ([block origins](#block-origins)). The researcher's missing-toolchain stop (`i-body.txt`) is the sanctioned block |
| RVp rejects a test step that asserts something the plan's named toolchain cannot produce, or a FAIL that the plan's own Findings contradict | `_plan-checklist.txt` item 4 | an unachievable assertion costs least in the plan, before TW, C and a review round spend on it |
| A REJECT names its owner. RVa names C, TW or TI. RVc names TI (for any red test, or any change TI made outside its tests) or C. No usable owner means C | `rva-body.txt`, `rvc-body.txt`, `run.rework_owner` | a round filed against a card that cannot fix the defect repeats until it escalates ([rework loops](#rework-loops)) |

### The goal judge

- **Two different models.** The *goal judge* is the auxiliary task `auxiliary.goal_judge`.
  It runs on the worker's profile model only where nothing pins it: a managed pin decides
  for every profile and a per-profile `auxiliary.goal_judge` cannot override it — the
  managed layer here (`/etc/hermes/config.yaml`) sets `provider: openrouter`, `model:
  z-ai/glm-5.3-flash` (not opencode-go: the judge runs outside a turn, carries no
  `x-opencode-session`, and OpenCode Go answers `400 MissingSessionID`), so that is what
  judges, whatever the profile or the board's `model` say.
  The *review model* is `model_override`/`provider_override`, set on the review cards
  only (`lanes.JUDGE_CODES`, `lanes.model_args`). Pinning the review model does not move
  the goal judge.
- **It sees text only**: the card's title and body (cut at 2000 characters), plus the
  worker's claim. It neither runs nor reads the work, so its verdict depends on how the
  claim is worded. A claim that names failing tests without saying the body counts that
  as finished reads as "not done".
- **It acts in two places.**
  1. It gates `kanban_complete` and `request-review` on `summary or result`. A `done`
     verdict lets the completion through. `continue` rejects it with the judge's reason,
     and the worker keeps going. `blocked` rejects it as unachievable. A missing
     auxiliary client, or an exception raised in the gate, fails open: the completion
     goes through.
  2. After each turn that ends without a terminal call, the goal loop
     (`goals.run_kanban_goal_loop`) judges the last response and nudges the worker. The
     loop can end by blocking the card itself, **with no kind**, with one of three
     fixed reasons: "Goal-mode judge ruled the goal unachievable: …", "Goal-mode
     worker's output looked complete but it never called kanban_complete after a
     finalize nudge …", or "Goal-mode worker exhausted its turn budget …"
     (`run.JUDGE_BUDGET_BLOCK_MARK`). The driver treats the first two as the worker's
     own block and halts at once on the third ([block origins](#block-origins)). A
     goal-mode worker's own block is `needs_input`, because the worker contract says so.
- **It can wedge every worker card.** When the judge's API call fails inside
  `judge_goal`, the failure is logged as `goal judge: API call failed` and returned as
  the verdict `continue`. No evidence satisfies that verdict, so every completion is
  rejected and every goal loop spends its budget. The judge runs *outside* a turn, so it
  has no conversation to key on — and an OpenCode relay refuses a request whose
  `x-opencode-session` is missing with `400 MissingSessionID`. Something has to supply
  that key: the Hermes checkout's out-of-turn affinity fallback does it for every
  out-of-turn call (a per-process key; see *Hermes Local State and Recovery* in the
  KnowledgeBase vault), and with no such fallback the judge must be pinned to a provider
  that is not the relay (`auxiliary.goal_judge.provider`). Measured 2026-09-15: the
  judge's call carried `hermes-proc-<pid>-<hex>` and answered `{"verdict": "done"}`; with
  the fallback removed, the same call returned the 400. This is why goal mode is opt-in.
- **Probing it.** There is no probe board, because goal mode is a manifest key. Before
  arming a real board with `"goal": true`, set it on `boards/is-even` (it ships with it
  on; turn it off to run that board without the judge),
  re-create and run that board, then set it back. A working probe proves that the judge
  answers and can say `done`. It does not prove the judge checks the work.
  - *Working:* `I1` completes in one turn. The worker's profile log
    (`~/.hermes/profiles/<p>/logs/agent.log`) shows `goal judge: verdict=done` and
    `kanban goal loop: task … completed by worker after 1 turn(s)`.
  - *Failing:* `I1` never completes and stops at its per-card `max-runtime`. The same log
    names the cause in `goal judge: API call failed`.

  | Symptom | Cause | Lever |
  |---|---|---|
  | every judge call fails `400 MissingSessionID` | the auxiliary request carries no `x-opencode-session` — the judge runs outside a turn, so nothing keys one | the checkout's out-of-turn affinity fallback, or a judge provider that is not the OpenCode relay (`auxiliary.goal_judge.provider`) |
  | the judge answers but never `done` | the model cannot follow the strict JSON verdict contract | `auxiliary.goal_judge.provider` / `.model` in the profile's `config.yaml` |

  If the judge cannot be made to answer, the board keeps `"goal": false`.

### Block origins

Promotion only looks at a blocked card whose parents are done and that no verdict holds
back. The only block it may release is the board's own parking brake. Any other block
is somebody saying STOP. `run.block_origin` classifies a block by the reason on its
newest block event, and `run.should_repromote` decides what to do:

| origin | recognised by | `should_repromote` | driver action | what the human sees |
|---|---|---|---|---|
| `parked` | `is_parked`: reason `initial_status` (the card was filed blocked) or `parked: awaiting lane activation` | `release` | unblocks the card, as often as the graph asks | log `unblocked <code> (parents done)` |
| `worker` | any other non-empty reason: the worker's block, the goal loop's "unachievable" or "never called kanban_complete" block, or a human's block | `repromote` the first time, then `stop` | re-promotes once, after the worker's process exits (below). A second block escalates and halts | comment `RE-PROMOTED (once): …` and log `re-promoted <code> once`, then `ESCALATION: its own worker blocked it twice (…)` |
| `judge_budget` | reason starts `Goal-mode worker exhausted its turn budget` | `stop` | escalates at the top of the tick, wherever the card sits. One such card behind an unfinished parent is below the deadman threshold | the halt, plus `goal judge: API call failed` in `~/.hermes/profiles/<assignee>/logs/agent.log` (`judge_log_hint`) |
| `timeout` | reason contains `TIMEOUT:`, the block the driver sets at a runtime ceiling (`stop_a_timeout`) | `stop` | never promoted away. Only a review sends work back | "a ceiling is not a review; a human resets the board" |
| `driver` | reason starts `HALTED:`, the block the driver puts on a card it halted for (`driver_block`) | `stop` | never promoted away. A restart reads this block as the driver's stop, never as the worker's | "blocked by the driver when it halted" |
| `other` | the newest block event has no reason (`hermes kanban block <id>` with no words; the driver always gives one) | `stop` | escalates at the top of the tick, wherever the card sits, like `judge_budget`: nobody can interpret it, and a card held behind a verdict would otherwise wait unseen. A card whose record cannot be read has no block event and is not halted on | "blocked without a reason (by a human or a worker)" |
| `unreadable` | the card's `show --json` failed (`card_record` notes the error in `_READ_ERROR`; a good read clears it): a CLI timeout or "database is locked" | `skip` | leaves the card for this tick: no unblock, no escalation, not stuck, not a reasonless block. A failed read is not remembered by the per-tick memo, so the next tick reads again. `UNREADABLE_LIMIT` (3) promotion ticks in a row unreadable escalates and halts; a good read restarts the count | log `<code>: could not read its card (…)` once per streak, then "could not read card <code> (<error>)" |

Why a worker's stop gets exactly one re-promotion:

- **Why promotion hears a stop at all.** On 2026-09-13, roman-evaluator-java C2 blocked
  itself at 15:52:41, and promotion undid the block six seconds later. The worker's "I
  cannot complete this" survived only as a comment nobody read.
- **Why it gets one retry.** Lane 2 of roman-evaluator-java healed on the retry.
- **Why a spent turn budget gets none.** A failing goal judge reads as `continue`, so a
  second budget would burn the same way.
- **Why a human's block counts too.** A block event carries no actor, so a human who
  blocks a gate with a reason gets the same one re-promotion before the halt finds
  them. A block with no reason halts at once. To stop a card dead, reset the board.

**Waiting for the worker to exit.** `kanban_block` is a tool call, not the worker's
exit. The worker may still be finishing its turn, so unblocking at once would put a
second worker on the card and record the log offset before the first worker's output
lands. `run.live_worker_pid` reads the pid from the card's newest `spawned` event. While
that process is alive the driver defers the re-promotion and logs the deferral once. A
blocked card has no runtime ceiling bounding that wait, and a pid the OS has reused
would hold it indefinitely. So `REPROMOTE_WAIT_S` (5 min) after the block, the driver
re-promotes anyway and logs that it stopped waiting.

**Two blocks the engine reroutes before the driver sees them.**

- **A `--kind dependency` block never reaches `blocked`.** `kanban_db._route_block`
  sends it to `todo` as a `dependency_wait` event, and `recompute_ready` promotes it
  again without counting a recurrence. Once the card's parents are done, `run.card_stall`
  handles it:
  - the first such event counts as the card's one re-promotion (ledger `repromote`
    with `via: dependency_wait`, comment `RE-PROMOTED (once)`)
  - a second one halts the board, and so does a dependency block after an ordinary
    re-promotion
  - events whose reason starts `rework in flight:` are ignored
- **A second block of the same kind after an unblock goes to Triage.** The engine counts
  recurrences up to `BLOCK_RECURRENCE_LIMIT` (2), then routes the card to Triage
  (`block_loop_detected`). `run.escalated_to_triage` halts on that, and
  `run.triage_halt_reason` carries the block's words, so the worker's reason still
  surfaces.

### Stall classes

Every halt goes through `run.record_halt`: a `BOARD HALTED: …` log line,
`runs/<run-id>/halt.txt`, and one notice. Through `run.escalate`, the card also gets an
`ESCALATION: …` comment where there is a card to put it on. The ledger keeps that
comment to one per key, across restarts too. The driver then exits.

| stall | detected by | driver action | message |
|---|---|---|---|
| a card attempt failed (`gave_up`: retries spent, a crash, a failed spawn) | `halt_if_exhausted` → `_exhaustion_event` | comments `BOARD HALTED:` on the card and halts. The reason says "provider-starved" when the attempt's log holds ≥3 upstream lines | the event's error |
| a provider-starved attempt: `gave_up` with ≥3 `runs_util.UPSTREAM_ERROR` lines since the attempt's offset, and an exit that never called `kanban_complete`/`kanban_block` (reason `protocol violation`, or `trigger_outcome` `crashed`) | `halt_if_exhausted`, `provider_hits` | **re-queues once** (`requeue_provider_starved`): marks the attempt, unblocks, and records `requeue` with its time. An exhaustion event at or before that time is ignored, and any later failure halts | comment `RE-QUEUED (once): …`, log `re-queued <code> once` |
| timeout (`timed_out`) | `halt_if_exhausted` → `stop_a_timeout` | blocks the card with `TIMEOUT: … hard failure`, because the dispatcher would put it back at `ready`, then halts. Never re-queued | `BOARD HALTED:` on the card |
| rate-limit wall: `RATE_LIMIT_LIMIT` (3) closed runs in a row ending `rate_limited` | `card_stall` | `driver_block` `HALTED: …` (promoting a `todo` card first, so the block is accepted), then escalates | "provider quota wall" |
| stale reclaim: `RECLAIM_LIMIT` (2) `reclaimed` events whose payload is not `manual` (an operator's `reclaim`) | `card_stall` | same | "its claim was reclaimed n times" |
| dependency loop: a second `dependency_wait` with the parents done | `card_stall` | same | "its own worker blocked it twice, the last time with `--kind dependency`" |
| a worker blocked its card a second time | promotion: `should_repromote` → `stop` | escalates | `stop_reason`, quoting the worker's words |
| a goal loop spent its turn budget | the top-of-tick scan for `JUDGE_BUDGET_BLOCK_MARK` | escalates | `stop_reason` + `judge_log_hint` |
| a blocked card whose newest block event has no reason | the same top-of-tick scan, `is_reasonless_block` | escalates | "blocked without a reason (by a human or a worker)" |
| a blocked card promotion reaches could not be read `UNREADABLE_LIMIT` (3) ticks running | promotion: `should_repromote` → `skip`, counted in `_UNREADABLE_TICKS` | escalates. Fewer ticks only skip the card, so a transient CLI failure never halts a healthy board | "could not read card <code> (<last error>)" |
| the engine escalated an assigned card to Triage | `escalated_to_triage` | escalates | `triage_halt_reason` |
| a lane card sits in `review` or `scheduled` (statuses no lane uses, reached only through `request-review`, which the worker contract forbids, or by hand) | the tick's status scan | escalates | "a status no lane uses" |
| a lane card was archived or removed by hand (a card the lane's own options do not drop) | `missing_lane_card`: `list --json` omits archived cards, so the children wait on a parent that reads as not done | escalates on the first live card after it, or halts when there is none | "… is no longer on the board" |
| a lane root was filed against a different run | `open_lane` → `lane_paths_agree`, checked before anything is archived, linked or written | escalates on the root at once and never releases it | "filed against a different run than runs/current names" |
| a gate whose parents are all done keeps giving the same `waiting:` message for `GATE_WAIT_S` (10 min) | the gate loop, `gate_wait_reason` | escalates under the key `<gate>-wait`, so this halt never uses up the gate's rework-exhaustion comment | "verdict unreadable" (Gp/Gc), "the gate's input will not appear by itself" (Gi) |
| rework rounds exhausted | `rework_rounds` | escalates on the gate or plan card | [rework loops](#rework-loops) |
| a blocked card whose block reason carries `ESCALATION` | `halt_if_exhausted` | halts | the block reason |
| the Hermes board itself no longer exists (`board '<slug>' does not exist`) | `board_removed_exit`, before the tick-error count | a finished, serving run: exits 0 with `BOARD REMOVED`, no halt. Mid-run: halts at once | "was removed under a live run" |
| the tick raised the same exception `TICK_ERROR_LIMIT` (3) times running | `note_tick_outcome`: a good tick or a different exception restarts the count | halts | the exception |
| `runs/current` names a run with no lane card and no idea card to arm, or with lane cards but no P card | `empty_run_reason` (a lane is counted by its P card) | halts | the reason plus `RESET_STEPS`, because the armed idea card is already archived |
| the run directory is gone under a live run | `run_directory_is_gone` | halts, writing halt.txt to `runs/` | "run directory disappeared" |
| the driver died without a halt | `run-audit.py`: no halt, no finish banner, no live pid in `runs/driver.lock` | nothing is running | E1 "the driver died without a halt or the finish banner … restart it with start-board.sh" |
| two or more cards `is_stuck`, with no halt | `deadman_check` | sends a notice once per distinct stuck set. No halt | `DEADMAN` line, `deadman.txt`, Telegram |

Where a row's reasoning is not obvious from the table:

- **Why the driver blocks the rate-limit, reclaim and dependency cards before halting.**
  The engine retries those cards for ever without counting a failure:
  `check_respawn_guard` retries every cooldown, `release_stale_claims` returns the card
  to `ready`, and `recompute_ready` promotes again. Without the block, the retries would
  go on after the driver exits.
- **Why timeouts are never re-queued.** A runtime ceiling is the board's own rule. A
  provider flake is not.
- **Why a repeated tick exception halts.** roman-evaluator-java once logged one
  `ValueError` 26 times.
- **Why a waiting gate halts.** A minimal-development run sat on
  `Gc1: waiting: final review verdict` until a human killed it.
- **How the empty-run case arises.** `create-board.sh` mints its run and files the
  parked lanes in one step, and a refile archives only once it has an armed card. So only
  a filing that failed after `mint_run`, or cards archived under a live driver, leaves
  a run like that. Nothing retracts a mint — `runs/` is a human's to prune, `reset.sh`
  keeps it wholesale, and AGENTS.md forbids deleting run directories — so a *re-filing*
  must not add a second one: `file_lanes.next_run_key` reuses the run `runs/current`
  names while no driver has started in it, and treats any path in
  `file_lanes.DRIVER_EVIDENCE` as proof the run happened (a run is never reused).
  Measured on `is-even` (2026-09-13): two abandoned mints, the newer named by `current`,
  and the board's own definition of done red — E1 "no driver.log — the run never
  started", E4 — for a run that never existed.

**Upstream lines belong to an attempt.** The dispatcher opens a card's worker log
append-only, so one file holds every attempt, including every earlier run of that card,
and the log's lines carry no timestamps. A session id is no boundary either. Under `-Q`
the id goes to stderr at once and the buffered stdout lands after it: in one 2026-09-10
storm log, 10 of 12 `HTTP 400` lines followed the only id.

The driver therefore records the log's byte size in `verdicts.jsonl` (`attempt`,
`run.mark_attempt`) before every unblock that starts an attempt: lane release,
re-promotion or re-queue. It does so once the previous worker has exited and flushed.
A parked card never ran, a re-queue follows the exit, and a re-promotion waits for it.

Counting starts at an offset:

- `provider_hits` counts from the card's newest offset, and run-audit's E18 counts from
  its first offset in the run.
- A card with no offset, such as a rework round filed ready, counts its whole log.
- An offset past the end of the file (the log was rotated at spawn) counts from 0.

Both counts match only the transport's own forms (`runs_util.UPSTREAM_ERROR`). A
whole-file count let an earlier attempt's storm, or a tool's `HTTP 404`, re-queue a
later failure and label every later halt.

### Restart and reset

- **A restart keeps the run's allowances.** `run.rejoin_chain` → `load_one_shots`
  rebuilds them from `runs/<run-id>/verdicts.jsonl`:
  - `repromote` records, including `via: dependency_wait`
  - `requeue` records, with their time
  - `escalation` records, keyed by code or `key`
  - `attempt` log offsets
  
  `lane_open` records in `chain.jsonl` are rejoined the same way. A restart is not a new
  run, so it grants no second re-promotion or re-queue and repeats no comment.
- **Some state lives in memory only.** The tick-exception count, the gate-wait clock
  and the deferral log line all start over on a restart.
- **A halt that rests on the board's record halts the restarted driver again**, because
  the new process reads the same record:
  - a `gave_up`/`timed_out` event on a card that is not done
  - a driver `HALTED:` or `TIMEOUT:` block
  - a worker's second block, or a spent budget
  - a card in Triage, `review` or `scheduled`
  - a `card_stall` count (runs and events stay on the card)
  - an exhausted rework loop
  - a missing lane card, a mismatched lane, an empty or partial run
  
  An escalation already in the ledger adds no comment, but it still halts.
  `reset_attempt_budgets` clears only the engine's failure counter; the events remain.
  A gate wait halts again after another `GATE_WAIT_S`, and a tick exception halts again
  only if it repeats. So a restart recovers a driver that stopped without a halt, and
  only `mission/reset.sh` clears a halt (README's Resetting sequence).
- **`reset.sh` stops the driver first.** The pid comes from `runs/driver.lock`, and the
  script acts on it only when it is a live process running this repo's `mission/run.py`.
  If that process does not stop, the script stops too. Stopping the driver matters
  because a driver left serving reads the archived board as a failed filing and halts
  with the wrong cause, or drives the cards `create-board.sh` files next. Only then does
  the script unstage the board's paths, and then, card by card, stop the card's live
  worker before archiving the cards.
- **Every halt sends one notice.** `record_halt` → `send_notice` writes `deadman.txt` and
  sends Telegram when tokens are set. The driver is exiting, so nothing else would push
  the news.
- **Deadman, short of a halt.** `run.deadman_check` notifies when two or more cards are
  `is_stuck`. A card counts as stuck when it is blocked, `should_repromote` says `stop`,
  and its origin is `worker`, `judge_budget` or `other` with its block event read. An
  `unreadable` card is `skip`, so it is not counted. A ceiling or a `HALTED:` block halts through its own
  path (`halt_if_exhausted` stops a timeout; a `HALTED:` block is set by a halt already
  recorded). Parked cards are not counted, and
  neither are self-blocks still owed their re-promotion: TW and C blocking in parallel
  are both released on the next tick. The notice goes out once per distinct stuck set,
  and a failed board read is logged, not raised.

## Records

- **Driver log** — `runs/<run-id>/driver.log` (per run) and the board-level
  `boards/<slug>/runs/driver.log`, which is append-only across runs. Every driver start
  writes a `--- driver start: board=… pid=… run=… ---` header, so `tail` on the board log
  reads as this run's, not as the previous night's last line (measured 2026-09-13: a
  fresh run's lines sat under the previous day's).
- **Document chain** — `runs/<run-id>/chain.jsonl`: one `lane_open` record per lane
  (the run's own beginning: inputs are written, the root is released next, so a
  "written before the run" finding is measured from here); one record per card as it
  starts (the lane documents its body names, any unresolved `<PLACEHOLDER>`) and as it
  finishes (attached patch, result, verdict, and for worker cards the staged set).
  Rework-round cards (`RVa1-r2`, `P1-rev-1`) are recorded like base cards. Every gate
  rework adds a `rework` record (gate, round, cards filed, findings).
- **Verdict ledger** — `runs/<run-id>/verdicts.jsonl`: every verdict, rework and
  escalation.
- `mission/doc-chain.py --runs boards/<slug>/runs` checks the chain against the
  filesystem and exits 1 on: a named document that is missing (F1); one a card reads
  but that was written after it started (F2); one written before the run began — a
  previous run's leftover (F3); an unresolved placeholder in a filed body (F4); a
  worker that left no trace at all — nothing attached, nothing staged, no result (F5);
  a REJECT with no round filed (F6 — what
  an invisible stall looks like). `--history` counts reviews and reworks.

## Known traps

Each is current behaviour, with what to do about it.

- **The dashboard cannot complete a card from the desktop app.** `Complete` asks for the
  completion summary with `window.prompt` (a documented carve-out in the kanban plugin bundle,
  `dist/index.js`, because the host's `ConfirmDialog` cannot stay open across a validation
  failure), and `window.prompt` is not implemented in Electron — it returns `null`, which the
  flow reads as *cancel*, so the click produces no dialog, no error and no request. Answer
  a gate with a `PASS` comment instead (the driver completes it), use a browser on
  `http://127.0.0.1:9119/kanban`, or the CLI: `hermes kanban --board <b> complete <id>
  --result "…"` needs no summary at all.
- **Arming a board has no CLI subcommand.** The driver reads a Triage card as armed
  once it is out of `triage` and unassigned (`armed_ideas`), which the dashboard offers
  as the panel's `→ ready` button or a drag to Todo — but `hermes kanban promote` refuses
  a `triage` card, and so do `block` and `schedule`, so no subcommand can make that
  gesture. `mission/arm.sh <slug> [lane]` reaches the state the other way round: it
  archives the board's seeded Triage card and creates an unassigned card in `blocked`
  whose body is the lane's idea in the shape `file_ideas` writes — `blocked` because a
  `ready` card is claimed by the dispatcher (`kanban.default_assignee`) and WORKED while
  the driver reads it as an idea, which is what happened on the first arm attempt
  (2026-09-15). `armed_ideas` accepts a blocked card only with the marker, so a card a
  person parked by hand is still ignored.

- **A worker that cannot complete is told the wrong reason.** `kanban_complete`
  refuses an unsatisfied-parent card with *"unknown id or already terminal"*, neither
  of which is true, and a worker hunts for `--force` flags that do not exist. Check
  the card's parents first.
- **Blocking a card is not a hard stop.** A block event carries no actor, so a human
  blocking a gate — or a worker blocking its card — gets one re-promotion before the
  second block halts the board ([block origins](#block-origins)). To stop a card dead,
  reset the board (`mission/reset.sh`): that is the human brake.
- **Never unlink, archive or re-parent a card while the dispatcher is claiming it.**
  The worker spawns holding the pre-change view and fights a board that has moved.
  Board surgery is safe on a parked lane.
- **`work/` holds only what the idea asks a human to receive** — the files the plan's
  Files blocks name. Transients go under `runs/<run-id>/scratch/<card-id>/`. `<RUNS>`
  is a render value, deliberately not a lane document, so the chain never stats scratch
  as a hand-off. Caches a worker leaves in `work/` are reported as a note (E16) and left
  in place.
- **An IDE commit while a driver is live is suspect.** A changelist commit has no
  pathspec, so it takes whatever the run has staged — generated files into HEAD, or
  pending removals of tracked documents. Check `git log --stat` for `boards/*/work|runs`
  additions and missing documents; untrack generated paths with `git rm --cached`.
- **The index is board state.** `git diff --cached --name-only` lists all of it, not
  just your directory, so a pending entry from anywhere (a repo cleanup, another
  board) is handed to every card that checks the index and can pull a card
  off-contract. Keep the index clean before arming. Nothing commits, so a previous
  run's staged work entries outlive it until the human commits or `reset.sh` unstages
  them (the files stay).
- **Clearing `work/` is by hand, never with `git restore --staged --worktree -- work/`.**
  Against tracked paths that means "restore to HEAD": it resurrects the committed
  deliverable and un-stages any pending removal at once.
- **Stale-document safety rests on minting being correct.** The idea gate checks the
  refined idea's *structure*, so a leftover `refined.md` would pass it. A lane is never
  handed one only because each run's hand-offs are under its own `runs/<run-id>/` — a
  driver that minted a run per restart instead of per armed idea would break that,
  which is why `mint_run` requires an armed idea and `open_lane` checks lane/run
  agreement.
- **A killed driver leaves its workers running.** They write to the paths rendered into
  their own bodies, which name their own run, so an orphan cannot reach a later run's
  documents — but it burns a slot and a budget on an archived card and can re-stage
  stale content. `reset.sh` stops this board's workers before archiving;
  `run-audit.py` warns on a worker that outlived the run (E8) — and only on one that is
  really still running: a zombie (`pgrep` lists it, `/proc` says `Z`), a worker whose card
  is already `done`, and a worker whose card is not on this board are all ignored. Each of
  those three produced a false warning on the is-even run of 2026-09-15, and a run summary
  is written once, so a false one can never be withdrawn.
- **The goal judge can wedge every worker card** when it cannot answer, and a working
  probe proves only that it answers. Mechanism, probe and levers:
  [the goal judge](#the-goal-judge).
- **A leaked child-context marker blocks every card mutation.** With
  `HERMES_DELEGATED_CHILD_CONTEXT=1` in the environment the kanban CLI refuses
  `create`, `attach`, `complete`, `unblock`. The scripts unset it; launch anything else
  as `env -u HERMES_DELEGATED_CHILD_CONTEXT -u HERMES_HOME mission/…`. **A worker is fenced
  on purpose** — it is a dispatcher-owned child — so no card body may tell it to `env -u`
  its way out: a strong model that finds the trick passes the card by defeating a Hermes
  guard (cloud runs on is-even did exactly that until 2026-09-16), and a weaker one does
  not. A worker mutates its card through the kanban TOOLS, and hands files over through
  its scratch directory for the driver to attach.
- **`python3` on the PATH is the Hermes venv and has no pytest.** Run the suite as
  `mission/test.sh`; a plan whose Run steps say bare `python3 -m pytest` fails before
  collecting.
- **A Hermes command's first stderr lines can be a stale-update banner**, printed while
  the last `hermes update` receipt is partial. It is not the error:
  `runs_util.cli_error` drops it so the real error ("board does not exist") reaches the
  driver log.
- **Lane chaining (`Gc1 → I2`) is exercised only by `roman-evaluator-java`**, the one
  two-lane board. Watch the lane-2 release on a multi-lane board.

## Timing instrumentation

- The driver ticks every 20 s and appends a status snapshot to
  `runs/<run-id>/timing.jsonl`; a run-boundary marker (ts, argv) at every driver start
  lets the report cover only the latest segment.
- On each card status *change* the snapshot embeds the card's run evidence (`last_run`
  outcome + `elapsed_min` from `runs <id> --json`, `gave_up` when a budget ran out),
  and the card's FULL record — body, assignee, result, run history, attachments — is
  appended to `runs/<run-id>/cards/<card-id>.jsonl`, so a card's history survives board
  archiving. Per-card patches are preserved into the run directory for the same reason.
- At a code gate the driver logs the staged-evidence line
  (`GATE GcN evidence: …; staged: …`) and, *before* announcing the gate, writes
  `runs/<run-id>/timing-report-lane-<k>.txt`: the gate is where you decide whether to
  commit, so the lane's cost must be readable while it can still change the decision.
- On completion it writes `runs/<run-id>/run-summary.json`: per-card agent minutes,
  wall and overhead totals, gate results (the driver's evidence for opening each
  gate, then the gate-holder's own result). Because a lane forks (`TW ∥ C`),
  `agent_work_min` is the SUM (what a per-card ceiling is measured against),
  `agent_union_min` is the minutes work was in flight (sum minus `overlap_min`), and
  `overhead_min` is wall time nobody worked, measured against the union so two cards
  sharing the clock never read as negative overhead. A timed-out attempt counts as
  worked time, or its minutes reappear as overhead and the audit passes a run that
  burned its budget.
- `mission/timing-report.py --board <slug>` prints the same report on demand (latest
  segment): the per-card table, a per-lane breakdown when there is more than one lane,
  and a per-role share showing how wall time divides between reviewing and working.
  Roles come from `lanes.LANE_CARDS`, so the report cannot disagree with the graph.
- Gate completion timestamps delimit the planning, build and review phases of a lane.
