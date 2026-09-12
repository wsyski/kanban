# roman-evaluator-js — a small browser page

One lane: a roman-number evaluator page whose parsing module is unit-tested,
two ways to launch it, and page behaviour a human checks at the code gate. It
moved here from `minimal-development` on 2026-09-11, when that board went back
to being the cheapest possible smoke run.

Toolchain the idea implies: Node.js with npm (module tests, packages fetched
into `work/`) and Google Chrome (the `file://` launch). The researcher records
what is actually present; a missing runtime stops the lane at the researcher
card with an install recommendation — nothing is installed.

The page's behaviour — a row per evaluation, the alert, Reset — is marked for a
human at the code gate: no card here drives a browser. This board runs
auto-gated: the driver completes each gate itself once its evidence is
satisfied, so no card here waits on a person. The page check that `--dump-dom`
cannot make is therefore the OPERATOR's, performed with a browser after the
run; the driver still commits nothing, and the human commit at the gate stays
the authorization record.

    mission/create-board.sh --board boards/roman-evaluator-js
    mission/start-board.sh --slug roman-evaluator-js   # then drag Triage → Todo

Nothing here deletes anything — `mission/reset.sh --board boards/roman-evaluator-js`
archives the cards and unstages what a dead run left in the index, and leaves
every `runs/<run-id>/` and the work directory in place.
Nothing here touches the work directory, so a re-run finds the last run's page and
treats it as the previous version to improve. Delete it by hand if you want a
blank start.