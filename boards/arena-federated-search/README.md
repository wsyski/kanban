# arena-federated-search

**The second external-project board.** Like `blade-workspace` it points `default-workdir`
at a repository that already exists, that this repo does not contain, and that has its own
history. The project underneath is a different animal, though: a Maven multi-module Spring
Boot service rather than a Liferay Gradle workspace. Where `blade-workspace` meets
`buildREST`, a testable Tomcat and the Postman collection, this board meets `mvn`, Surefire,
WireMock and HttpComponents 5.

The idea it ships with is **a committed plan to implement**, not a description to write:
the workspace holds `docs/superpowers/plans/2026-09-14-liferay-context-id-resolution.md`
with all 25 of its steps still open, and the card says to work it task by task — write the
failing test, run it, make it pass, stage — without touching the plan's prose.

## The work directory

    "default-workdir": "/opt/projects/arena-federated-search/main/arena-federated-search"

A Java 17 / Spring Boot federated search service: a Maven multi-module repository — its own
`AGENTS.md` (Maven commands, Docker scripts, `newman` integration tests), `DESIGN.md`,
`SECURITY_REVIEW.md`, `integration-tests/` as Postman collections, and the modules
`federation-core`, `federation-liferay`, `federation-solr`, `federation-solr-arena`,
`federation-worldcat`, `federated-search-service` and friends.

**That path is host-local and absolute, so this board does not run as shipped.** Edit
`default-workdir` in `board.json` to a project on your machine before creating the board.
Any Maven repository with a README and a committed plan works: the idea in `lane-1.md` is
about implementing the plan that is there, not about anything specific to this service.

## Preconditions

Beyond the template's own (§2 of the root README — profiles, one dispatcher lock):

- **The work directory is a git repository with a clean index.** Cards verify their work
  with `git diff --cached`, which lists the whole index, so your own pending edits there
  become the lane's evidence and a reviewer judges the lane on them. The plan's own
  pre-flight is `git status --short` clean; check it before arming.
- **You accept work being staged on whatever branch it is on.** The run pins the
  repository, branch and HEAD when the first lane opens (`feature/PLCB-25380` here), and a
  branch switch, a commit under the run, or a path you stage that is not the lane's fails
  `run-audit.py` (E17). Nothing is committed and no branch is moved.
- **A JDK 17 and Maven are enough — nothing has to be running.** Every verification step in
  this plan is `mvn … test` against WireMock, so there is no portal, Tomcat, database or
  port to stand up. `mvn` must be on `PATH` (3.9 here) with a warm `~/.m2`. Task 5 Step 2's
  build of the affected modules may skip repository tests that need Docker (Testcontainers);
  the card reports which tests ran instead of counting a skip as a pass.
- **The project's own agent instructions are in play.** Workers run in the work directory,
  so its `AGENTS.md` is read alongside the card bodies — that is where the `mvn` shapes
  (`-pl … -am`, `-Dtest=…`) and the `newman` rule for integration tests come from.

## Lane shape

`"refinement": true` and `"unit-tests": true` in the manifest with no per-lane header
overriding them, and **`"integration-tests": false`**: the lane files without `TI` and `RVc`
and opens as `I Gi P RVp Gp TW C RVa Gc` — nine cards, three human gates. That level is off
because the plan has nothing for it to run: all nine of its `Run:` steps are
`mvn -pl federation-liferay -am … test`, it touches no Postman collection, and this project's
integration tests are `newman` collections that need a running service instance plus a live
Arena portal — a dependency the plan deliberately does not carry. `RVc` goes with `TI`
because the final review reviews the integration level; `RVa` still reviews the tree the
gate receives, and it waits on `TW` and `C` together.

The plan gate releases `TW` and `C` together: `TW` writes the plan's tests (the spike test
that stays in `LiferaySiteResolverTest`, `TestConfig`'s pinned `RestClient`,
`LiferayEntityHandlerTest`) while `C` writes the handlers beside them, each staging its own
files. `"goal": false`, written out rather than omitted, so no worker card carries the goal
judge or its `--goal-max-turns 40` ceiling: the judge reads only the card's text and has
never vouched for a deliverable, while either of its halt paths — a spent turn budget, or a
`blocked` verdict that makes a worker self-block instead of completing — costs a card its
single attempt.

