# blade-workspace

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
  The board stages into whatever branch it finds, and pins it: the run records that
  repository, branch and HEAD when its first lane opens, and reports a branch
  switch, a commit made under the run, or a path you staged that is not the lane's.
  Those fail `run-audit.py` (E17). Nothing is committed and no branch is moved —
  staging and unstaging are the board's only git writes — so the run leaves staged
  changes for you to inspect, keep or throw away.
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
  nothing. Every board's idea now says the work directory may hold the previous
  version; this is the board where it is the whole task.
- **An idea with no unit-test surface.** Rewriting a README has nothing to test,
  so the manifest says `"unit-tests": false` and the idea repeats it as a header,
  the same way `integration-tests` works on both sides. The lane opens with 8
  cards instead of 9: `TW` is archived and `C` is reparented to the plan gate. The
  code review still runs — `RVa` reviews the change, not the tests, and it is the
  only review before the code gate.

## Cleaning up

    mission/reset.sh --board boards/blade-workspace

That archives the cards and unstages what the last run left in the index. It works
here exactly as on any other board, because **nothing deletes a work directory** —
pointing one at another repository costs nothing. The run directories under `runs/`
stay too; `rm` them yourself when you want them gone.

Whether the Liferay workspace keeps this board's changes is that repository's
business, decided with its own git.

## Timing

`max-runtime` is 10 minutes per card, not the 4 that `minimal-development` uses.
The deliverable is small but the researcher and the manager have a real tree to
read first, and a survey that runs out of budget produces a plan about an empty
directory.
