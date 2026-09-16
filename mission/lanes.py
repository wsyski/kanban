"""Generic lane graph + idea-file parsing for the kanban board template.

Nothing here knows about any particular board. A board is a directory
`boards/<slug>/` holding `board.json` and one `lane-<k>.md` per lane; this
module only shapes the card graph and reads the options an idea may override.

A LANE is one full instance of the card graph executing one human-entered
idea. Lanes run sequentially: lane k's root is parented to lane k-1's Gc.

The lane opens on a RAW idea and reaches the plan card only through a human.
`I` refines what the human wrote into something a plan can be built on, and
`Gi` is where a person accepts that refinement — so the plan is written against
a reviewed idea, never against whatever was typed into lane-<k>.md at 2am.
The refined text is a FILE (`<REFINED>`), like every other hand-off here: a
card comment would be a second, mutable copy of the contract.
"""

# code, card-body file, assignee, parent code (None = lane root), skill
LANE_CARDS = [
    ("I",   "i-body.txt",   "researcher", None,  None),
    ("Gi",  "gi-body.txt",  "human-gate", "I",   None),
    ("P",   "p-body.txt",   "coder",      "Gi",  "writing-plans"),
    ("RVp", "rvp-body.txt", "coder",      "P",   None),
    ("Gp",  "gp-body.txt",  "human-gate", "RVp", None),
    ("TW",  "tw-body.txt",  "coder",      "Gp",  "test-driven-development"),
    ("C",   "c-body.txt",   "coder",      "Gp",  None),
    ("RVa", "rva-body.txt", "coder",      "C",   None),
    # The integration level is CODER work, not tester work: an end-to-end run is in
    # effect a review OF the whole deliverable, so the errors it uncovers are
    # main-code errors — and they may sit anywhere, including code the earlier review
    # already passed. A card that could only write tests would hand every one of them
    # to a fresh revision card that rediscovers the context from a transcript; the same
    # role, on its second pass, fixes what it just proved wrong. The JUDGEMENT stays
    # independent: RVc reviews the tree the gate receives (its check (e)), so the card
    # that authored the tests and the fixes never certifies them.
    ("TI",  "ti-body.txt",   "coder",     "RVa", None),
    ("RVc", "rvc-body.txt", "coder",      "TI",  None),
    ("Gc",  "gc-body.txt",  "human-gate", "RVc", None),
]

# The graph is a chain — each card's parent is the card filed before it — with ONE
# FORK, declared here because a walk cannot express it.
#
#   Gp ─┬─ TW   (unit tests, when the lane runs them)
#       └─ C    (implementation)
#          └─┴─ RVa   (the review that waits for BOTH)
#
# The unit-test card no longer blocks the implementation card. The plan already carries
# the real code (the plan checklist forbids a TBD), so the implementation has nothing to
# learn from a test file that does not exist yet — and the LANE's done criterion was
# never "the tests are green": it is RVa's verdict, which re-derives the suite itself. What the sequence
# bought was the RED observation (a FAIL witnessed before the implementation existed),
# and that is what moving TW beside C gives up; a lane that needs it back can prove it
# from the two patches at review time.
#
# A code named here ignores the positional parent; the walk still advances past it, so
# every other card keeps its chain. Cards a lane drops (UT_CODES / IT_CODES) are
# filtered out of the parents — `unit-tests: false` narrows RVa to (C,) by itself.
PARENTS = {
    "C":   ("Gp",),
    "RVa": ("TW", "C"),
}

LABELS = {
    "I":   "idea refinement",
    "Gi":  "idea gate",
    "P":   "implementation plan",
    "RVp": "plan review",
    "Gp":  "plan gate",
    "TW":  "unit tests",
    "C":   "implement",
    "RVa": "code review",
    "TI":  "integration tests",
    "RVc": "final review",
    "Gc":  "code gate",
}

