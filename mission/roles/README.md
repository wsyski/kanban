# Role souls

`mission/card-bodies/` holds what a **card** tells a worker. This directory holds what the
**profile** tells it — one `SOUL.md` per role, versioned with the card graph that routes to them
(`mission/lanes.py`). Three files, three roles; `human-gate` has none because it is not a profile
(a person completes it, or the driver does when `auto-gates` is on).

Why they live here at all. The card graph is the topology of record, but the behaviour that decides
whether a worker strays lives in its profile — and the profiles were not versioned with it. The
`tester` and `reviewer` profiles were retired on 2026-09-12 and their SOULs survived only in a
`profiles-repo history and a backup zip; the `manager` profile followed on 2026-09-13 and took its
ROLE with it — the plan card is the coder's now, like every other work card; the `trader` SOUL has been
running without the card
contract paragraph (see *Drift found* below) for nobody knows how long. A role's standing
instructions are a repo artifact like the card bodies are, and this is where they stop being one
bad `rm` or one silent omission from mattering.

| profile | installs to | Cards it governs |
|---|---|---|
| `researcher` | `~/.hermes/profiles/researcher/SOUL.md` | I — refines the raw idea into a reviewable one |
| `coder` | `~/.hermes/profiles/coder/SOUL.md` | every other work card: P (the plan), TW (unit tests), C (implementation), TI (integration tests) and the RVp/RVa/RVc reviews |
| `trader` | `~/.hermes/profiles/trader/SOUL.md` | no card of its own — domain authority and expected values |

The `manager`, `tester` and `reviewer` roles were retired (2026-09-13, 2026-09-12, 2026-09-12) and
their cards are the coder's: the card graph names `coder` directly, so there is no role to fall
back from.

## What is inside them, and who owns which part

Each file is the whole SOUL document, in four layers:

1. **Line 1** names the profile the file is installed into.
2. **`## Profile Role`** — the only per-role prose, and the only part a `/skill-sync` run will never
   touch.
3. **Role-specific sections where the role needs them** — `researcher`'s `## Research Discipline`,
   `trader`'s `## Portfolio Constraints` and `## Private Skills`. Nothing else in the set has any.
4. **The shared layers** — `## Kanban Cards` (the card contract: the card body wins, no branches, no
   commits, no memories, end the card exactly as its body says) and `## Shared Floor` — followed by
   the trailing `skill-sync:response-style` block (**124 lines, owned by `/skill-sync` from
   `~/.agents/RULES.md`**; never edit inside it, and do not "fix" it here if a `/skill-sync` run has
   since changed the live copy).

So the per-role delta is line 1 + the role paragraph (+ the role-specific sections, where they
exist). Everything else is shared text and should stay byte-identical across the three — that is what
makes this directory checkable rather than three drifting documents.

## Drift found on 2026-09-13, and what was done

Checked by diffing the three files' halves against each other:

| file | vs the shared text | action |
|---|---|---|
| `researcher` | clean | — |
| `coder` | clean | — |
| `trader` | **missing the whole `## Kanban Cards` paragraph** | restored, spliced byte-for-byte from `reviewer/SOUL.md` (then live) |

