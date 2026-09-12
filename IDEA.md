# Improvement ideas

Raw ideas, not an execution plan. Each item states the gap and the open
questions it opens; none of them prescribes the change.

## Starting condition (what the sketches already show)

Both halves of a board's configuration are closed sets, checked by different
code. `BOARD_KEYS` (`mission/file_lanes.py:50`) is a strict allowlist in
underscore form and `create-board.sh:136` exits on any unknown manifest key;
`HEADER_KEYS` (`lanes.py:131`) is the same idea for idea headers and `parse_idea`
raises on an unknown one. A typo in either is a typo in the board's shape.
Measured against them, three shipped boards do not create:

    board.json
      minimal-development unit_tests                      item 1, underscore sketch
      blade-workspace     unit-tests                      item 1, proposed spelling
                          auto-gates, default-workdir, goal, integration-tests,
                          max-retries, max-runtime, name  item 2
      minimal-goal-mode   auto-gates, goal, integration-tests,
                          max-retries, max-runtime, name  item 2
    lane-1.md
      blade-workspace     <!-- unit-tests: false -->      item 1 — not in
                                                          HEADER_KEYS, so the
                                                          idea does not parse

`minimal-development`'s `unit_tests` is the original sketch asking for item 1;
`blade-workspace` asks for the same option in the spelling item 2 argues for, and
it is the board that actually needs it — a README rewrite has nothing to unit
test, so `"unit-tests": false` is the honest manifest and `TW` being filed anyway
is the defect. The other keys are the proposed convention, checked in so it has
something to point at rather than only a paragraph describing it. Their refusal is
the feature working.

**Read those three manifests as red tests.** Each one is a failing
specification, written in the naming the engine should have, checked in so the
gap is executable rather than described. They are already wired to the suite —
`test_shipped_boards.py` asserts exactly this and is **red right now**, on the
manifests and on the one idea file that carries a proposed header:

    FAILED test_every_shipped_manifest_uses_known_keys
    FAILED test_every_shipped_idea_parses_and_fits_its_board
    2 failed, 194 passed

So the loop for the items below is the ordinary one: the test is red, the item
says what would make it green, and nothing is done while it stays red. An item
lands when `mission/test.sh` passes with these boards unchanged — changing a
board to satisfy the engine would be editing the test to match the bug.

(The assertion stops at the first offending board, so it names one and the set
stays hidden. It should report all three: a red test that under-reports its
subject invites fixing one third of the job and calling it done.)

## 1. Unit tests configurable exactly like integration tests

A board can drop `TI`/`RVc` with `"integration_tests": false`; it cannot drop
the unit level. Some ideas have no unit surface at all — a README rewrite, a
config install, a documentation pass — and for those `TW` is a card that exists
to be talked out of its job.

`boards/blade-workspace` is that board and now says so **on both sides**:
`"unit-tests": false` in its manifest and `<!-- unit-tests: false -->` at the top
of its `lane-1.md`. Its idea is a documentation pass on an external project that
forbids building, so there is nothing for `TW` to test and no honest `DONE WHEN:`
for it to meet.

Both are red, and they fail differently, which is the point: the manifest key
fails the key allowlist, and the header fails `parse_idea` — `HEADER_KEYS` does
not contain `unit-tests`, so the idea does not parse at all
(`test_every_shipped_idea_parses_and_fits_its_board`). The header is the half
that must not be forgotten: a board-level option with no header is not
"configurable in the same way as integration tests", and an idea that carries
`<!-- integration-tests: false -->` while its sibling option has no header is the
asymmetry item 7 exists to make impossible.

    "unit-tests": [false, true]        # board.json, scalar or one entry per lane
    <!-- unit-tests: false -->         # lane-<k>.md, this lane only

(Spelled with a hyphen on both sides, per item 2. `unit_tests` is what the
staged `minimal-development` edit says, and it is a new option that has no Hermes
counterpart, so it may as well be born with the right name rather than migrated
later.)

