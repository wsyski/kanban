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
human at the code gate: no card here drives a browser. Keep the default human
gates; auto-gates would skip that check.

    mission/create-board.sh --board boards/roman-evaluator-js
    mission/start-board.sh --slug roman-evaluator-js   # then drag Triage → Todo

A clean start is `rm -rf boards/roman-evaluator-js/work`.