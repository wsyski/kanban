# roman-evaluator-js — a small browser page

One lane: a roman-number evaluator page whose parsing module is unit-tested, with two
ways to launch it.

Toolchain the idea implies: Node.js with npm (module tests, packages fetched into
`work/`) and Google Chrome (the `file://` launch). The researcher records what is
actually present; a missing runtime stops the lane at the researcher card with an
install recommendation — nothing is installed.

The page's behaviour — a row per evaluation, the alert, Reset — needs a human with a
browser: no card here drives one, and `--dump-dom` cannot check it. The board is
auto-gated, so the driver completes each gate once its evidence is satisfied and no card
waits on a person. The page check is therefore the OPERATOR's, after the run, before
committing the staged work; the driver commits nothing.

## Running it

    driver/create-board.sh --board boards/roman-evaluator-js
    hermes kanban boards switch roman-evaluator-js       # create files the board
                                                         # but leaves it NON-current
    driver/start-board.sh --slug roman-evaluator-js     # serve; then drop the
                                                         # seeded Triage card in Todo
    driver/run-audit.py --runs boards/roman-evaluator-js/runs      # 0/0 is the pass

Serving releases nothing: the go signal is the seeded Triage card dropped in the **Todo**
column (`driver/arm.sh roman-evaluator-js 1` files the same thing from a shell). A drop in
**Ready** is the one that fails — `kanban.default_assignee` is `coder`, so the dispatcher
claims and spawns it before the driver can read it as the idea.

`driver/reset.sh --board boards/roman-evaluator-js` archives the cards and unstages what
a dead run left in the index. The work directory is never cleared, so a re-run finds the
last run's page and treats it as the previous version to improve; delete it by hand for a
blank start.