The schema already declares it — `unit-tests`, per-lane, default true, no Hermes
counterpart — so the manifest and the header are both accepted by the validator
today. What does not exist is the effect: `lanes.py` has `IT_CODES = ("TI", "RVc")`
and no parallel for the unit level, so `TW` is filed whatever the manifest says.

Answering the question this item used to pose: `RVa` is "reviewer verdict",
parented to `C` — it reviews the **code**, not the tests, and it is the only
review before the code gate. So `unit-tests: false` drops `TW` alone and reparents
`C` to `Gp`; it does not mirror `integration-tests: false`, which drops a worker
*and* its reviewer because `RVc` reviews nothing else.

Still open: is `unit-tests: false, integration-tests: true` a legitimate shape or
a misconfiguration to refuse? The schema can express the refusal — it validates
combinations as easily as values — but whether a lane may have integration tests
without unit tests is a judgement about the card graph, not about the manifest.

## 2. Rename the options to match the schema

The rule is settled and `mission/board_schema.py` is where it is written down:
**every option that reaches Hermes keeps Hermes's spelling of its name.** Not
"prefer hyphens" — Hermes's own config keys are underscored (`notifier_profile`,
`agent.max_turns`), so the convention is provenance, and hyphens are just what
Hermes flags happen to use. The template's own options follow the same convention
so the file has one rule rather than a rule and a house style.

The schema validates that: `test_board_schema.py` asserts every pass-through key
equals the flag it becomes. What remains is the engine reading them. The renames:

| today | becomes | because Hermes calls it |
|---|---|---|
| `max_runtime` | `max-runtime` | `--max-runtime` |
| `max_retries` | `max-retries` | `--max-retries` |
| `goal_mode` | `goal` | `--goal` |
| `title` | `name` | `--name` |
| `workdir` | `default-workdir` | `--default-workdir` |

`workdir` → `default-workdir` looks like the awkward one and is the clearest:
Hermes has two flags because there are two scopes — a board's default workdir and
a card's workdir (`--workspace dir:…`, `file_lanes.py:161`) — and `board.json` sets
the board's default, so one key was blurring a distinction Hermes draws.

**Candidates the schema does not cover**, because they are not options yet:

- **`--goal-max-turns 40`** (`lanes.py:97`) — hardcoded, on the one feature
  documented to wedge. If it becomes an option it is `goal-max-turns`.
- **`--max-retries "1"` hardcoded for revision cards** (`run.py:349`, `:1092`) —
  so `max-retries` governs the first filing and not the rework rounds, which
  README §5 states as a rule and the manifest does not hint at.
- **`--assignee`** — the profile names live in the card graph; a board that wants
  different profiles has no key.
- **`--timeout-min`** — the driver's own runtime cap, `start-board.sh`'s flag,
  default 240, not expressible per board. Spelling already agrees.

Open question: accept the underscore spellings during a transition, or hard-cut
and let the validator's rename hints be the migration message? It already prints
`unknown option 'max_runtime' — did you mean 'max-runtime'?`, which is most of
what a transition would buy.

## 3. A lane must know it opened on an existing tree

"The driver never clears `work/`" is already true and already documented twice —
that is not the gap. The gap is that **nothing tells the lane it inherited
something**. The researcher and the manager are handed `<WORKDIR>` and no signal
whether it is empty, holds the last run's product, or is a project with years of
history. So a brownfield task is planned as if it were greenfield, and the first
thing a card does is overwrite the input.

