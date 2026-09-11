# portfolio-engineering — before you start

The lane builds in this board's own work directory, `boards/portfolio-engineering/work/`,
and **installs into the Hermes `trader` profile** as its final step.

`board.json` declares `~/.hermes/profiles/trader` as a target root: the cards may
write there, and the reviewers count the files there as the lane's own.

One precondition, a human action: **pause the profiles autocommit cron.**
`~/.hermes/profiles` is a git repository with an hourly commit-and-push job
(`sync-hermes-profiles.sh`) feeding a second workstation. The lane edits that
tree without git, so an autocommit firing mid-lane would commit and push a
half-installed job. Pause it for the board's lifetime and resume afterwards.

Toolchain: Python 3 and a reachable local LLM endpoint (the profile's
`shared_lib/llm.py` points at `http://localhost:8081/v1`). Nothing else.

    rm -rf boards/portfolio-engineering/work     # clean start, if re-running
    mission/create-board.sh --board boards/portfolio-engineering
    mission/start-board.sh --slug portfolio-engineering
