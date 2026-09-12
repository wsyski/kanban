"""Generic lane graph + idea-file parsing for the kanban board template.

Nothing here knows about any particular board. A board is a directory
`boards/<slug>/` holding `board.json` and one `lane-<k>.md` per lane; this
module only shapes the card graph and reads the options an idea may override.

A LANE is one full instance of the card graph executing one human-entered
idea. Lanes run sequentially: lane k's root is parented to lane k-1's Gc.

The lane opens on a RAW idea and reaches the manager only through a human.
`I` refines what the human wrote into something a plan can be built on, and
`Gi` is where a person accepts that refinement — so the manager plans against
a reviewed idea, never against whatever was typed into lane-<k>.md at 2am.
The refined text is a FILE (`<REFINED>`), like every other hand-off here: a
card comment would be a second, mutable copy of the contract.
"""

# code, card-body file, assignee, parent code (None = lane root), skill
LANE_CARDS = [
    ("I",   "i-body.txt",   "researcher", None,  None),
    ("Gi",  "gi-body.txt",  "human-gate", "I",   None),
    ("P",   "p-body.txt",   "manager",    "Gi",  "writing-plans"),
    ("RVp", "rvp-body.txt", "reviewer",   "P",   None),
    ("Gp",  "gp-body.txt",  "human-gate", "RVp", None),
    ("TW",  "tw-body.txt",  "tester",     "Gp",  "test-driven-development"),
    ("C",   "c-body.txt",   "coder",      "TW",  None),
    ("RVa", "rva-body.txt", "reviewer",   "C",   None),
    ("TI",  "ti-body.txt",  "tester",     "RVa", None),
    ("RVc", "rvc-body.txt", "reviewer",   "TI",  None),
    ("Gc",  "gc-body.txt",  "human-gate", "RVc", None),
]

LABELS = {
    "I":   "idea refinement",
    "Gi":  "idea gate",
    "P":   "implementation plan",
    "RVp": "plan review",
    "Gp":  "plan gate",
    "TW":  "unit tests (RED-first)",
    "C":   "implement",
    "RVa": "reviewer verdict",
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

# codes dropped when a lane runs without unit tests. TW alone: RVa is the CODE
# review (parented to C, "reviewer verdict") and the only review before the code
# gate, so dropping it with the tests would leave the gate unguarded. Not a
# mirror of IT_CODES, and deliberately so.
UT_CODES = ("TW",)


def lane_root_code(integration_tests=True):
    """The card a lane starts from — the FIRST entry of LANE_CARDS.

    Positional, not code-based: open_lane's activation work (snapshot,
    pruning, linking) belongs to whatever card opens the lane, and hardcoding
    "i" there breaks the day I/Gi are removed or reordered.
    """
    return lane_cards(1, integration_tests)[0]["code"]


def card_title(code, lane):
    return f"{code}{lane}: {LABELS[code]} - lane {lane}"


def goal_args(code, enabled=True, max_turns=None):
    """`--goal` flags for a WORKER card at filing time; [] for gates/reviewers.

    ``enabled=False`` — a board whose manifest sets ``"goal": false`` —
    files none of them. The judge gate is a worker self-check that needs a
    REACHABLE auxiliary model; a judge that is reachable but failing returns
    its transport error as the verdict ``continue`` ("not done yet"), which
    makes every goal-mode card uncompletable and the lane unwinnable (the
    harness warns of exactly this wedge and guards only the no-client case —
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
    """
    c = code.lower()
    if not enabled or c.startswith("g") or c.startswith("rv"):
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

    One lookup, so a board that renames its tester renames it everywhere: filing,
    revision cards and the reviewer-feed retry rule all come through here.
    """
    return (assignees or {}).get(role, role)


def lane_cards(lane, integration_tests=True, unit_tests=True, assignees=None):
    """The card graph for one lane, in filing order (parents before children).

    A dropped card's child is reparented by the `prev_id` walk below, so
    `unit-tests: false` hands C straight to the plan gate.
    """
    rows = [r for r in LANE_CARDS
            if (integration_tests or r[0] not in IT_CODES)
            and (unit_tests or r[0] not in UT_CODES)]
    cards = []
    prev_id = None
    for code, body, assignee, _parent_code, skill in rows:
        cards.append({
            "code": code,
            "id": f"{code}{lane}",
            "title": card_title(code, lane),
            "body": body,
            "role": assignee,
            "assignee": assignee_for(assignee, assignees),
            "parent": prev_id,
            "skill": skill,
        })
        prev_id = f"{code}{lane}"
    return cards


import os
import re

import board_schema

# The option set — and the per-lane subset an idea header may carry — is declared
# once, in board_schema. A second copy here is what let the manifest and the
# header spell the same option two different ways.
HEADER_KEYS = board_schema.HEADER_KEYS

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
            value = _as_bool(headers[key], value)
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
