"""Generic lane graph + idea-file parsing for the kanban board template.

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
    ("I",   "i-body.txt",   "researcher", None,  "brainstorming"),
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

# codes dropped when a lane runs without integration tests
IT_CODES = ("TI", "RVc")


def card_title(code, lane):
    return f"{code}{lane}: {LABELS[code]} - lane {lane}"


def lane_cards(lane, integration_tests=True):
    """The card graph for one lane, in filing order (parents before children)."""
    rows = [r for r in LANE_CARDS
            if integration_tests or r[0] not in IT_CODES]
    cards = []
    prev_id = None
    for code, body, assignee, _parent_code, skill in rows:
        cards.append({
            "code": code,
            "id": f"{code}{lane}",
            "title": card_title(code, lane),
            "body": body,
            "assignee": assignee,
            "parent": prev_id,
            "skill": skill,
        })
        prev_id = f"{code}{lane}"
    return cards


import os
import re

HEADER_KEYS = frozenset({"integration-tests", "auto-gates"})

_HEADER_RE = re.compile(r"^<!--\s*([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*?)\s*-->\s*$")
_BOOL = {"true": True, "false": False}


def parse_idea(text):
    """Split an idea into (headers, body).

    A header is a whole line of the form `<!-- key: value -->`. An HTML
    comment without a `key:` shape is ordinary prose and left in the body.
    An unknown key is an error: a typo must fail loudly, never silently
    produce the wrong lane shape.
    """
    headers, body_lines = {}, []
    for line in text.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            key, value = m.group(1).lower(), m.group(2)
            if key not in HEADER_KEYS:
                raise ValueError(
                    f"unknown idea header {key!r} (known: {sorted(HEADER_KEYS)})")
            headers[key] = value
            continue
        body_lines.append(line)
    return headers, "\n".join(body_lines).strip() + "\n"


def split_ideas(text):
    """Split a document at level-2 headings, in document order.

    Position decides the lane. Text before the first `## ` is preamble and
    is dropped, so a file can carry a title and notes without them leaking
    into lane 1.
    """
    parts, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                parts.append("\n".join(current).strip() + "\n")
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        parts.append("\n".join(current).strip() + "\n")
    return parts


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
    `"integration_tests": [false, true]` reads as "lane 1 without, lane 2 with"
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
    count = board_defaults.get("lane_count", len(value))
    if len(value) != count:
        raise ValueError(
            f"board {key!r} has {len(value)} entries for {count} lane(s) — "
            f"give one per lane, or a single value for all of them")
    if not 1 <= lane <= len(value):
        raise ValueError(f"lane {lane} is outside board {key!r} ({len(value)} entries)")
    return value[lane - 1]


def resolve_lane_options(board_defaults, headers, lane=1):
    """template default -> board default (scalar or per-lane list) -> idea header."""
    it = _board_default(board_defaults, "integration_tests", lane, True)
    ag = _board_default(board_defaults, "auto_gates", lane, False)
    if "integration-tests" in headers:
        it = _as_bool(headers["integration-tests"], it)
    if "auto-gates" in headers:
        ag = _as_bool(headers["auto-gates"], ag)
    return {"integration_tests": it, "auto_gates": ag}


def read_idea(path):
    """(headers, body) for an entered idea, or None when not entered yet."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    if not text.strip():
        return None
    return parse_idea(text)