The plan is the specification and the card adds nothing to it. `### Done means` is what the
code gate judges — every checkbox ticked in the plan file itself, every `mvn … test` the
plan names passing up to Task 5's full build of the affected modules, and exactly the files
its File Structure table names staged in the workspace index (six under `federation-liferay`
plus `DESIGN.md`), nothing committed.

**It consumes what `blade-workspace` builds.** The plan's `LiferaySiteResolver` calls
`GET /o/headless-delivery-ext/v1.0/arena-site` and rewrites Liferay-generated item and media
URLs onto the incoming request's base URL — the endpoint the companion plan in
`boards/blade-workspace` implements. The two boards are the two halves of one feature
(PLCB-25380), which is why this one can only be deployed after that one is.

## Running it

See §3 of the root README for the loop; the board-specific commands are:

    mission/create-board.sh --board boards/arena-federated-search
    hermes kanban boards switch arena-federated-search      # create files the board
                                                            # but leaves it NON-current
    mission/start-board.sh --slug arena-federated-search    # serves; releases nothing
    mission/run-audit.py --runs boards/arena-federated-search/runs   # 0/0 is the pass

`create-board.sh` files eleven parked cards — the complete `LANE_CARDS` set — and the
driver prunes `TI1`/`RVc1` down to the nine-card lane when the lane opens (see *Lane
shape*). The board is IT-complete at filing; the integration level is dropped at arm.

**The go signal is the arm card.** Serve mode releases nothing on its own. Arm lane 1
from a shell — this is the reliable gesture and the one to use:

    mission/arm.sh arena-federated-search 1

`arm.sh` files the idea as a **`blocked`, unassigned** card, which the driver's
`armed_ideas()` reads and the dispatcher never claims, and it archives the board's own
seeded Triage card (whose title it would otherwise duplicate).

**Do not drag the seeded Triage card to Todo on this machine.** `kanban.default_assignee`
is set to `coder`, so a drag leaves the card unassigned-but-`ready` and the dispatcher
assigns it and spawns a worker within seconds; `armed_ideas()` then skips it (it ignores
any card with an assignee, `run.py:2980`), so the driver can never read the idea again —
`_ARMED` stays false, `open_lanes()` skips the lane every tick, and every card sits
`blocked` with nothing running (measured 2026-09-15, this board). If it happens: archive
that card and run `arm.sh` — `block`/`unblock` alone do not clear its assignee.

Never the dashboard's `specify` button: it rewrites the idea with an auxiliary LLM before
the researcher reads it.

`"auto-gates": false`, so three human gates stop the run and nothing downstream moves
until a person completes the card (see §6 of the root README for gate discipline):

- `Gi` — read `refined.md` against this idea; the result's first word is `PASS:` (opens
  the lane) or `REWORK: <what is wrong>` (files a revision and re-gates).
- `Gp` — read `plan.md` and the `RVp` verdict; complete it only with `PASS` on record.
  Its completion releases `TW` and `C` together.
- `Gc` — read `plan.md`, the newest verdict and `git -C <workdir> diff --cached --stat`;
  committing is the gate-holder's call, with an explicit pathspec.

Complete a gate from the shell — the card id is on the board and in the driver's
`HUMAN GATE READY` line:

    env -u HERMES_HOME hermes kanban --board arena-federated-search complete <CARD-ID> --result "PASS: <what you decided>"

Write the gate's own evidence word into the result (`refined idea present` at `Gi`, the
word `PASS` at `Gp`/`Gc`) — the audit checks exactly those tokens in the run snapshot.
The driver never commits and never moves a branch; the workspace index is the hand-off.

## Cleaning up

    mission/reset.sh --board boards/arena-federated-search

Archives the cards and unstages what the last run left in the index. Nothing in the template
deletes a work directory, so pointing one at another repository costs nothing; whether that
repository keeps the board's changes is decided with its own git.

## Timing

`max-runtime` is 60 minutes per card and `max-reworks` is 4. Measured on this host
(2026-09-15, warm 76 GB `~/.m2`): the plan's heaviest command,
`mvn -pl federation-liferay,federated-search-service -am test`, is **33 s** with
`BUILD SUCCESS` and every affected module's tests green — so the ceiling exists for card
generation across 25 steps, not for Maven. The standalone `-Dtest=…` runs the plan repeats
are a fraction of that. `"auto-gates": false`, so the three gates wait for a person: this
board stages into another repository, and committing there is that repository's decision.
