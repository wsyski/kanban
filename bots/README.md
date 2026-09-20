# bots/ — the same board, run by Hermes Bots

A second driver for the boards in `boards/`, beside `driver/run.py`. The kanban
driver files cards on a `hermes kanban` board and a dispatcher spawns hidden
workers. This one files nothing: each card becomes ONE `hermes … chat` turn on the
bot that owns its role, in its own session, so the whole board is readable — live,
while it runs — in Hermes Desktop's **Bots** tab.

It is not a replacement. The kanban driver is the one that *proves* a run; this is
the one you can *watch*.

```
bots/demo.sh                              # every step, on boards/is-even
bots/demo.sh --board boards/<slug>        # any board in this repo
bots/demo.sh --check                      # prerequisites only, run nothing
bots/demo.sh --fresh                      # empty the work directory first (asks; --yes skips)

bots/run-board.py --board boards/<slug>                     # the driver alone
bots/run-board.py --board boards/<slug> --resume            # accept a gate, or continue a halt
bots/run-board.py --board boards/<slug> --rework "<reason>" # reject at a gate
bots/run-board.py --board boards/<slug> --lane 2            # one lane
bots/run-board.py --board boards/<slug> --dry-run           # render prompts into bots-dry-<ts>; writes nothing else

bots/audit.py --board boards/<slug>                         # exit 0 = the run is done
bots/audit.py --run boards/<slug>/runs/bots-<ts> [--json]
```

Exit codes: **0** complete · **10** a gate is held for you · **1** halted.

