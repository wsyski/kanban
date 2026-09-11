# minimal-development — the cheap board

The smallest idea that still travels the whole lane. Its purpose is to exercise
the machinery — arm an idea, watch the researcher refine it, act on the gates,
see force-staged code (work/ is scratch, never committed) and a timing report — for as close to nothing as a full run can
cost. Run it after any change to `mission/`, and before trusting a real board.

Everything about the idea is chosen for speed: one parsing module, a handful
of unit tests, no build step, no ambiguity for any card to resolve. The lane
files 11 cards and drops to 9 when it activates: `integration_tests` is false,
so `TI` and `RVc` are archived and `Gc` is re-linked to `RVa`.

Toolchain: whatever the workstation already has — the idea prefers Node.js
with npm (Jest, optionally Bootstrap, fetched into `work/`) and Google Chrome;
the same page files run from any static web server, or from `file://` in
Chrome launched with `--allow-file-access-from-files`. A missing runtime stops the lane at the
researcher card with an install recommendation; nothing is installed.

    mission/create-board.sh --board boards/minimal-development
    mission/start-board.sh --slug minimal-development

Then in the dashboard: drag the Triage card to Todo. A clean start is
`rm -rf boards/minimal-development/work`, or just type a new idea into the Triage card
and drag it again — that archives the previous run for you.

**For a fully unattended smoke run**, set `"auto_gates": true` in `board.json`:
the driver then completes the three gates itself, recording the same evidence,
and still commits nothing. Use it to time the machinery; use the default when
you want to see what a human actually gets asked at each gate.
