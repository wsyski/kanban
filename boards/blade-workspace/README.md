# blade-workspace

> **This board is a red test.** Its `board.json` is written in the proposed
> naming convention (`IDEA.md` item 2: every Hermes parameter keeps Hermes's
> spelling — `max-runtime`, `name`, `goal`, `default-workdir`), which today's
> `BOARD_KEYS` does not accept. So `create-board.sh` refuses it and
> `mission/test.sh` is red on it, on purpose: the manifest is the specification
> and the engine is what has not caught up. It goes green when items 1, 2 and 7
> land, and it is not to be edited to satisfy the engine in the meantime.

**The external-project board.** Every other board builds into
`boards/<slug>/work/`, a directory the board created and owns. This one points
`default-workdir` at a repository that already existed, that this repo does not contain,
and that has its own history — which is the whole point: it is the cheap smoke
test for running a lane against a real project, the way `minimal-development` is
the cheap smoke test for running one at all.

## The work directory

    "default-workdir": "/home/playground/liferay/workspaces/blade-workspace"

A Liferay Workspace: a Gradle workspace holding one module
(`modules/headless-delivery-ext`, with api/client/impl/test sub-projects), six
configuration environments under `configs/`, a Postman collection, and its own
`AGENTS.md`, `CLAUDE.md` and `DESIGN.md`.

**That path is host-local and this board will not run as shipped.** Edit
`default-workdir` in `board.json` to a project on your machine before creating the
board. Anything with a git repository, a README and some structure works — the
idea in `lane-1.md` is deliberately about describing what is there, not about
any Liferay-specific thing.

## Preconditions

Beyond the template's own (§2 of the root README — profiles, one dispatcher
lock):

- **The work directory is a git repository, and its index is clean.** Cards
  verify their work with `git diff --cached`, and that lists the whole index —
  so your own pending edits in that repository become the lane's evidence and a
  reviewer will judge the lane on them. Check `git -C <workdir> status` before
  arming.
- **You know which branch it is on, and you accept work being staged there.**
  The board stages into whatever branch it finds. Nothing is committed —
  auto-gates are on and the driver commits nothing at all — so the run leaves
  staged changes for you to inspect, keep or throw away.
- **The project's own agent instructions are in play.** Workers run in the work
  directory, so an `AGENTS.md` or `CLAUDE.md` there is read alongside the card
  bodies. For a documentation idea that is usually what you want. Read them
  first if you do not know what they say.

No toolchain is required. The idea is a documentation pass and forbids building,
so no JDK, no Gradle daemon and no warm dependency cache are needed.

## What this board demonstrates

- **A lane that opens on an existing tree.** The idea cannot be satisfied
  without surveying first: the deliverable is a description of what is already
  there, so a card that assumes an empty directory produces a README about
  nothing. This is the brownfield case the template has never run.
- **An idea with no unit-test surface.** Rewriting a README has nothing to test,
  so the manifest says `"unit-tests": false` and the idea repeats it as a header,
  the same way `integration-tests` works on both sides. The engine has neither
  (`IDEA.md` item 1), which is the second reason this board is red: today `TW`
  would be filed anyway and would have to talk itself out of its job. Both files
  state the intent; the engine has to catch up.

## Cleaning up

`mission/reset.sh --board boards/blade-workspace` **refuses** and exits 3: the
work directory is outside the board directory, so deleting it is not the
script's call. Correct, and also more than intended — it takes the run state and
the card archival down with it (`IDEA.md` item 4). Until those separate:

    rm -rf boards/blade-workspace/runs          # run state only
    hermes kanban boards rm blade-workspace     # then archive/remove the board

and clean the work directory yourself, in that repository, with its own git.

## Timing

`max_runtime` is 10 minutes per card, not the 4 that `minimal-development` uses.
The deliverable is small but the researcher and the manager have a real tree to
read first, and a survey that runs out of budget produces a plan about an empty
directory.