# The refined idea's headings, in order. i-body.txt prescribes them and the idea
# gate refuses a file missing any — one list, so the two cannot drift apart.
REFINED_SECTIONS = ("Problem", "Scope", "Open questions", "Assumptions", "Findings",
                    "Verification recipe", "Prior art", "Success criteria")

# codes dropped when a lane runs without integration tests: the integration
# tester AND the final review, because RVc reviews nothing else.
IT_CODES = ("TI", "RVc")

# Roles that never spawn a worker: a gate is completed by a person, or by the
# driver when `auto-gates` is on, so no profile has to exist for it. The dispatcher
# buckets a card whose assignee is not a profile as unspawnable — correct for a
# gate, and the reason `required_profiles` must not demand one.
NO_PROFILE_ROLES = frozenset({"human-gate"})

# The review cards. `model_override` (the review model) is applied to these cards and
# above the board's or the lane's `model` — see lanes.model_args for the precedence.
# to nothing else. Keyed on the CARD CODE, not on a role: every work card is the coder's
# now, so a role cannot tell a verdict card from an implementation one — keyed on
# `coder` the review model would land on the implementation too. Not the goal judge,
# which is `auxiliary.goal_judge` on the worker's profile.
JUDGE_CODES = frozenset({"RVp", "RVa", "RVc"})

# codes dropped when a lane runs no REFINEMENT: the researcher who turns the raw
# idea into a refined one, and the human gate that accepts that refinement. The lane
# then plans from the raw idea itself, and P becomes the lane ROOT — the walk below
# reparents it, exactly as it hands C to the plan gate when TW is dropped.
REFINEMENT_CODES = ("I", "Gi")

# codes dropped when a lane runs without unit tests. TW alone: RVa is the CODE
# review and the only review before the code gate, so dropping it with the tests
# would leave the gate unguarded. Not a mirror of IT_CODES, and deliberately so.
# Dropping TW narrows RVa's declared parents to (C,) — see PARENTS and lane_cards.
UT_CODES = ("TW",)


def lane_root_code(integration_tests=True, refinement=True):
    """The card a lane starts from — the FIRST entry of LANE_CARDS.

    Positional, not code-based: open_lane's activation work (snapshot,
    pruning, linking) belongs to whatever card opens the lane, and hardcoding
    "i" there breaks the day I/Gi are removed or reordered.
    """
    return lane_cards(1, integration_tests, refinement=refinement)[0]["code"]


def card_title(code, lane):
    return f"{code}{lane}: {LABELS[code]} - lane {lane}"


def goal_args(code, cards=(), max_turns=None):
    """`--goal` flags for a WORKER card at filing time; [] for gates/reviewers.

    ``cards`` is the board's ``goal-cards``; ``[]`` (the default) files none of them. The goal judge is a worker self-check that needs a
    REACHABLE auxiliary model; a goal judge that is reachable but failing returns
    its transport error as the verdict ``continue`` ("not done yet"), which
    makes every goal-mode card uncompletable and the lane unwinnable (the
    harness warns of exactly this wedge and guards only the no-client case).
    Nothing else bounds a worker: agent.max_turns is 80 and the
    card's runtime ceiling still applies.

    Turn-based bounding for the cards that produce work (O5: /loop inside a
    one-shot worker was never proven to wake). NEVER on a reviewer or gate
    card: a goal-loop judge can push a card whose success case is BLOCKING
    into completing, silently opening the gate it guards.

    The default is 40, not the global goal-loop default 20: a verifier-heavy plan/implementation
    card legitimately needs more turns than a /goal chat loop (observed: a P1
    attempt died at 20/20 healthy, then finished in 51s with a fresh attempt).
    agent.max_turns (80) is untouched — goal-mode workers measure against the
    goal ceiling, not the agent one.

    The gate/review refusal comes first, so a list naming one cannot arm it.
    """
    c = code.lower()
    if c.startswith("g") or c.startswith("rv"):
        return []
    if code not in (cards or ()):
        return []
    turns = max_turns or board_schema.OPTIONS["goal-max-turns"][1]
    return ["--goal", "--goal-max-turns", str(turns)]


