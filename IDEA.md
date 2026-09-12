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

## 2. Nothing outstanding here — the invariants are enforced

Recorded because it was the last thing resting on convention, and so that a change
here is a deliberate one.

Three checks hold the run layout together, none of them a matter of remembering:

- **A run is minted only for an armed idea.** `mint_run(run_id, armed)` refuses an
  empty `armed`, so a call on driver start or restart cannot ask for a run, and it
  refuses to re-mint the current one, so two sets of cards cannot land in one
  directory.
- **A restart rejoins.** `use_run(_read_current_run())` at import is the only rejoin,
  proved by a test that imports the driver in a fresh interpreter and asserts nothing
  was minted.
- **A lane opens only if its cards name the run the driver is on.**
  `lane_paths_agree` reads the lane root's filed body and refuses the lane otherwise
  — which catches a wrong run whatever caused it, including a hand-edited
  `runs/current`.

Together they are why a lane cannot inherit a stale `refined.md`: not because
anything is cleared, but because the paths differ and every way of getting that wrong
is refused at the point it would matter.

Nothing prunes `runs/`, by design. `scratch/<card-id>/` grows without bound, since a
worker can write anything there; `mission/runs-report.py` shows what it costs and
deletes nothing.
