# blade-workspace

**The external-project board.** Every other board builds into `boards/<slug>/work/`, a
directory the board owns. This one points `default-workdir` at a repository that
already exists, that this repo does not contain, and that has its own history. It is
the cheap smoke test for running a lane against a real project, the way
`minimal-development` is the cheap smoke test for running one at all.

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

No toolchain is required: the idea is a documentation pass and forbids building.

## Lane shape

`"refinement": false`, `"unit-tests": false`, `"integration-tests": false`, so the lane
is `P RVp Gp C RVa Gc`: the idea is already specified (its `### Done means` section is
what the code gate judges), and rewriting a README has nothing to test. The idea
repeats `unit-tests: false` as a header. When the lane opens, `I`, `Gi`, `TW`, `TI` and
`RVc` are archived; `RVa` still runs — it reviews the change, not the tests, and is the
only review before the code gate.

The deliverable is a description of what already exists, so the plan cannot be written
without surveying the tree first; a card that assumes an empty directory produces a
README about nothing.

## Cleaning up

    mission/reset.sh --board boards/blade-workspace

Archives the cards and unstages what the last run left in the index. Nothing in the
template deletes a work directory, so pointing one at another repository costs nothing;
whether that repository keeps the board's changes is decided with its own git.

## Timing

`max-runtime` is 10 minutes per card, not `minimal-development`'s 4: the deliverable is
small, but the coder must read a real tree first, and a survey that runs out of budget
produces a plan about an empty directory.
