# portfolio-engineering — before you start

**The work directory is the `trader` profile itself** —
`"default-workdir": "/home/wos/.hermes/profiles/trader"` — absolute, as that
option always is, and therefore host-local: edit it on another machine. The lane edits the live tree: no
staging copy, no install step, no second version. The existing cron job, the
`shared_lib/` modules and the scripts around them are what it changes, using what
is already there.

That works because the profile is a git repository. Every change is an ordinary
staged diff, reviewers read `git diff --cached` in that repo, and the gate commit
lands in the profile's own history — the same authorization chain every other
board has, in a different repository.

## Two human preconditions

**Pause the profiles autocommit cron for the board's lifetime.**
`~/.hermes/profiles` has an hourly commit-and-push job (`sync-hermes-profiles.sh`,
feeding a second workstation). The driver's staged index is board state: a cron
that commits it takes the gate's decision away and pushes a half-finished change.
Pause it before arming, resume when the board is done.

**Expect the lane to touch this tree, and let it.** The board promises nothing
about a staged or uncommitted file inside its work directory — the lane may change,
replace or delete what it finds there, and that is the lane's decision, not yours.
What it will not do is commit or branch. `git diff --cached` lists the whole index,
so your own pending edits would reach the lane's evidence: check
`git -C ~/.hermes/profiles status` for information, and once the run is live a path
you stage there is reported and fails the audit (E17). Reported, not unstaged — the
board will not throw away your pending work outside the lane's own paths.

## Cleaning up

    mission/reset.sh --board boards/portfolio-engineering

Clears `runs/` and archives the cards. **It does not touch the profile** — nothing
in this template clears a work directory, which matters more here than anywhere
else: this one is a live tree with six running jobs. The only thing that undoes
work here is git, in that repository.

## Running it

Toolchain: Python 3 and a reachable local LLM endpoint (the profile's
`shared_lib/llm.py` points at `http://localhost:8081/v1`). Nothing else — the
profile brings its own.

    mission/create-board.sh --board boards/portfolio-engineering
    mission/start-board.sh --slug portfolio-engineering
