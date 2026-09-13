# Role souls

`mission/card-bodies/` holds what a **card** tells a worker. This directory holds what the
**profile** tells it: one `SOUL.md` per profile, versioned with the card graph that routes to them
(`mission/lanes.py`). `human-gate` has no file, because it is not a profile. A person completes a
gate, or the driver does when `auto-gates` is on.

These files are **copies of the live profiles** (`~/.hermes/profiles/<p>/SOUL.md`), refreshed from
live data. The live file is the one Hermes reads, so edit the live profile first and copy it back here.

| profile | live file | cards it works |
|---|---|---|
| `researcher` | `~/.hermes/profiles/researcher/SOUL.md` | I — refines the raw idea into a reviewable one |
| `coder` | `~/.hermes/profiles/coder/SOUL.md` | every other work card: P, TW, C, TI and the RVp/RVa/RVc reviews |
| `trader` | `~/.hermes/profiles/trader/SOUL.md` | no card of its own — domain authority and expected values |

The `manager`, `tester` and `reviewer` profiles are retired (2026-09-12/13). The card graph names
`coder` directly.

## What is inside them, and who owns which part

1. **Line 1** names the profile the file is installed into.
2. **`## Profile Role`**, plus role-specific sections where a role needs them (`researcher`'s
   `## Research Discipline`, `trader`'s `## Portfolio Constraints` and `## Private Skills`). This is
   the only per-role prose.
3. **`## Kanban Cards`**: a short paragraph that is identical in all three files. It does one job:
   it tells a `work kanban task <id>` session that the card body is the entire contract and wins over
   the rest of the SOUL. That precedence has to sit in the system prompt, because the card arrives as
   a tool result.
4. **`## Shared Floor`** and the trailing `skill-sync:response-style` block (124 lines). That block
   is owned by `/skill-sync` from `~/.agents/RULES.md`, which rewrites only what is between its
   markers. Never edit inside it here.

**The card rules themselves are not in the SOUL.** They are in `mission/card-bodies/_worker-contract.txt`,
which every worker and verdict body includes as `<WORKER_CONTRACT>`. It covers:
- board access through `kanban_show` or the CLI, never `tool_search` hunting or sqlite on `kanban.db`;
- no branches, commits, `request-review` or follow-up cards, and no unasked subagents or skills;
- no questions, and `block` when a decision is missing;
- full sentences;
- no memories, skills or config writes, with backups under `/opt/backup/agents/` allowed;
- ending the card as its body says.

Until 2026-09-13 those rules were a 2 KB section in every SOUL. That meant three copies to keep in
sync, and every session of the profile paid for them, desktop, cron and telegram included. Now only
kanban sessions pay, and there is one copy.

The one intentional variant: `trader`'s `## Shared Floor` says *"curate, copy, enumerate, or
restate"* and *"role **and domain** instructions"*, because that profile carries domain
instructions. It is left alone.

## Drift check

```bash
cd mission/roles
PAT='/skill-sync:response-style:start/,/skill-sync:response-style:end/p'   # hub-owned block
CON='/^## Kanban Cards/,/^## Shared Floor/p'                              # the card-precedence paragraph
for r in researcher trader; do
  diff <(sed -n "$PAT" $r/SOUL.md) <(sed -n "$PAT" coder/SOUL.md) >/dev/null \
    && echo "$r: hub block ok"   || echo "$r: HUB BLOCK DRIFTED"
  diff <(sed -n "$CON" $r/SOUL.md) <(sed -n "$CON" coder/SOUL.md) >/dev/null \
    && echo "$r: kanban ok"      || echo "$r: KANBAN PARAGRAPH DRIFTED"
done
for r in researcher coder trader; do
  cmp -s $r/SOUL.md ~/.hermes/profiles/$r/SOUL.md && echo "$r: copy = live" || echo "$r: COPY DIFFERS FROM LIVE"
done
```

Every line should say `ok` or `copy = live`. Stop the second range at `## Shared Floor`, not at the
managed block, or `trader`'s deliberate wording variant reads as drift.

## Refreshing the copies, and installing

Refresh from live (the normal direction):

```bash
for r in researcher coder trader; do cp ~/.hermes/profiles/$r/SOUL.md mission/roles/$r/SOUL.md; done
```

Install into a profile (a fresh profile, or a restore). Back up the live file first:

```bash
for r in researcher coder trader; do install -D -m 644 mission/roles/$r/SOUL.md ~/.hermes/profiles/$r/SOUL.md; done
```

The managed block in these copies is a snapshot. If `/skill-sync` has moved the live block since the
last refresh, installing reverts it, so re-run `/skill-sync` in that profile afterwards. Hermes
re-reads `SOUL.md` per session, so no gateway restart is needed. Hermes scans the file for prompt
injection and blocks the whole file on a hit, so check a changed SOUL with
`agent.prompt_builder._scan_context_content` before relying on it.

## History

- **2026-09-13, card contract moved out of the SOUL:** `## Kanban Cards` was cut to the precedence
  paragraph, and the rules went to `_worker-contract.txt`. The copies were refreshed from live
  afterwards. Pre-edit live files are in `/opt/backup/agents/20260913-104524-soul-kanban-contract/`.
- **2026-09-13, trader fix:** `trader` had been running with no card contract at all. The full
  paragraph was restored from the then-live `reviewer` SOUL.
- **Retired profiles:** `tester` and `reviewer` SOULs can be recovered from this directory's git
  history, from `/opt/backup/agents/20260913-000609-reviewer-tester-souls/`, and from
  `~/.hermes/backups/hermes-backup-2026-09-12-140154.zip`. `manager` can be recovered from
  `~/.hermes/profiles` git history.

## Engine side

Nothing in here is read at runtime. A worker reads its own profile's `SOUL.md` and its card, and the
card graph reads roles, not souls. Give the judge a different model through `model_override` /
`provider_override` in `board.json`, not through a separate profile.