def skill_for(code):
    """The skill a card of this code is filed with — rework rounds reuse it."""
    for row in LANE_CARDS:
        if row[0] == code:
            return row[4]
    raise KeyError(code)


def assignee_for(role, assignees=None):
    """The hermes profile that works a role — the board's `assignees` remapping if
    it names this role, else the role's own name.

    One lookup, so a board that remaps a role remaps it everywhere: filing, revision
    cards and the rework-owner rule all come through here.
    """
    return (assignees or {}).get(role, role)


def any_lane(value, default=True):
    """A per-lane option as ONE answer, for a question asked of the whole board:
    a list is per-lane, so the board needs the profile if ANY lane does."""
    if value is None:
        return default
    return any(value) if isinstance(value, list) else bool(value)


def goal_profiles(cfg):
    """{profile: [worker codes]} for the cards a manifest files with `--goal`.

    The goal judge is each worker profile's `auxiliary.goal_judge`, so this is the
    set of profiles whose judge setting decides a card — create-board.sh prints it."""
    out = {}
    for c in lane_cards(1, integration_tests=any_lane(cfg.get("integration-tests", True)),
                        unit_tests=any_lane(cfg.get("unit-tests", True)),
                        refinement=any_lane(cfg.get("refinement", True)),
                        assignees=cfg.get("assignees")):
        if goal_args(c["code"], cards=cfg.get("goal-cards")):
            out.setdefault(c["assignee"], []).append(c["code"])
    return out


def required_profiles(assignees=None, refinement=True, unit_tests=True,
                      integration_tests=True):
    """Every hermes profile a board needs before its cards can dispatch.

    create-board.sh's pre-flight asks this instead of carrying a list: a
    hand-written one is wrong the moment a role's profile is retired — it then
    refuses to create ANY board, however the manifest remaps — and it cannot tell
    which roles need no profile at all.
    """
    remap = assignees or {}
    # The lane-SHAPE options are part of the answer: a board that runs no refinement
    # spawns no researcher, and demanding its profile would refuse a board that needs
    # nothing of the sort — the same wrong refusal, one option over.
    codes = {c["code"] for c in lane_cards(1, integration_tests=integration_tests,
                                           unit_tests=unit_tests,
                                           refinement=refinement)}
    out = set()
    for code, _body, role, _parent, _skill in LANE_CARDS:
        if code not in codes:
            continue
        if role in NO_PROFILE_ROLES and role not in remap:
            continue
        out.add(assignee_for(role, remap))
    return sorted(out)


def max_reworks(cfg=None):
    """This lane's rework budget: `max-reworks` when the board — or the lane's own
    header — sets one, else the house default.

    NOT `max-retries`, and the difference is the whole point: that is the engine's
    flag for how many times the DISPATCHER may attempt one card (a timeout, a crash),
    and it stays 1 because a failed card is final. This is the board's own retry
    mechanism — a REVIEW that sends work back by filing a revision card — and this is
    how many times it may do that before the lane asks a human.
    """
    set_to = (cfg or {}).get("max-reworks")
    return int(set_to) if set_to else MAX_REWORKS        # see MAX_REWORKS below: the
                                                        # option table holds it


def _model_pair(model, provider):
    """`--model`/`--provider` for one model choice, or [] when none is named.

    The provider travels only beside a model: the engine refuses a provider alone,
    and a bare `-m` is resolved against the profile's own provider — so a local
    model has to name llama-swap or it is asked of the wrong backend.
    """
    if not model:
        return []
    return ["--model", model] + (["--provider", provider] if provider else [])