Every managed block was already identical across the three (all equal to the hub's), so no
`/skill-sync` repair is implied by any of these files.

The `trader` gap is the one that mattered and the one that was invisible: its live profile ran with
no card contract at all — the paragraph that says the card body overrides everything else in the
file, that no worker commits or writes memories, and that a card ends with `complete`/`block`
exactly as its body names. Installing `trader/SOUL.md` from here fixes the live profile.

Reproduce the check:

```bash
cd mission/roles
PAT='/skill-sync:response-style:start/,/skill-sync:response-style:end/p'   # hub-owned block
CON='/^## Kanban Cards/,/^## Shared Floor/p'                              # the card contract
for r in researcher coder trader; do
  diff <(sed -n "$PAT" $r/SOUL.md) <(sed -n "$PAT" reviewer/SOUL.md) >/dev/null \
    && echo "$r: hub block ok"     || echo "$r: HUB BLOCK DRIFTED"
  diff <(sed -n "$CON" $r/SOUL.md) <(sed -n "$CON" reviewer/SOUL.md) >/dev/null \
    && echo "$r: card contract ok" || echo "$r: CARD CONTRACT DRIFTED"
done
```

All three print `ok` on both lines; a role's own prose is invisible to both ranges, which is the
point — the check is about the shared layers only. **Scope the second range to `## Shared Floor`**:
run it to the managed block instead and `trader`'s deliberate wording variant masquerades as a
card-contract drift, which is exactly how this check read on its first run.

The one intentional variant: `trader`'s `## Shared Floor` says *"curate, copy, enumerate, or
restate"* and *"role **and domain** instructions"*. That is deliberate — that profile carries
domain instructions — so it is left alone rather than homogenised.

## Provenance

`tester` and `reviewer` came out of git history; the files that remain are copies of the live profiles as
they stood on 2026-09-13, hashes below being the pre-edit baseline of each source file.

| file | source | hash |
|---|---|---|
| `researcher/SOUL.md` | live profile, verbatim | `d27734771789d9fc…` |
| `coder/SOUL.md` | live profile + one sentence | `6ef624f3fe1e2541…` (pre-edit) |
| `trader/SOUL.md` | live profile + the restored card contract | `ca8aa8e0c29f92a7…` (pre-edit) |

The three retired roles' files (`manager`, `tester`, `reviewer`) were removed from this directory on
2026-09-13, when those roles were retired and their cards became the coder's. Their SOULs are still
recoverable: `tester`/`reviewer` from this directory's own git history and the backup zip named
below, `manager` from `~/.hermes/profiles` history (the autocommit that deleted the profile keeps the
file).

`5a88285` is the autocommit that deleted the two profiles (2026-09-12 19:11). Verbatim copies of
both, with their `profile.yaml` descriptions, are parked at
`/opt/backup/agents/20260913-000609-reviewer-tester-souls/`, and the full profiles — SOUL, config,
skills, avatar — are inside `~/.hermes/backups/hermes-backup-2026-09-12-140154.zip` (14:01, five
hours before the deletion).

## The edits made to the live text, in full

Three files are not verbatim, all for the same reason: the role paragraphs were written for the
retired worktree/branch topology, and this mission shares one checkout per lane and is stage-only
(§6 — *"Nothing the idea builds enters history except through a gate commit"*).

- **`coder`** — *"in isolated workspaces"* → *"in the lane's shared checkout"*; *"Start from the
  tester's test branch when the card names one"* → *"Start from the tests the tester staged when the
  card names them"*; *"commit logical units"* → *"stage logical units"*. A role paragraph that tells
  the coder to commit invites the one thing the lane forbids; the card body's hard rules override it
  on a card, but the paragraph is what a non-card session reads.
- **`tester`** — the same class of fix: *"commit them on the card's test branch"* → *"stage them in
  the lane's shared checkout"*, and *"against the named commit"* → *"against the staged work"*.
- **`trader`** — the restored paragraph, above.

Its **description** carries the same legacy wording (the tester's says *"on a test branch"*) and is
adjusted the same way when installed; see below.

## The description is the other half of the identity

`hermes profile describe <profile>` is what the kanban orchestrator reads —
`hermes_cli/kanban_decompose.py` builds its prompt from profile descriptions — and the desktop Bot
roster shows it to every agent in the teammate table. The four live profiles already carry
role-accurate descriptions; the two recovered ones need theirs installed:

```bash
hermes profile describe reviewer "Independent verdict lane for everything that reaches a human gate: research dossiers, implementation plans, code diffs, and test evidence. Approves or returns actionable change requests through the same-card review lifecycle, citing concrete evidence. Never edits mission code, writes tests, or deploys. Does not write profile memories."
hermes profile describe tester "Owns tests on both sides of implementation. Writes the failing acceptance tests and stages them BEFORE the coder card runs, then runs the full suite plus domain checks against the staged work and reports reproducible pass/fail evidence. Never implements or fixes mission code, reviews, or deploys. Does not write profile memories."
```

This is not cosmetic. A profile cloned from `coder` inherits coder's description — which says it
*"never authors acceptance tests, reviews"* — so a reviewer bot that keeps it contradicts itself in
the one place the orchestrator reads. One live example: `coder-2` is titled **Reviewer** in the Bot
roster and still carries coder's description.

Do **not** restore the `ui_meta.hermes-bots.chat` key from the archived `profile.yaml`. Canonical
Bot Chats are resolved by session title, and stored session-id pointers are ignored and dropped by
design — restoring one re-imports a dead key.

## Installing

```bash
for r in researcher coder trader; do   # every work card is the coder's; the gates have no profile
  install -D -m 644 mission/roles/$r/SOUL.md ~/.hermes/profiles/$r/SOUL.md
done
```

Line 1 must name the profile the file lands in — edit it if a bot is called something else. When a
profile is installed from here into a **fresh** profile, the rest of that profile still has to
exist (config, credentials, skills); this directory supplies the identity, not the profile.

One caveat with the loop above: the managed block in these files is a snapshot. It matches the
hub's rendering as of 2026-09-13 (verified), but if `/skill-sync` has moved the block in the live
profile since, copying the file back would revert it — install line 1 + the role paragraph instead,
or re-run `/skill-sync` in that profile afterwards.

Then verify the topology from the CLI, because the dispatcher spawns workers as
`hermes -p <assignee> --cli` and reads nothing else:

```bash
hermes profile list
for r in researcher coder trader; do
  printf '%-11s %s\n' "$r" "$(hermes -p $r status | grep -E '  Model:' )"
done
```

## Engine side

Nothing in here is read at runtime — a worker reads its own profile's `SOUL.md`, and the card graph
reads roles, not souls. What changes when every role has a profile of its own is the compensating
machinery: a board's `assignees` map becomes unnecessary, and `model_override`/`provider_override` in a manifest
has to be cleared — it would otherwise silently beat the model the role's own profile pins.