**On a board whose product is already built, expect `NO CHANGE`.** `reset.sh` archives the cards and
re-files them; it does **not** empty `work/` — nothing in the engine deletes that tree (a run's
product may be the input of a follow-up fix, and DESIGN keeps it a human's own `rm`). So a board run
over an existing product legitimately ends with the cards reporting nothing needed changing, and the
final review returning `NO CHANGE` instead of `PASS`, which `audit.py` reports as `ERROR B4` (exit 1).
Measured both ways on one complete board: one run's review said `NO CHANGE` (B4), the next said `PASS`
with notes (clean) — so B4 here is the wording of the verdict, not a broken driver. Whether to empty
`work/` for a from-scratch run is your call, made outside the engine.

**A card that reports nothing halts the run** — `HALT — <card> reported nothing`, and the transcript
path is printed beside it. That is the contract, not a crash. Seen once with a local model
(2026-09-19, `nex-n25-mini` on a rework card): it declared *"this session has no filesystem/terminal
tools exposed"* and wrote no result, while the same model in the same run had made 24 tool calls on
the card it was revising. Read the transcript before suspecting the spawn — the toolset is identical
for every card, so a model claiming it has none is telling you about itself.

## Files

| | |
| --- | --- |
| `run-board.py` | the driver: the graph, the gates, the rework rounds, one turn per card |
| `audit.py` | judges a finished run; a bot run is done when this exits 0 |
| `card-adapter.txt` | the one translation — how a card reports without a board |
| `demo.sh` | prerequisites → run → audit, for any board |

Tests live with the rest of the suite: `tests/test_bots_driver.py` and
`tests/test_bots_audit.py`, both model-free, both run by `test.sh`.

## What it shares with the kanban driver

Nothing about a board is restated here. The driver imports `template/`:

| From | What |
| --- | --- |
| `board_schema.py` | the option table, its defaults, validation of `board.json` |
| `lanes.py` | the card graph (`lane_cards`), role→profile (`assignee_for`), the review model pin (`model_args`), per-lane options from the idea header, `max_reworks` |
| `card_render.py` | card bodies with every placeholder resolved (`render_body`), a lane's hand-off paths, the work-directory reading |
| `template/card-bodies/` | the card bodies verbatim, worker contract included |

A change to the graph, a card body or an option reaches both drivers at once.

`card_render.py` holds what both drivers need; `file_lanes.py` holds the kanban filing
— `hermes kanban create`, the idea cards, the run-id mint — and this driver imports none
of it. Where a body's paths land is an argument
(`run_root`), not a module global a caller rewrites: a bot run passes its own
`runs/bots-<ts>` and every `<RUNS>`, `<IDEA>`, `<PLAN>` and `<REFINED>` resolves
there.

## One board, one driver

Both drivers build in a board's `work/`, keep runs under its `runs/`, and take its
`runs/driver.lock` — so ONE BOARD is driven one way at a time, by construction
rather than by convention. That is the trade for a single product tree: a bot run
reads whatever the last run left, kanban or bot, exactly as `lane-<k>.md` describes
its input.

The lock is per board, so this says nothing about other boards — run `boards/a` on
kanban and `boards/b` on bots at the same time if you like. What they share across
boards is capacity: the same profiles and the same model backend serve every board
at once.

A dead holder's lock is taken over (a SIGKILL skips the atexit unlink), and the
release only ever drops a lock still holding this driver's own pid.

## What one card looks like

```
hermes -p <profile> chat --in <work> -c "<slug> L<n> <card>" \
    --create-if-missing --query-file <run>/cards/<card>.prompt.txt -Q \
    --model <work or review model> --provider <…> [-s <skill>] --run-budget <max-runtime>
```

- **profile** — the card's role through the board's `assignees` (`researcher`, `coder`).
- **model** — the board's work model, or `model_override`/`provider_override` on a
  review card. Same precedence as filing, from `lanes.model_args`.
- **skill** — what the card force-loads (`writing-plans` on P, `test-driven-development` on TW).
- **budget** — `max-runtime` from the manifest, as `--run-budget`; its default comes
  from the option table, not from a second constant here.
- **session** — one per card, titled `<slug> L<lane> <card>`. Fresh context per card,
  as on the board, and the reason each card is separately readable in the Bots tab.

The prompt is `card-adapter.txt` followed by the rendered body. The adapter
translates exactly one thing — the completion protocol. Where the body says
"complete the card with `--result`", the adapter says "write that same result line
to `<run>/cards/<card>.result.txt`". Hand-off files keep their paths under
`<RUNS>/scratch/<card>/`, and the rest of the body — hard rules, scope, the worker
contract — is binding as written.

The driver reads that file the way the board reads a card's `result` field:
`REJECT…` from a review starts a rework round, `BLOCKED…` halts, a missing file is
a failed card.

## What a card waits for

A card runs when its PARENTS are done — the graph's own condition, not the filing
order. So the lane's one fork (TW ∥ C) genuinely overlaps: both are ready at once
and run as one batch, one thread each. `sequential: true` already makes C wait for
TW inside `lane_cards`, so the MANIFEST decides whether the fork overlaps and this
driver never re-reads that option. If cards remain and none is ready, the run halts
naming them rather than spinning.

Each card's cost lands in `timing.jsonl` — card, code, profile, model, seconds, exit
code, session, first line of the result — including a card that failed, because that
is run cost too. The log carries it per card (`I1 [24s]: …`) and totals it at the
end:

```
ALL CARDS COMPLETE — 6 card(s) in 7m 41s of model time, slowest RVa1 (311s)
```

## Gates

`auto-gates` is read from the manifest exactly as the kanban driver reads it. A gate
listed there is passed by the driver; a gate that is not stops the run with exit
**10** and the held card in `state.json`. Read the files it names — `<REFINED>`,
`<PLAN>`, the work tree — and answer it, the two answers a kanban gate takes:

```
bots/run-board.py --board boards/<slug> --resume                    # PASS
bots/run-board.py --board boards/<slug> --rework "<what is wrong>"  # REWORK
```

`--rework` re-runs the card that wrote what you read — `Gi`→`I`, `Gp`→`P`, `Gc`→`C`
— with your reason appended as a revision round, then holds the same gate again so
you re-read the result. `max-reworks` caps it per gate; past the cap the run halts
and says the lane is a human's call now, which is the board's own escalation. The
reason is required, exactly as at a kanban gate: the revision is built from it.

A review rejection works the same way without you: `REJECT` from `RVp`/`RVa`/`RVc`
re-runs `P`/`C`/`TI` with the review text, then re-runs the review, up to
`max-reworks`.

`boards/is-even` lists all three gates as auto, so the example board runs unattended
end to end.

## Resuming

`--resume` has two jobs, and which one it does depends on how the run stopped:

- **a gate is held** — it is your PASS, and the lane goes on.
- **the run halted** (a card wrote no result, or one blocked) — it continues at the
  card that failed. `state.json` names every card that finished, so those are not
  re-run. Without this a halt costs the whole run.

It refuses, loudly, when `runs/current-bots` names no run with a `state.json` — a
resume that silently minted a fresh run would restart the board from card one. The
same applies to a `state.json` that exists and cannot be parsed: fatal, not ignored.
The file is written whole and moved into place, so a driver killed mid-write leaves
the previous state rather than a truncated one.

Ctrl-C and `SIGTERM` both unwind through the same path: the board's lock is released,
the cards that finished are recorded, and the run ends with `interrupted — … --resume
continues this run` (exit 130) rather than a stack trace.

### `--dry-run` and a live run

A dry run renders each prompt into its own `runs/bots-dry-<ts>/` and writes nothing
else — no pointer move, no session. It also walks the graph, which means it RECORDS
the cards it rendered as done; that is what makes a board walkable without spawning
anything, and it is confined to a `bots-dry-<ts>` run. So a dry run refuses
`--resume`/`--rework` when the pointer names a run a session produced
(`bots-<ts>`): one `--dry-run --resume` against a live run recorded every card as done
and printed `ALL CARDS COMPLETE` with nothing run, after which the next real `--resume`
would skip the whole board (measured 2026-09-20). Drop `--dry-run` to answer a real
run's gate.

## Where the output goes

```
boards/<slug>/work/                  the product — the SAME tree driver/run.py builds
boards/<slug>/runs/
    driver.lock                      the board's one driver lock, taken by both drivers
    current                          kanban's live run — this driver never writes it
    current-bots                     this driver's live run
    <slug>-<ts>/                     a kanban run
    bots-<ts>/                       a bot run:
        driver.log                   one line per card, and the work tree at start
        timing.jsonl                 one line per card: seconds, model, verdict
        state.json                   cards done, gate held, rework rounds — what --resume reads
        cards/<card>.prompt.txt      exactly what the bot was sent
        cards/<card>.transcript.txt  what it answered
        cards/<card>.result.txt      the result field
        snapshots/, artifacts/, scratch/   the lane's hand-offs, at the paths the bodies name
    bots-dry-<ts>/                   a --dry-run: renders prompts, moves no pointer,
                                     and continues only another bots-dry-<ts> run
```

`runs/` is gitignored for both drivers; `work/` is tracked for both, and a human
commits it at a gate. A run id says which driver made it —
`driver/runs-report.py` lists them together.

## The audit

A driver that reached the end is not the same claim as a run that holds together.
`bots/audit.py` is this board's `run-audit.py`: **the run is done when it exits 0**,
and any ERROR or WARNING makes it non-zero. `demo.sh` runs it as its last step.

| | |
| --- | --- |
| B1 | no `driver.log` — the run never started |
| B2 | a card the GRAPH declares never completed (a held gate is reported, not faulted) |
| B3 | a card ran and wrote no result — the result field is the report |
| B4 | a review's last round does not PASS — a lane that shipped a refused deliverable |
| B5 | a card blocked |
| B6 | a result claims `CHANGED: <path>` that is not on disk |
| B7 | a tool cache THIS RUN left in the work directory — a WARNING here, where the kanban audit's E16 reports the same cache as an INFO: the worker contract forbids caches in `work/`, so the stricter reading is the one this driver, which cannot rely on the dispatcher to enforce it, keeps |
| B8 | a lane hand-off (`<IDEA>`, `<REFINED>`, `<PLAN>`) empty or missing |

The declared card list comes from `lanes.lane_cards`, not from what the run happens
to hold — otherwise a run that stopped after two cards would audit as a complete
two-card run.

## Seeing it in the Bots tab

Each card is an ordinary session on its profile, titled `<slug> L<n> <card> <run-id>` —
stamped with the run, so a **rerun opens fresh sessions** instead of resuming the previous
run's conversation (it did resume them until 2026-09-19; a resumed card carried 151 messages
of history and paid for it). Not a hidden `kanban`-source worker, which is why it is visible
at all. In Desktop: the
**Bots** tab, then right-click a bot → **Open recent session** for the card running
now, or its session browser for the rest; Cmd/Ctrl+K and the board's slug jumps
straight to one. A bot row's plain click opens that bot's canonical *Bot Chat*,
which is not where cards run.

