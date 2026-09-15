# blade-workspace

**The external-project board.** Every other board builds into `boards/<slug>/work/`, a
directory the board owns. This one points `default-workdir` at a repository that
already exists, that this repo does not contain, and that has its own history. It is
the cheap smoke test for running a lane against a real project, the way
`is-even` is the cheap smoke test for running one at all.

The idea it ships with is **a committed plan to implement**, not a description to write:
the workspace holds `docs/superpowers/plans/2026-09-14-headless-delivery-ext-arena-site.md`
with every task still open, and the card says to work it task by task — write the failing
test, run it, make it pass, stage — without touching the plan's prose. That is what makes
this the board where a lane meets a real toolchain: its own build, its own `AGENTS.md`,
integration steps, and a human at every gate.

## The work directory

    "default-workdir": "/home/playground/liferay/workspaces/blade-workspace"

A Liferay Workspace: a Gradle workspace holding one module
(`modules/headless-delivery-ext`, with api/client/impl/test sub-projects), six
configuration environments under `configs/`, a Postman collection, and its own
`AGENTS.md`, `CLAUDE.md` and `DESIGN.md`.

**That path is host-local, so this board does not run as shipped.** Edit
`default-workdir` in `board.json` to a project on your machine before creating the
board. Anything with a git repository, a README and some structure works: the idea in
`lane-1.md` is about describing what is there, not about anything Liferay-specific.

## Preconditions

Beyond the template's own (§2 of the root README — profiles, one dispatcher lock):

- **The work directory is a git repository with a clean index.** Cards verify their
  work with `git diff --cached`, which lists the whole index, so your own pending edits
  there become the lane's evidence and a reviewer judges the lane on them. Check
  `git -C <workdir> status` before arming.
- **You accept work being staged on whatever branch it is on.** The run pins the
  repository, branch and HEAD when its first lane opens, and a branch switch, a commit
  under the run, or a path you stage that is not the lane's fails `run-audit.py` (E17).
  Nothing is committed and no branch is moved, so the run leaves staged changes for you
  to inspect, keep or throw away.
- **The project's own agent instructions are in play.** Workers run in the work
  directory, so its `AGENTS.md` or `CLAUDE.md` is read alongside the card bodies. For a
  documentation idea that is usually what you want; read them first if you do not know
  what they say.

The idea needs the workspace's own toolchain. Its plan runs unit tests, integration tests
and the Postman collection as separate steps, so a JDK, the Gradle wrapper, and whatever
those steps need (`LIFERAY_BASE_URL`, a testable Tomcat) have to be in place — the plan
states its own pre-flights. A pre-flight that cannot pass is a stop: the card says to park
it with what you found rather than work around it.

## Lane shape

`"refinement": true` and `"integration-tests": true` in the manifest, with `"unit-tests"`
turned off by the idea's own header (`<!-- unit-tests: false -->`) — the header wins for
that lane, so the lane files complete and then opens as `I Gi P RVp Gp C RVa TI RVc Gc`:
`TW` is archived at lane open (the plan's steps carry their own failing-test-then-pass
loop), while `TI` and `RVc` stay, because the plan's integration steps and the Postman
collection are exactly what a reviewer has to re-run. `"goal": true`, so every worker card
is judged after each turn (`--goal-max-turns 40`).

The plan is the specification and the card adds nothing to it: it names
`docs/superpowers/plans/2026-09-14-headless-delivery-ext-arena-site.md`, says to work each
checkbox step as *write the failing test, run it, make it pass, stage*, and forbids editing
the plan's prose. `### Done means` is what the code gate judges — every checkbox ticked in
the plan itself, the plan's test steps green, and exactly the files its File Structure
table names staged in the workspace index, nothing committed.

## Cleaning up

    mission/reset.sh --board boards/blade-workspace

Archives the cards and unstages what the last run left in the index. Nothing in the
template deletes a work directory, so pointing one at another repository costs nothing;
whether that repository keeps the board's changes is decided with its own git.

## Timing

`max-runtime` is 30 minutes per card, and `max-reworks` is 4: these cards work a real
codebase with its own build, and an integration step that has to stand up Tomcat and
Elasticsearch is not a 10-minute card. `"auto-gates": false`, so the three gates wait for a
human — this board stages into someone else's repository, and committing there is that
repository's decision.
