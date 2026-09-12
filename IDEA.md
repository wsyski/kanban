# Open items

What is missing or unsettled, as the board stands.

## 1. Lane chaining has never run

`Gc1 → I2` is checked at the graph level: lane 2's root is parented to lane 1's
code gate, the driver refuses to open lane N while `Gc(N-1)` is unfinished, and the
last card is `Gc` whatever the lane options prune. Each lane also reads its work
directory as it finds it, so lane 2 is told what lane 1 built.

What has never happened is a real two-lane run. `roman-evaluator-java` is the
board, and its prerequisites are all present on this host — JDK 17, Maven 3.9,
hermes 0.21.2 — so this is now a matter of spending the wall clock, not of missing
tooling. The tests cover the edges; whether lane 2's researcher can build on what
lane 1 committed is the part only a run can answer.

## 2. The two enforced invariants, and what still rests on convention

Two guarantees are now checked at runtime rather than trusted:

- **A lane opens only if its cards name the run the driver is writing to.**
  `lane_paths_agree` reads the lane root's filed body and compares its `<IDEA>` path
  against the current run; a mismatch refuses the lane with the reason, instead of
  letting the researcher write a refined idea the gate will never find. That covers
  every cause — a run minted on a restart, a hand-edited `runs/current`, a board
  refiled against the wrong directory — not just the one that was imagined.
- **The work directory cannot move under a live run unnoticed.** A branch switch, a
  commit or reset, or a path staged in an external tree that is not the lane's are
  reported once and fail the audit (E17). Reported, never corrected: the board's only
  git writes are stage and unstage.

What still rests on convention is narrower: `adopt_and_refile` being the only caller
of `mint_run`, pinned by a source-inspection test. That test is weaker than the
runtime check above — it would pass a second caller added inside
`adopt_and_refile` — but a wrong mint is now caught at the next lane open anyway, so
the source test is a hint about intent rather than the guarantee.

