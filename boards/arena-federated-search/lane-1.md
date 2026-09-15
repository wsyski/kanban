## Idea 1: Liferay CONTEXT_ID Resolution Implementation Plan

The workspace has a committed implementation plan with every task still open:

    docs/superpowers/plans/2026-09-14-liferay-context-id-resolution.md

Implement it, task by task, exactly as written. The plan is the deliverable's
specification — this card adds nothing to it and changes nothing in it. Read the
plan first, including its Global Constraints, File Structure and consumer-plan
reference, and treat each checkbox step as: write the failing test, run it, make
it pass, stage.

Ground rules this card enforces beyond the plan:

- Work on the current branch (`feature/PLCB-25380`). The plan's own git rule is
  stage-only ("Git: stage only; the user commits"), and this board's cards add
  nothing to it: the driver never commits and never moves a branch; the human
  commits at a gate.
- Do not edit, reflow or re-copy the plan file. Checkboxes in it may be ticked
  as tasks complete — that tracking is the plan's own convention — but its
  prose, code blocks and constraints stay byte-identical.
- The pre-flights are real: `git status --short` clean in the workspace before
  starting (this card is the only pending edit) and `mvn` building the module at
  hand — every verification step the plan names is `mvn … test`. If a pre-flight
  fails, stop and park the card with what you found, do not work around it.
- If a verification step in the plan cannot pass for an environmental reason
  (no network for a missing Maven artifact, Docker unavailable for the
  Testcontainers repository tests Task 5 Step 2 names), stop at that step,
  report exactly which step and why, and leave the index holding only the tasks
  that genuinely finished. Partial staging that the plan did not sanction is a
  rework, not progress.

- The committed plan is the lane's specification, not merely an input. The refined idea
  must record its path and carry its task steps in as the criteria to be met, and the
  plan card that follows must cover exactly those steps, one for one, however they are
  tagged — so the lane implements the plan rather than a paraphrase of it. A plan card
  that invents work the committed plan does not contain, or drops steps it does, is a
  defect for the plan review and gate to catch, not to discover after the code is written.

### Done means

- Every checkbox in the plan file is ticked, in the plan file itself.
- Every `mvn … test` the plan's steps name passes, up to and including Task 5's
  full build of the affected modules
  (`mvn -pl federation-liferay,federated-search-service -am test`), with the
  number of tests that ran reported. Repository tests needing Docker may be
  skipped locally — say which ran rather than counting a skip as a pass.
- The files the plan's File Structure table names are staged in the workspace
  git index — six under `federation-liferay` plus `DESIGN.md` — nothing else,
  nothing committed. (`target/` is gitignored and the plan names no generated,
  tracked file to carry.)
- No generated path is hand-edited and no file outside the plan's table was
  touched; `git status --short` in the workspace shows exactly the intended
  staged set and nothing unstaged-or-untracked that the plan did not predict.