```
hermes -p coder sessions list --source cli | grep <slug>
hermes -p coder sessions export --session-id <id> --format md
```

For the Bots tab to list a profile at all it needs Desktop's `ui_meta: {hermes-bots: …}`
marker in `~/.hermes/profiles/<p>/profile.yaml`; `demo.sh` checks for it and says so
when it is missing. Cards run either way.

## What this does not have

Deliberate, and the reason `driver/run.py` stays:

- **No enforcement.** The card contract ("no commits, no branches, no skills, no
  memories") holds because the bot honours it. A kanban worker runs in a dispatched
  process with a claim lock and a breaker; a bot turn is a chat. `audit.py` catches
  the aftermath, not the act.
- **No goal mode.** `goal-cards` is ignored — the Ralph-style judge loop lives inside
  the hermes worker path (`--goal` at filing, `auxiliary.goal_judge` on the profile),
  so a chat turn has nothing to switch on. Not silent: a run whose manifest sets it
  (or `max-retries`) logs `NOT honoured: <option> — <why>` at startup and says to run
  that board on `driver/run.py`. `UNHONOURED` in `run-board.py` is the list.
- **No attachments, no chain, no per-card patches, no board history** — the files
  under `runs/bots-<ts>/` are the whole record, and `audit.py` is thinner than
  `run-audit.py` because of it: it judges results, hand-offs and the work tree, never
  HOW a card worked.
- **One attempt per card**, like the board, but without the dispatcher's breaker: a
  card that writes no result — including one killed for outrunning `max-runtime` —
  halts the run, and `--resume` continues it.
- **Rework targets are declared, not derived** (`REWORK_TARGET` in `run-board.py`).
  Two tests hold it to the graph: every gate in `board_schema.GATE_CODES` and every
  code in `lanes.JUDGE_CODES` must have an entry, and every target must be a real
  card.
- **Bots do not address each other.** Hand-offs are files, exactly as on the kanban
  board. `message_agent` (bot-to-bot DMs) exists only inside a canonical Bot Chat,
  which is not where cards run; a group-chat room would be the place for real
  bot-to-bot conversation, and the gateway's `groups.*` RPCs (`groups.send`,
  `groups.state` with its `driver_status.working`, `groups.log`) are the upgrade path
  if that is ever wanted. It needs a `hermes serve` session token, which Desktop
  mints into its own process.
