# Run records

The most recent run of each board that has run. Per-run state lives beside each
board in `boards/<slug>/runs/<run-id>/`; this file is the human-readable summary,
and it is the only place in the repo that ages out every time a board runs. The
board's design and rules are in the top-level `README.md`.


Two boards have run. These are their most recent runs — the only run records
this README keeps; each board's `runs/` holds its own current-run state.

### `minimal-development` — run 15, 2026-09-11 23:32 → 23:42

One lane, idea `is_even` (one Python function and its tests), 9 live cards
(`TI1`/`RVc1` archived: `integration-tests: false`), auto-gates, goal mode off,
**4-minute ceiling per card, board-wide**.

| card | role | agent min |
|---|---|---|
| I1 refine idea | researcher | 1.33 |
| Gi1 idea gate | auto | 0.00 |
| P1 plan | manager | 0.87 |
| RVp1 plan review | reviewer | 0.58 |
| Gp1 plan gate | auto | 0.00 |
| TW1 tests RED | tester | 0.62 |
| C1 implement | coder | 0.38 |
| RVa1 review | reviewer | 1.22 |
| Gc1 code gate | auto | 0.00 |
| **total** | | **wall 10.4 min, agent 5.0 min, overhead 5.4 min** |

Gates: `Gi1` auto (refined idea present, all sections, 10 findings with
evidence), `Gp1` auto (plan verdict PASS), `Gc1` auto (2 files staged, verdict
PASS) — **nothing committed**. Deliverables: `work/is_even.py` and
`work/test_is_even.py`, staged. `run-audit.py`: **0 errors, 0 warnings**;
`doc-chain.py`: `OK: 0 findings` over 9 cards; reviews `RVp1/Gp1/RVa1/Gc1` all
PASS. Role share: reviewer 1.8 min (36%), researcher 1.3 (27%), manager 0.9
(17%), tester 0.6 (12%), coder 0.4 (8%).

Comments — what this run is for:

- **It is the machinery's smoke test**, worth running after any change to
  `mission/`: arm an idea, watch the researcher refine it, read the gates and
  the timing report, and check the auditor — for about ten minutes of wall clock
  and almost nothing to review.
- **Overhead is the cost centre, not the cards.** More than half the wall clock
  is not agent work: it is the dispatcher claiming a card, the 20 s poll
  interval and provider latency. Cheaper cards would not shorten this run much;
  a tighter loop or a faster provider would.
- **The 4-minute ceiling is a detector, not a target.** The worst card took
  1.33 min — 3× headroom. On an idea this small a card that needs longer is a
  card body doing work the idea does not ask for, which is how an over-long plan
  review was caught.
- **Human gates cost no agent time** (0.00 each) because the driver plays the
  gate-holder role; they are still the only place a human can intervene, and on
  an auto-gated board they never wait for one.

### `roman-evaluator-js` — run 1, 2026-09-11 23:58 → 2026-09-12 00:16

One lane, idea `roman-evaluator` (browser page at `work/roman-evaluator.html`,
DOM-free parsing ES module with unit tests, executable `run.sh`, two launch
modes), 9 live cards, auto-gates, goal mode off, **10-minute ceiling per card**.

| card | role | agent min |
|---|---|---|
| I1 refine idea | researcher | 3.30 |
| Gi1 idea gate | auto | 0.00 |
| P1 plan | manager | 3.20 |
| RVp1 plan review | reviewer | 1.33 |
| Gp1 plan gate | auto | 0.00 |
| TW1 tests RED | tester | 1.72 |
| C1 implement | coder | 1.13 |
| RVa1 review | reviewer | 2.50 |
| Gc1 code gate | auto | 0.00 |
| **total** | | **wall 18.9 min, agent 13.2 min, overhead 5.7 min** |

Gates: `Gi1` auto (refined idea, 25 findings with evidence, 21 795 bytes),
`Gp1` auto (plan verdict PASS), `Gc1` auto (**9 files staged**, verdict PASS) —
**nothing committed**. `run-audit.py`: **0 errors, 0 warnings**; `doc-chain.py`:
`OK: 0 findings` over 9 cards; reviews `RVp1/Gp1/RVa1/Gc1` all PASS. Role share:
reviewer 3.8 min (29%), researcher 3.3 (25%), manager 3.2 (24%), tester 1.7
(13%), coder 1.1 (9%).

Deliverables, all staged under `work/`: `roman-evaluator.html`, `style.css`,
`roman.js`, `main.js`, `roman.test.js`, `run.sh`, `jest.config.js`,
`package.json`, `package-lock.json`, plus the installed `node_modules/`
(untracked, reproducible from the staged lockfile). What was verified on the
finished artifact:

- `npm test` (Jest 30, `NODE_OPTIONS=--experimental-vm-modules`): **8 passed / 8**.
- `./run.sh --headless --dump-dom`: prints the page's DOM, exit 0.
- No absolute path, `file://` or `http(s)://` reference in the delivered HTML,
  JS or CSS; every `import` is `./`-relative.
- `./run.sh` with `google-chrome` off `PATH`: exit 1 with
  `run.sh: google-chrome not found on PATH`.
- `RVa1` re-derived the parser independently — an oracle over all of 1..3999
  (0 mismatches) and 24 malformed inputs, all rejected — and proved the coder
  changed no test file: the suite the coder turned green is byte-identical to
  the one the tester made red.
- **Page behaviour, checked after the run in both launches, in real Chrome
  153.0.8010.36**, since no card in this lane may drive a browser: over HTTP
  (`python3 -m http.server 8000`) and from `file://` through the deliverable's
  own `./run.sh` (Chrome's CDP attached, so the flag and throwaway profile under
  test are `run.sh`'s own). Evaluating `XIV` appends exactly one row reading
  `XIV = 14`; a second numeral appends a second row and keeps the first, in
  order; `IIII` raises an alert reading `Not a valid roman numeral: IIII` and
  appends nothing; `Reset` empties both the input and the display; `MMMCMXCIX`
  gives `MMMCMXCIX = 3999`; `ABC` raises `Not a valid roman numeral: ABC` with
  no row. Identical in both launches, and the nine delivered files' sha256 sums
  were unchanged by the check — nothing in the frozen deliverable was written.

Comments — what this run shows:

- **A real (if small) idea costs about twice the smoke board**: 13.2 min of
  agent work against 5.0, with refinement and planning dominant (I1 3.3, P1 3.2)
  because those cards carry the environment facts — Chrome's `file://` module
  block, the flag that lifts it, `run.sh`'s throwaway profile, Jest's ESM flag.
  The code cards stay cheap (TW1 1.7, C1 1.1).
- **Page behaviour is deliberately not a card.** `--dump-dom` can click nothing
  and cannot see an `alert()`, so "evaluating `XIV` appends one row, `IIII`
  shows an alert and appends nothing, Reset clears both" is checked by a human
  — with a browser, in both launches — not by the lane. This is why the board
  keeps that check out of its card bodies and says so in its own README.
- **The ceiling was never close.** The worst card took 3.3 min against 10, so
  the 10-minute board-wide budget is headroom here, not a constraint that
  shaped the work.
- **The nine files are yours to commit** — the deliverable is tracked, and the
  gate commit is its authorization record; an auto-gated run leaves them staged
  until you commit. A later idea on this board inherits them (that is what makes a
  fix task possible); deleting them is your call, made by hand — no command here
  does it.

### Running the unit tests

The tests are the lane's deliverables, so these are the commands the cards ran —
from the repo root, each in its own board's work directory:

```
# minimal-development — pytest, the four cases 0, 4, 7, -3
cd boards/minimal-development/work && pytest test_is_even.py -q
#   ....                                                             [100%]
#   4 passed in 0.00s

# roman-evaluator-js — Jest 30 over the ES module, eight cases
cd boards/roman-evaluator-js/work && npm test
#   Test Suites: 1 passed, 1 total
#   Tests:       8 passed, 8 total
```

Two traps, both measured on this machine:

- **`python3` first on `PATH` is the Hermes venv and has no pytest**
  (`No module named pytest`, exit 1); the bare `pytest` on `PATH` is
  `/usr/bin/pytest` (pytest 9.0.2, shebang `#!/usr/bin/python3`). So
  `minimal-development` runs the bare CLI — `pytest …`, or explicitly
  `/usr/bin/python3 -m pytest …`, which also works — and a plan whose Run step
  says `python3 -m pytest` fails before collecting.
- **The Jest suite tests an ES module, so it needs
  `NODE_OPTIONS=--experimental-vm-modules`**; `work/package.json`'s `test`
  script already sets it, which is why `npm test` is enough. The same run
  without the script:
  `NODE_OPTIONS=--experimental-vm-modules npx jest`. Bare `npx jest` does not
  fail on assertions but on the module load (`createRequireEsmError`) — a run
  that reports `0 total` is that, not a broken suite.

Neither run writes outside its own work directory, and neither needs the
network or a build step. To run `minimal-development`'s suite without leaving
the pytest caches behind (`work/` holds deliverables only):

```
cd boards/minimal-development/work \
  && PYTHONDONTWRITEBYTECODE=1 pytest test_is_even.py -q -p no:cacheprovider
```