def model_args(code, cfg, lane_cfg=None):
    """`--model`/`--provider` for a card of this CODE. One precedence, four outcomes.

    The review pin wins where it exists: `model_override` — board-level, review
    cards only — is the model a VERDICT runs on, and it is what keeps a review off
    the author's model (the shipped boards pin it for exactly that). It is
    indifferent to the work model: a board whose work runs locally can still buy a
    stronger verdict.

    Below it, the work model: `model`/`provider`, per lane, resolved by
    `resolve_lane_options` into `lane_cfg` (idea header over board default). `cfg`
    alone is the FILING-time answer, because a board files its cards before any idea
    exists — so filing passes the manifest, and `run.open_lane` re-points a lane's
    parked cards with `hermes kanban set-model` when the header says otherwise.

    Nothing named anywhere → no flag at all, and the card runs its assignee
    profile's own model (the behaviour before 2026-09-13).
    """
    cfg = cfg or {}
    if code in JUDGE_CODES:
        pinned = _model_pair(cfg.get("model_override"), cfg.get("provider_override"))
        if pinned:
            return pinned
    lane_cfg = lane_cfg or {}
    lane_pair = _model_pair(lane_cfg.get("model"), lane_cfg.get("provider"))
    return lane_pair or _model_pair(cfg.get("model"), cfg.get("provider"))


def lane_cards(lane, integration_tests=True, unit_tests=True, assignees=None,
               refinement=True, sequential=False):
    """The card graph for one lane, in filing order (parents before children).

    A dropped card's child is reparented by the `prev_id` walk below, so
    `unit-tests: false` hands C straight to the plan gate — and a card whose parents
    are DECLARED (`lanes.PARENTS`, the fork) has the dropped ones filtered out of its
    list instead, so RVa waits on TW only when the lane runs unit tests at all.
    `refinement: false` drops the lane's first two cards, which leaves P with no
    predecessor: it becomes the ROOT this lane opens on.

    `parents` is a LIST: the fork is the one place a card waits for two.
    """
    rows = [r for r in LANE_CARDS
            if (integration_tests or r[0] not in IT_CODES)
            and (unit_tests or r[0] not in UT_CODES)
            and (refinement or r[0] not in REFINEMENT_CODES)]
    codes = {r[0] for r in rows}
    # `sequential` (board option): the implementation waits for the unit tests instead
    # of running beside them, so one model slot serves one card at a time. It restores
    # the RED observation as a side effect, and costs the lane the fork's overlap.
    declared_parents = dict(PARENTS)
    if sequential and "TW" in codes:
        declared_parents["C"] = ("TW",)
    cards = []
    prev_id = None
    for code, body, assignee, _parent_code, skill in rows:
        declared = declared_parents.get(code)
        if declared:
            parents = [f"{p}{lane}" for p in declared if p in codes]
        else:
            parents = [prev_id] if prev_id else []
        cards.append({
            "code": code,
            "id": f"{code}{lane}",
            "title": card_title(code, lane),
            "body": body,
            "role": assignee,
            "assignee": assignee_for(assignee, assignees),
            "parents": parents,
            "skill": skill,
        })
        prev_id = f"{code}{lane}"
    return cards


import os
import re

import board_schema


def base_code(code):
    """A card's code without its lane and round: `P1`, `P1-rev-1` -> `P`; `RVa1-r2` -> `RVa`."""
    return re.match(r"[A-Za-z]*", code).group()

# The option set — and the per-lane subset an idea header may carry — is declared
# once, in board_schema. A second copy here is what let the manifest and the
# header spell the same option two different ways.
HEADER_KEYS = board_schema.HEADER_KEYS

# The house rework budget — how many times a review may send work back before the lane
# asks a human. Read FROM the option table so there is one declaration of it, and it
# lives here rather than with the function above because this module's board_schema
# imports come after the graph (a module-level read up there is a NameError).
MAX_REWORKS = board_schema.OPTIONS["max-reworks"][1]

_HEADER_RE = re.compile(r"^<!--\s*([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*?)\s*-->\s*$")
_BOOL = {"true": True, "false": False}


