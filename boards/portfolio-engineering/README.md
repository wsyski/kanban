# portfolio-engineering — before you start

**The work directory is the `trader` profile itself** —
`"default-workdir": "/home/wos/.hermes/profiles/trader"` — absolute, as that option
always is, and therefore host-local: edit it on another machine. The lane edits the live
tree: no staging copy, no install step, no second version. The existing cron job, the
`shared_lib/` modules and the scripts around them are what it changes, using what is
already there.

That works because the profile is a git repository. Every change is an ordinary staged
diff, reviewers read `git diff --cached` in that repo, and the gate commit lands in the
profile's own history — the same authorization chain as every other board, in a
different repository.

**Gates are human** (`"auto-gates": false`): each gate waits for a person, who decides
what the profile's history receives.

**The goal judge runs on the implementation card only** (`"goal": true`,
`"goal-cards": ["C"]`, `"goal-max-turns": 80`): `C` is the long card most likely to end a
turn without calling `kanban_complete`, and the ceiling equals `agent.max_turns`, so it
loses no turns to the judge. `I`, `P` and `TW` complete on their own evidence.

## Two human preconditions

**Pause the profiles autocommit cron for the board's lifetime.** `~/.hermes/profiles`
has an hourly commit-and-push job (`sync-hermes-profiles.sh`, feeding a second
workstation). The staged index is board state: a cron that commits it takes the gate's
decision away and pushes a half-finished change. Pause it before arming, resume when the
board is done.

**Expect the lane to touch this tree, and let it.** Inside its work directory the lane
may change, replace or delete what it finds; that is the lane's decision. It will not
commit or branch. `git diff --cached` lists the whole index, so your own pending edits
would reach the lane's evidence: check `git -C ~/.hermes/profiles status` before arming.
Once the run is live, a path you stage there is reported and fails the audit (E17) — not
unstaged, because the board does not throw away pending work outside the lane's paths.

## Cleaning up

    mission/reset.sh --board boards/portfolio-engineering

Archives the cards and unstages what a dead run left in the index. **It does not touch
the profile** — nothing in the template clears a work directory, which matters most
here: this is a live tree with running jobs, and the only thing that undoes work in it
is git, in that repository.

## Running it

Toolchain: Python 3 and a reachable local LLM endpoint (the profile's
`shared_lib/llm.py` points at `http://localhost:8081/v1`). The profile brings the rest.

    mission/create-board.sh --board boards/portfolio-engineering
    mission/start-board.sh --slug portfolio-engineering
