# Role souls

`template/card-bodies/` holds what a **card** tells a worker. This directory holds what the
**profile** tells it: one `SOUL.md` per profile, versioned with the card graph that routes to them
(`template/lanes.py`). `human-gate` has no file, because it is not a profile. A person completes a
gate, or the driver does when `auto-gates` is on.

These files are **copies of the live profiles** (`~/.hermes/profiles/<p>/SOUL.md`). The live file is the one Hermes reads, so edit the live profile first and copy it back here.

The kanban rules are not in the SOULs. They are in the engine's worker skill,
`template/skills/kanban-worker/SKILL.md`, which goes the other way: edit it in this repo, then
install it into the profiles ([The worker skill](#the-worker-skill)).

| profile | live file | cards it works |
|---|---|---|
| `researcher` | `~/.hermes/profiles/researcher/SOUL.md` | I — refines the raw idea into a reviewable one |
| `coder` | `~/.hermes/profiles/coder/SOUL.md` | every other work card: P, TW, C, TI and the RVp/RVa/RVc reviews |
| `trader` | `~/.hermes/profiles/trader/SOUL.md` | no card of its own |

Roles are not separate profiles: one `coder` profile works every non-research card, and each job is
kept apart by the card that names it, so there is one work profile to keep in sync. Review
independence comes from the review model, not from a profile (see Engine side).

## What is inside them, and who owns which part

1. **Line 1** names the profile the file is installed into.
2. **`## Profile Role`**, plus role-specific sections where a role needs them (`researcher`'s
   `## Research Discipline`, `trader`'s `## Portfolio Constraints` and `## Private Skills`). This is
   the only per-role prose, and it describes the profile's daily use: nothing in it is about cards.
3. **`## Shared Floor`** and the trailing `skill-sync:response-style` block (124 lines). That block
   is owned by `/skill-sync` from `~/.agents/RULES.md`, which rewrites only what is between its
   markers. Never edit inside it here.

**The card rules are not in the SOUL.** They are in `template/card-bodies/_worker-contract.txt`,
which every worker and verdict body includes as `<WORKER_CONTRACT>`. It covers:
- board access through `kanban_show` or the CLI, never `tool_search` hunting or sqlite on `kanban.db`;
- no branches, commits, `request-review` or follow-up cards, and no unasked subagents or skills;
- no questions, and `block` when a decision is missing;
- full sentences;
- no memories, skills or config writes, with backups under `/opt/backup/agents/` allowed;
- ending the card as its body says.

They sit in the card rather than the SOUL for two reasons: there is one copy instead of one per
profile, and only kanban sessions pay for them — a SOUL is loaded by every session of the profile,
desktop, cron and telegram included.

## The worker skill

`template/skills/kanban-worker/SKILL.md` holds what a worker needs outside its card's text: the
card wins over the SOUL, project files and the skill; re-read the card after a context compaction;
ignore the engine's own `AGENTS.md`; one card, one job; no deployment without a recorded approval.
Every card a profile works is filed with `--skill kanban-worker` (`lanes.skill_args`), which puts
the skill in the worker's system prompt — the one part a compaction keeps. Its
`requires_tools: [__manual_command_only__]` keeps it out of the skill index, so no other session of
the profile sees it.

`create-board.sh` refuses a board, and the driver refuses to file an armed idea, while a profile
the board needs has no copy or a copy that differs from this repo's
(`lanes.worker_skill_problems`). Install it into every profile, after backing up a live copy:

```bash
for r in researcher coder trader; do
  install -D -m 600 template/skills/kanban-worker/SKILL.md ~/.hermes/profiles/$r/skills/kanban-worker/SKILL.md
  hermes -p $r curator pin kanban-worker    # no curator or background review writes a pinned skill
done
```

Check the copies:

```bash
for r in researcher coder trader; do
  cmp -s template/skills/kanban-worker/SKILL.md ~/.hermes/profiles/$r/skills/kanban-worker/SKILL.md \
    && echo "$r: worker skill ok" || echo "$r: WORKER SKILL DRIFTED"
done
```

The one intentional variant: `trader`'s `## Shared Floor` says *"curate, copy, enumerate, or
restate"* and *"role **and domain** instructions"*, because that profile carries domain
instructions. It is left alone.

## Drift check

```bash
cd template/roles
PAT='/skill-sync:response-style:start/,/skill-sync:response-style:end/p'   # hub-owned block
OWN='/skill-sync:response-style:start/q;p'                                # everything the repo owns
for r in researcher trader; do
  diff <(sed -n "$PAT" $r/SOUL.md) <(sed -n "$PAT" coder/SOUL.md) >/dev/null \
    && echo "$r: hub block ok"   || echo "$r: HUB BLOCK DRIFTED"
done
for r in researcher coder trader; do
  diff <(sed -n "$OWN" $r/SOUL.md) <(sed -n "$OWN" ~/.hermes/profiles/$r/SOUL.md) >/dev/null \
    && echo "$r: hand-written part = live" || echo "$r: HAND-WRITTEN PART DRIFTED"
  cmp -s $r/SOUL.md ~/.hermes/profiles/$r/SOUL.md \
    && echo "$r: hub block = live" \
    || echo "$r: hub block is a snapshot — live has moved on since the copy"
done
```

Every line should say `ok`, `= live`, or the one snapshot line.

**A whole-file `cmp` against the live profile was the wrong check** (changed 2026-09-20): it
failed on all three copies over nothing but the hub block, which `/skill-sync` rewrites in a
profile whenever `~/.agents` changes — so the check was red on a healthy repo and stopped being
read. What this repo owns is everything ABOVE the block (`OWN`); the block is a snapshot, and a
live one that has moved on is the normal state between refreshes, not drift.

## Refreshing the copies, and installing

Refresh from live (the normal direction):

```bash
for r in researcher coder trader; do cp ~/.hermes/profiles/$r/SOUL.md template/roles/$r/SOUL.md; done
```

Install into a profile (a fresh profile, or a restore). Back up the live file first:

```bash
for r in researcher coder trader; do install -D -m 644 template/roles/$r/SOUL.md ~/.hermes/profiles/$r/SOUL.md; done
```

The managed block in these copies is a snapshot. If `/skill-sync` has moved the live block since the
last refresh, installing reverts it, so re-run `/skill-sync` in that profile afterwards. Hermes
re-reads `SOUL.md` per session, so no gateway restart is needed. Hermes scans the file for prompt
injection and blocks the whole file on a hit, so check a changed SOUL with
`agent.prompt_builder._scan_context_content` before relying on it.

## Engine side

Nothing in here is read at runtime. A worker reads its own profile's `SOUL.md`, the installed worker
skill and its card, and the card graph reads roles, not souls. The engine reads
`template/skills/kanban-worker/SKILL.md` only to compare the installed copies with it. Give the review cards a different model (the review model) through `model_override` /
`provider_override` in `board.json`, not through a separate profile.