def parse_idea(text):
    """Split an idea into (headers, body), or raise ValueError naming every fault.

    `board_schema.validate_headers` is the single authority on what a header is and
    whether its value is usable: it judges a line that merely LOOKS like a header
    (opens `<!--`, carries a `key:`) rather than only one matching the strict key
    class below, so `<!-- auto_gates: true -->` is an error instead of prose, and it
    checks the value against the same option table `board.json` is checked against.
    Extraction stays here because the body is what the caller needs back. The
    idea's PROSE is not this function's business — `board_schema.validate_idea`
    judges that at the doors, where a missing success criterion can still be fixed
    by the person who wrote it.
    """
    problems = board_schema.validate_headers(text)
    if problems:
        raise ValueError("; ".join(problems))
    headers, body_lines = {}, []
    for line in text.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            headers[m.group(1).lower()] = m.group(2)
            continue
        body_lines.append(line)
    return headers, "\n".join(body_lines).strip() + "\n"


def _as_bool(value, fallback):
    """Exactly `true` or `false`. One spelling, so a header always reads the
    same way in every idea file."""
    v = str(value).strip().lower()
    if v not in _BOOL:
        raise ValueError(f"expected true or false, got {value!r}")
    return _BOOL[v]


def _as_value(kind, raw, fallback):
    """One idea-header value, coerced by the option's KIND.

    Per-lane options are not all booleans — `max-reworks` is a count — so each value
    is coerced by its kind rather than failing the LANE. The value itself is
    judged at the doors (`board_schema.validate_headers`); this only has to turn the
    text into the option's own type.
    """
    text = str(raw).strip()
    if kind in ("bool", "gates"):
        # A HEADER is one lane's answer, so it is the boolean form: a lane cannot name
        # a different gate set than the board it belongs to.
        return _as_bool(text, fallback if isinstance(fallback, bool) else False)
    if kind == "count":
        if not text.isdigit() or int(text) < 1:
            raise ValueError(f"expected a positive integer, got {raw!r}")
        return int(text)
    return text


def _board_default(board_defaults, key, lane, fallback):
    """One board default for THIS lane.

    A scalar applies to every lane. A LIST is per-lane, indexed from lane 1, so
    `"integration-tests": [false, true]` reads as "lane 1 without, lane 2 with"
    in the one file that describes the board. A list whose length does not match
    the board's lanes is an error, not a shrug: a missing entry would otherwise
    become a silent default, and the lane that quietly grew or lost its
    integration cards is exactly the bug this shape exists to prevent.

    It stays a DEFAULT. The idea's own header still wins, because the header
    travels with the idea it describes while an index describes a slot.
    """
    value = board_defaults.get(key, fallback)
    if not isinstance(value, list):
        return value
    count = board_defaults.get("lanes", len(value))
    if len(value) != count:
        raise ValueError(
            f"board {key!r} has {len(value)} entries for {count} lane(s) — "
            f"give one per lane, or a single value for all of them")
    if not 1 <= lane <= len(value):
        raise ValueError(f"lane {lane} is outside board {key!r} ({len(value)} entries)")
    return value[lane - 1]


def resolve_lane_options(board_defaults, headers, lane=1):
    """schema default -> board default (scalar or per-lane list) -> idea header.

    One key per option, spelled as `board_schema` spells it, from the manifest
    through the header to this dict — so there is one thing to grep for and no
    translation layer to forget. Every per-lane option resolves the same way;
    nothing here names them individually.
    """
    opts = {}
    for key in sorted(board_schema.PER_LANE):
        default = board_schema.OPTIONS[key][1]
        value = _board_default(board_defaults, key, lane, default)
        if key in headers:
            value = _as_value(board_schema.OPTIONS[key][0], headers[key], value)
        opts[key] = value
    return opts


def read_idea(path):
    """(headers, body) for an entered idea, or None when not entered yet."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    if not text.strip():
        return None
    return parse_idea(text)