What the board seems to want: the workdir's state is part of what the lane is
given. An idea that says "improve X" needs the researcher to survey X before
refining, and the manager to plan against what is there rather than against a
blank directory. Probably the triage card should say what it found (empty / last
run's product / foreign tree with N tracked files on branch B), and the refined
idea should have to account for it.

Open question: is the survey a new card, a mandated section in `refined.md`, or
just a rendered value in the bodies alongside `<WORKDIR>`? The cheapest thing
that removes the greenfield assumption is the right one.

## 4. The work directory may be an existing external project

`workdir` stays **optional**: omitted, it resolves to `boards/<slug>/work/`
exactly as today (`create-board.sh:125`, `reset.sh:66`), and every board that
does not name it is unaffected by anything below. This item is only about what
the key means when it IS set to somewhere the board does not own.

`boards/blade-workspace` is the example: `workdir` points at a Liferay workspace
that is its own git repository, on `main`, with its own history, its own
`AGENTS.md` and `CLAUDE.md`, and no relationship to this repo. That is the case
worth supporting — the board as a way to run work on real projects rather than
on toy directories it created itself — and it breaks several assumptions at
once. Naming them, not solving them:

- **The deliverable leaves this repo's history.** README §6's whole
  authorization story is "`work/` is tracked here, and the human's commit at a
  gate puts it in history." With an external workdir the product lives in
  another repo's branch. Who commits there, with what pathspec, and does a gate
  that cannot reach the deliverable's history still mean anything?
- **A foreign index has another writer.** Trap #29 (`git diff --cached` lists
  the whole index, not just your directory) bites much harder in a repo the
  operator is also working in: their pending edits become every card's evidence.
  A clean index and a known branch look like preconditions the board should
  verify and refuse on, the way `create-board.sh` already refuses a missing
  dispatcher lock.
- **`reset.sh` refuses too much.** The guard at `reset.sh:73` fires *before*
  `rm -rf "$WORKDIR" "$BOARD_DIR/runs"`, so an external-workdir board cannot
  clear its run state or archive its cards either — the one thing that must
  never be deleted takes the other two down with it. Those are two jobs and
  want separating.
- **The board is not portable.** Every other board is self-contained; this one
  hardcodes a path that exists on one host. A documented placeholder the
  operator edits, an env-var expansion, or an explicit "host-local, will not run
  as shipped" note in the board's README — but not silence.
- **The external project has its own agent instructions.** `AGENTS.md`,
  `CLAUDE.md`, `.claude/` in the workdir are read by the workers that run there.
  That may be exactly right (the project's conventions should govern its code)
  or a collision with the card bodies' hard rules. Either way it is now in play,
  and no board has hit it yet.
- **Auditor assumptions.** `run-audit.py`'s E16 (no tool caches left under
  `work/`) and the driver's cache sweep assume a directory the board owns. In a
  foreign tree a `.gradle/` was already there and is not the run's litter.

## 5. A minimal `goal: true` example — done

`boards/minimal-goal-mode` now ships: `"goal_mode": true`, one lane, one function
(`sign`) and three cases, no build tool, 6-minute ceiling, `max_retries: 1`.
Verified to file 9 cards with the goal flags on exactly `I`, `P`, `TW`, `C` — and
on no reviewer or gate — with all four of those bodies carrying the `DONE WHEN:`
line the judge reads.

What is left is the thing the board could not solve: **the precondition has no
probe.** The template never names the judge's auxiliary model and ships nothing
that pings it, so the board's README has to tell the operator to check
empirically — arm it and watch `I1`. That works, and it is the reason the board
is tiny and its ceiling short (a wedge declares itself in about twelve minutes
instead of an hour), but "run a whole board to find out whether a model answers"
is a probe by accident rather than by design. A real one belongs beside
`create-board.sh`'s other pre-flight checks: a board that sets `goal_mode` should
be refused on a machine whose judge cannot answer, the way it is already refused
when nothing holds the dispatcher lock.

## 6. The header check has two doors, and the dashboard is not one of them

Mostly done. `board_schema.validate_idea` judges a `lane-<k>.md` against the same
`OPTIONS` table as the manifest — headers are converted to the mapping a manifest
would have carried (JSON is the bridge, because that is what `board.json` is
written in) and handed to the same `validate`, restricted to the per-lane options
and refusing the array form. So `HEADER_KEYS` is the per-lane subset rather than a
second list, values are checked at the header instead of dying later in `_as_bool`,
and the two silent faults are caught:

    <!-- auto_gates: true -->          # underscore: not lanes._HEADER_RE's key
                                       # class, so no match, so PROSE, so ignored
    <!-- auto-gates: true --> keep     # trailing text: same silence

`create-board.sh` and `start-board.sh` both run it over every `lane-*.md`.

**What survives is the channel.** Both doors are shell entry points. An idea
dragged from Triage to Todo on the dashboard is adopted and filed by `run.py`,
which calls `lanes.parse_idea` directly (`run.py:109`, from `:466`, `:653`,
`:1417`) — and that parser still fails open on a shape it does not match and
raises bare on a key it does not know. So the operator who typed the header is the
one person the check cannot reach: a ValueError there surfaces as a driver that
stopped, or a log line nobody is reading, at a moment that looks exactly like a
slow board.

The fix is not a third validator. It is `run.py` calling this one at
triage→todo adoption, before `file_board`, and writing the result back onto the
card that was just dragged — where the triage card already prints the resolved
options and their provenance. `lanes.parse_idea` can then stop being a second
opinion about what a header is.

Not in the idea refinement: `I` is the wrong actor and too late. Headers decide
the lane's *shape* — which cards exist at all — and that is settled at filing,
before `I` runs. A header that wrongly archived `TW` cannot be caught by a card
whose siblings it already chose.

## 7. The consumers still read the old names

`mission/board_schema.py` now exists and is the one declaration: the option table,
in the naming of item 2, with types, defaults, the per-lane subset (from which
`HEADER_KEYS` is derived rather than written a second time), and the Hermes flag
each pass-through becomes. It validates values, not just keys — the three faults
that used to pass every check are covered, and it reports every problem rather
than the first. `create-board.sh` runs it before the board is created,
`start-board.sh` before a driver reads the file, and
`mission/board_schema.py --schema` prints the set.

What is left is the rename itself. The schema states the target; the ~136
references across `file_lanes.py`, `lanes.py`, `run.py`, `run-audit.py`,
`render-flow.py`, `create-board.sh` and `reset.sh` still read `integration_tests`,
`auto_gates`, `max_runtime`, `max_retries`, `goal_mode`, `workdir` and `title`. So
a validated manifest is currently one the engine cannot use, which is the red
state working as intended — and the two duplicate key sets
(`file_lanes.BOARD_KEYS`, `lanes.HEADER_KEYS`) are the ones to delete, not to
edit, since the schema derives both.

Two consumers deserve naming because a rename that misses them fails late rather
than loudly: `run-audit.py` reads `max_runtime` and `auto_gates` at **audit**
time, and `render-flow.py` at diagram time — neither goes through
`create-board.sh`, so neither is protected by the pre-flight.

## Other suggestions

8. **`ERRORS.md` is deleted but still cited fifteen times.** README points at it
   as the authority for O4, O7, O8, O10, #29, #31, #37 — the open traps and
   their history. Either the traps move into README §3 and the references go, or
   the file comes back. A README whose citations all dangle is worse than one
   that never cited.

9. **`README.md` is 725 lines and is doing four jobs** — tour, design
   specification, run log, and operational runbook. §4's per-run tables age out
   every run while §1 and §6 are the stable contract. Splitting the run records
   out would stop a routine re-run from touching the document that defines the
   board.

10. **The idea file's BODY has no schema.** Its headers do now; the prose beside
   them is checked only for parsing and a lane number that fits. A missing
   `### Done means` or an empty lane file still costs a full card cycle to
   discover, at the same moment `board_schema.py` already runs over that file.

11. **The red tests under-report, and the idea files have no equivalent.**
   `test_shipped_boards.py` already checks manifest keys, idea parsing, lane
   counts, and that no board commits run state — so the conventions *are*
   machine-checked, and the three manifests above are red against that check
   today. Two gaps: it names only the first offending board (see above), and
   the idea side has one red case: `blade-workspace/lane-1.md` carries
   `<!-- unit-tests: false -->`, which the schema accepts and `parse_idea`
   rejects, so the file fails to parse. That contrast is the spec for item 1's
   header half — the schema says the option exists and the engine says it does
   not.

12. **Lane chaining still has no run behind it** (`Gc1 → I2`,
    `roman-evaluator-java`). It is the only part of the graph documented as
    untested, and it is also the part a second lane silently depends on.
