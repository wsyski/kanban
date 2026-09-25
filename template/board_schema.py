"""The schema for `boards/<slug>/board.json` — one declaration, validated.

WHY A SCHEMA AND NOT A KEY LIST. `file_lanes.BOARD_KEYS` checks that every key
is spelled right and nothing else, so a manifest can name only known options and
still describe a board that cannot exist:

    "integration-tests": ["yes", "no"]   right length, both entries pass, resolve
                                         to the STRING "yes" — truthy — so BOTH
                                         lanes get integration cards
    "goal-cards": "C"                    a bare string is not a list of card codes, so
                                         the judge is armed for nothing, silently
    "max-runtime": "banana"              handed to --max-runtime; the auditor's
                                         <n><unit> parser reads it as 0 minutes

All three are typos in the board's shape that no key check can see, and the first
is precisely the silently-wrong lane shape the per-lane array's length check
exists to prevent. So the unit of declaration here is the OPTION, not the key:
its type, its default, whether a lane may override it, and the `hermes kanban`
flag it becomes.

NAMING. Every option that reaches Hermes keeps Hermes's spelling of its name —
`max-runtime` because the flag is `--max-runtime`, `name` because it is `--name`,
`goal-max-turns` because it is `--goal-max-turns`, `default-workdir` because it is
`--default-workdir`. A name we invent for a parameter Hermes already named is a
name nobody can grep for. The template's own options (`slug`, `lanes`,
`unit-tests`, `integration-tests`, `auto-gates`, `targets`) have no counterpart
and take the same hyphenated convention, so the file has one rule rather than a
rule and a house style. Hermes's own CONFIG keys are underscored
(`notifier_profile`, `agent.max_turns`) — the rule is Hermes's spelling, which
happens to be hyphens for flags, not "hyphens everywhere".

PER-LANE OPTIONS ARE THE HEADER SET. An option a lane may override is exactly an
option an idea file may carry as `<!-- key: value -->`. Deriving `HEADER_KEYS`
from `PER_LANE` rather than writing it out a second time is what stops the two
sets from drifting: a new per-lane option gets its header for free, and cannot
be added to one side only.

IT JUDGES BOTH FILES. A board's configuration is two files, and an idea header is
the per-lane form of the same option — so `validate_idea` reads a `lane-<k>.md`
against the same `OPTIONS`. One declaration means an option cannot be accepted in
the manifest and refused in the header, and a header cannot mean something the
manifest does not; it also means the header check gets the value validation for
free, which `parse_idea` never had (it accepts `<!-- auto-gates: yes -->` and lets
`_as_bool` fail later, in another caller).

This module reads both files and judges them. It deliberately does NOT read the
keys any consumer uses, so it can state the target shape while the rest of the
template still reads the old spellings.
"""

import json
import os
import re
import subprocess
import sys

# key -> (kind, default, per-lane overridable, hermes flag or None)
OPTIONS = {
    "slug":              ("slug",     None,  False, None),
    "name":              ("text",     None,  False, "--name"),
    "lanes":             ("count",    1,     False, None),
    "default-workdir":   ("abspath",  None,  False, "--default-workdir"),
    "targets":           ("paths",    [],    False, None),
    # The idea's refinement (the researcher's card and the human idea gate behind
    # it). Per-lane like the test levels, so a board built with it can turn it off
    # for one lane and vice versa; `lanes.REFINEMENT_CODES` is what it drops.
    "refinement":        ("bool",     True,  True,  None),
    "unit-tests":        ("bool",     True,  True,  None),
    "integration-tests": ("bool",     True,  True,  None),
    # WHICH gates the driver completes itself, by code: [] is every gate human,
    # ["Gi"] hands it the idea gate, ["Gi", "Gp", "Gc"] the whole board. An array
    # always — one shape, nothing to disambiguate, and no per-lane form: which gates a
    # person holds is a property of the BOARD, like who is watching it.
    "auto-gates":        ("gates",    [],    False, None),
    # The lane's ONE fork (TW ∥ C) becomes a chain: C waits for TW. Board-level,
    # because it is a property of what SERVES the board — a llama.cpp slot with
    # `--parallel 1` serialises the fork into two wall clocks and both cards spend
    # their ceilings on the queue (is-even, 2026-09-16) — not of one lane's idea.
    "sequential":        ("bool",     False, False, None),
    # WHICH worker cards run under the goal judge, by code: [] is none (the judge is
    # off), ["C"] the implementation card only, and the full list every worker card.
    # The same array-always shape as `auto-gates`; there is no separate switch to
    # contradict it.
    "goal-cards":        ("cards",    [],    False, None),
    "max-runtime":       ("duration", "60m", False, "--max-runtime"),
    "max-retries":       ("count",    1,     False, "--max-retries"),
    "goal-max-turns":    ("count",    40,    False, "--goal-max-turns"),
    # TWO different budgets, and the names say which is which:
    #   `max-retries` is the ENGINE's per-card attempt budget (`hermes kanban create
    #   --max-retries`), and the one-attempt rule pins it to 1.
    #   `max-reworks` is the BOARD's own mechanism: how many times a review may send
    #   work back by filing a revision card before a human is asked.
    "max-reworks":       ("count",   3,     True,  None),
    "timeout-min":       ("count",    240,   False, None),
    "assignees":         ("roles",    {},    False, None),
    # The WORK model: every card the board files runs on it, and a lane may name
    # its own in the idea header (`<!-- model: qwen38-27b -->`). Named as the flag
    # it becomes at filing (`hermes kanban create --model`, `--provider`), because
    # that is what a reader greps for. Omitted everywhere, no flag is filed and
    # every card runs its assignee profile's own model — the behaviour before
    # 2026-09-13. `provider` needs a `model` beside it in the same scope, for the
    # engine's own reason: a provider names a backend, not a model.
    "model":             ("text",     None,  True,  None),
    "provider":          ("text",     None,  True,  None),
    # The model a REVIEW runs on, named exactly as the engine names the task
    # property it becomes (`model_override`, with its provider beside it). Board
    # level, NOT per-lane: the header door is for options a lane's own idea may
    # decide, and how strong a review model the board buys is a property of the board.
    # `lanes.model_args` sends them, on the review cards only.
    "model_override":    ("text",     None,  False, None),
    "provider_override": ("text",     None,  False, None),
}

BOARD_KEYS = frozenset(OPTIONS)
PER_LANE = frozenset(k for k, o in OPTIONS.items() if o[2])
HEADER_KEYS = PER_LANE
PASS_THROUGH = {k: o[3] for k, o in OPTIONS.items() if o[3]}
# `timeout-min` is the DRIVER's cap, not a card's: start-board.sh passes it to
# run.py, so it has no `hermes kanban` flag even though the name is Hermes-shaped.
# Options the driver applies itself rather than passing through under that name.
DRIVER_OPTIONS = frozenset({"timeout-min"})

# The roles the card graph fills. `assignees` remaps role -> hermes profile for one
# board; a role it does not mention keeps the graph's own name. Declared here rather
# than imported from lanes.py, which imports this module — and a role that vanished
# from the graph should fail this module's own test, not silently accept a key
# nothing reads.
ROLES = frozenset({"researcher", "coder", "human-gate"})

# The worker cards a goal judge may run on. Declared here for the same reason as
# ROLES; `lanes.goal_args` still refuses gates and reviews whatever a list says.
GOAL_CODES = ("I", "P", "TW", "C", "TI")

# The gates a board may hand to the driver. Declared beside ROLES for the same reason:
# a code that left the graph should fail this module's own test.
GATE_CODES = ("Gi", "Gp", "Gc")


def gate_is_auto(value, code):
    """Does `auto-gates` hand gate `code` ('Gi') to the driver?

    A LIST only. The body was `code in (value or [])`, which on a string is substring
    containment: `gate_is_auto('xxGi', 'Gi')` was True (2026-09-23 review, Important 5).
    validate refuses a string `auto-gates`, so the shape is unreachable through the
    validated path — this function's own contract still must not answer yes to it.
    """
    return isinstance(value, (list, tuple)) and code in value

# Options whose VALUE the board's contract fixes, whatever their type allows. A
# failed card is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks it
# on that first failure and the driver halts the board. The only retry the board
# recognises is a REVIEW that failed, which asks for one by filing a revision
# card. `max-retries: 2` would re-enable the "run it again and hope" mechanism the
# rule removes, so it is refused where the board is declared rather than filed.
ONE_ATTEMPT = {
    "max-retries": ("a failed card is final — only a REVIEW sends work back, by "
                    "filing a revision card"),
}

# `<n><unit>` one or more times, as run-audit.py's ceiling parser reads it, so a
# manifest cannot state a ceiling the auditor scores as zero minutes.
# Whitespace between the parts is allowed because duration_seconds below reads it
# ('1h 30m' is 5400 there): the regex and the parser used to disagree about it.
_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*[hms]\s*)+$")


def duration_seconds(text):
    """`25m`, `90s`, `2h`, `1h30m` as seconds; None when nothing parses.

    ONE parser for the manifest's spelling, beside the regex that validates it. The
    other readers had their own copies and one of them was wrong: a second reader
    matched a SINGLE unit, so the multi-unit form accepted above (`1h30m`) came back
    None there, and a None budget means no `--run-budget` and no subprocess timeout —
    a card that runs unbounded while its manifest names a ceiling. `run-audit.py`
    carried a third copy, in minutes.
    """
    if not text:
        return None
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])",
                                  str(text).strip().lower()):
        total += float(value) * {"h": 3600.0, "m": 60.0, "s": 1.0}[unit]
    return int(round(total)) if total else None


def _kind_error(kind, value):
    """Why `value` is not a `kind`, or None when it is."""
    if kind == "bool":
        if not isinstance(value, bool):
            return f"expected true or false, got {value!r}"
    elif kind == "count":
        # bool is an int in Python; `"lanes": true` is not a lane count.
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return f"expected a positive integer, got {value!r}"
    elif kind in ("text", "slug", "abspath"):
        if not isinstance(value, str) or not value.strip():
            return f"expected a non-empty string, got {value!r}"
        if kind == "slug" and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
            return f"expected lowercase letters, digits and hyphens, got {value!r}"
        # A work directory is resolved from three different current directories
        # — create-board.sh's, the driver's, and each card's, which runs IN it —
        # so a relative path means a different tree depending on who asks, and
        # `~` means nothing at all to os.path.abspath (it becomes a literal `~`
        # directory inside the repo). Omit the option to get the board's own
        # work/; name it and it is absolute.
        if kind == "abspath" and not value.startswith("/"):
            return (f"must be an absolute path, got {value!r}"
                    + (" — `~` is not expanded; write the full path"
                       if value.startswith("~") else "")
                    + ". Omit the option for the board's own work/ directory.")
    elif kind == "paths":
        if not isinstance(value, list) or not all(
                isinstance(p, str) and p.strip() for p in value):
            return f"expected a list of non-empty paths, got {value!r}"
        # card_render.targets_text writes these into every card body, where the worker
        # runs in WORKDIR: a relative target is read from the wrong tree (2026-09-23
        # review, Important 4). `~` IS allowed here, unlike `abspath`: targets_text
        # expands it (tests/test_render_body.py pins that), so `~/x` names one place.
        bad = [p for p in value if not (p.startswith("/") or p == "~"
                                        or p.startswith("~/"))]
        if bad:
            return (f"expected absolute (or ~/) paths — {bad} would be read relative to "
                    f"each card's work directory")
        if len(set(value)) != len(value):
            return f"expected each target once — {value!r} names one twice"
    elif kind == "gates":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return (f"expected a list of gate codes {list(GATE_CODES)} — [] is every "
                    f"gate human, got {value!r}")
        unknown = sorted(set(value) - set(GATE_CODES))
        if unknown:
            return (f"unknown gate code(s) {unknown} — the lane's gates are "
                    f"{list(GATE_CODES)}")
        if len(set(value)) != len(value):
            return f"expected each gate code once — {value!r} names one twice"
    elif kind == "cards":
        if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
            return f"expected a list of card codes, got {value!r}"
        unknown = sorted(set(value) - set(GOAL_CODES))
        if unknown:
            return (f"unknown card code(s) {unknown} — the goal judge runs on "
                    f"worker cards only: {list(GOAL_CODES)}")
        if len(set(value)) != len(value):
            return f"expected each card code once — {value!r} names one twice"
    elif kind == "duration":
        if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
            return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
                    f"got {value!r}")
        if duration_seconds(value) is None:
            # '0s'/'0m' pass the regex and then mean NO budget: duration_seconds
            # collapses zero into None, so the card gets no --run-budget and no
            # subprocess timeout, and the auditor's ceiling is None — E6 silently
            # disabled (2026-09-23 review, Important 3).
            return (f"expected a positive duration — {value!r} means no budget at all, "
                    f"which disables the per-card ceiling")
    elif kind == "roles":
        if not isinstance(value, dict):
            return f"expected a mapping of role to profile, got {value!r}"
        unknown = sorted(set(value) - ROLES)
        if unknown:
            return (f"unknown role(s) {unknown} — the card graph fills "
                    f"{sorted(ROLES)}")
        bad = sorted(k for k, v in value.items()
                     if not isinstance(v, str) or not v.strip())
        if bad:
            return f"role(s) {bad} must name a profile as a non-empty string"
    else:                                       # pragma: no cover - typo guard
        raise KeyError(f"unknown option kind {kind!r}")
    return None


def validate(cfg, *, where="board.json", only=None, lists=True):
    """Every problem with one option mapping, as a list of strings — empty when
    valid.

    ALL of them, not the first. A manifest is edited by hand and a validator that
    stops at the earliest fault turns one mistake into one round trip each; the
    same reason `run-audit.py` reports a run's findings together.

    `only` narrows the acceptable options (idea headers may carry just the
    per-lane ones) and `lists` refuses the per-lane array form (an idea file IS
    one lane, so a list there has nothing to index). Those two arguments are the
    whole difference between judging a manifest and judging a set of headers —
    the types, the defaults and the values are the same question, asked of the
    same table.
    """
    problems = []
    if not isinstance(cfg, dict):
        return [f"{where}: expected a JSON object, got {type(cfg).__name__}"]
    allowed = BOARD_KEYS if only is None else frozenset(only)

    for key in sorted(set(cfg) - allowed):
        if key.startswith("$"):
            # A JSON META-KEY, not a board option: `$schema` is the editor's
            # reference to the generated schema and riding along in the manifest is
            # the point of it. Not in the option table on purpose — a board does not
            # "set" it, and the generated schema's `additionalProperties: false` is
            # what keeps a typo'd option loud in the editor.
            continue
        if key in BOARD_KEYS:
            problems.append(f"{where}: {key!r} is a board-level option — set it "
                            f"in board.json; only {sorted(allowed)} are per-lane")
            continue
        hint = _near(key)
        problems.append(f"{where}: unknown option {key!r}"
                        + (f" — did you mean {hint!r}?" if hint else ""))

    lanes = cfg.get("lanes", OPTIONS["lanes"][1])
    lanes_ok = _kind_error("count", lanes) is None

    for key, value in cfg.items():
        if key not in allowed:
            continue                            # already reported above
        kind, _default, per_lane, _flag = OPTIONS[key]
        if kind in ("gates", "cards"):       # a list of CODES is one value, not per-lane
            err = _kind_error(kind, value)
            if err:
                problems.append(f"{where}: {key!r} {err}")
            continue
        if isinstance(value, list) and kind not in ("paths", "roles", "cards") and not lists:
            problems.append(f"{where}: {key!r} takes a single value here — an "
                            f"idea file is one lane, so a list has nothing to "
                            f"index")
            continue
        if not isinstance(value, list) or kind in ("paths", "roles", "cards"):
            err = _kind_error(kind, value)
            if err:
                problems.append(f"{where}: {key!r} {err}")
            elif key in ONE_ATTEMPT and value != 1:
                problems.append(f"{where}: {key!r} must be 1 — {ONE_ATTEMPT[key]}")
            continue
        # A LIST is the per-lane form: one entry per lane, indexed from lane 1.
        if not per_lane:
            problems.append(
                f"{where}: {key!r} takes one value for the whole board, not a "
                f"list — only {sorted(PER_LANE)} are per-lane")
            continue
        if lanes_ok and len(value) != lanes:
            problems.append(
                f"{where}: {key!r} has {len(value)} entries for {lanes} lane(s) "
                f"— give one per lane, or a single value for all of them")
        for i, entry in enumerate(value, start=1):
            err = _kind_error(kind, entry)
            if err:
                problems.append(f"{where}: {key!r} lane {i}: {err}")

    # The engine's own rule (kanban_db._validate_model_override), refused where the
    # board is declared rather than at spawn: a provider names a backend, not a
    # model, so `provider_override` alone would ask the worker for a model nobody
    # named — and a spawn failure is final.
    # ...and the same rule for the work pair, in whichever scope it is declared:
    # a lane that names only a provider would pair it with the board's model, and a
    # model belongs to one provider — the flag pair is filed together or not at all.
    for provider_key, model_key in (("provider_override", "model_override"),
                                    ("provider", "model")):
        if provider_key not in allowed or not cfg.get(provider_key):
            continue
        prov, mod = cfg[provider_key], cfg.get(model_key)
        if not mod:
            problems.append(f"{where}: {provider_key!r} requires {model_key!r} "
                            f"— a provider alone does not say which model to run")
        elif isinstance(prov, list) and not isinstance(mod, list):
            # Per-lane providers beside ONE model would file that model on every lane's
            # provider, and a model belongs to one provider — a spawn failure is final
            # (2026-09-23 review, Important 1). The other direction, one provider
            # serving a different model per lane, is the normal local setup and stays
            # valid.
            problems.append(f"{where}: {provider_key!r} is per-lane but {model_key!r} is "
                            f"one value — {mod!r} would be asked of every lane's provider; "
                            f"give {model_key!r} one value per lane too")
    return problems


# Options that were called something else before the naming rule, so the error
# message can name the replacement instead of only refusing. A rename is not a
# typo and punctuation-blindness cannot find it.
RENAMED = {"title": "name", "workdir": "default-workdir", "goal_mode": "goal-cards",
           "goal-mode": "goal-cards", "goal": "goal-cards"}


def _near(key):
    """The known option a misspelling most likely meant, or None.

    Punctuation-blind first, because the common mistake is `max_runtime` for
    `max-runtime` — an underscore where Hermes writes a hyphen, which is the one
    typo a reader's eye slides over. Then the rename table, for the keys whose
    name changed rather than their punctuation.
    """
    flat = re.sub(r"[^a-z0-9]", "", key.lower())
    for known in sorted(BOARD_KEYS):
        if re.sub(r"[^a-z0-9]", "", known) == flat:
            return known
    return RENAMED.get(key.lower())


# A LOOSE header match: an HTML comment on its own line that contains a colon.
# Deliberately wider than lanes.py's `_HEADER_RE`, whose key class is
# [A-Za-z0-9-] — so `<!-- auto_gates: true -->` does not match it, is not an
# error, and becomes body PROSE. An underscore where the convention wants a
# hyphen is the likeliest typo and the only silent one, so anything SHAPED like a
# header is judged as one here and refused on its merits.
_LOOSE_HEADER_RE = re.compile(r"^\s*<!--\s*([^:\-][^:]*?)\s*:\s*(.*?)\s*-->(.*)$")

# What lanes.py accepts, so this module can say which of the two saw the line.
_STRICT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


def _as_json(text):
    """A header's text as the JSON value it spells, or the string it is.

    Headers are text and manifests are typed, so something has to bridge them —
    and the bridge is JSON, because that is what the manifest is written in.
    `true` becomes a bool and `2` an int, which is exactly what the same option
    would be in `board.json`; `yes` and `10m` are not JSON literals and stay
    strings, so `validate` rejects the first as not-a-bool and accepts the second
    as a duration. Nothing here decides what is valid: it converts, and the one
    validator judges.
    """
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return text.strip()


def headers_to_cfg(headers):
    """Idea headers as the option mapping a manifest would have carried."""
    return {k: _as_json(v) for k, v in headers.items()}


def validate_idea(text, *, where="lane-<k>.md"):
    """Every problem with one idea file — its headers AND its prose.

    What the DOORS check, because a lane filed from an empty idea or one with no
    success criterion fails later and more expensively. `validate_headers` is the
    narrower question, for callers that only need to read the options.
    """
    return validate_headers(text, where=where) + _body_problems(text, where)


def validate_headers(text, *, where="lane-<k>.md"):
    """Every problem with one idea file's headers — empty when it has none or all
    of them are good.

    Two jobs, and only the first is specific to idea files. LEXING: a line shaped
    like a header is judged as one, which `lanes._HEADER_RE` does not do — its key
    class is [A-Za-z0-9-], so `<!-- auto_gates: true -->` fails to match, is not an
    error, and becomes body PROSE. An underscore where the convention wants a
    hyphen is the likeliest typo and the only silent one. VALIDATION: the headers
    are converted to the mapping a manifest would carry and handed to `validate`,
    restricted to the per-lane options and refusing the array form.
    """
    problems, headers, lines = [], {}, {}
    for n, line in enumerate(text.splitlines(), start=1):
        m = _LOOSE_HEADER_RE.match(line)
        if not m:
            continue
        key, value, trailing = m.group(1), m.group(2), m.group(3)
        at = f"{where}:{n}"
        if trailing.strip():
            problems.append(f"{at}: a header is a whole line — drop "
                            f"{trailing.strip()!r} after the comment, or the line "
                            f"is silently kept as prose")
        if not _STRICT_KEY_RE.match(key):
            hint = _near(key)
            problems.append(
                f"{at}: {key!r} is not a header — a key is letters, digits and "
                f"hyphens" + (f", so write {hint!r}" if hint else "")
                + "; as written the line is kept as prose and the option is "
                  "silently ignored")
            continue
        if key in headers:
            # last-wins silently, in the one file a person reads to learn the lane's
            # options — the first line then lies (prior review T-3). `lines` keeps the
            # FIRST occurrence, which is the line to look at: overwriting it per
            # occurrence made a THIRD repeat report the second's line as the first, and
            # the line prefix below names that same line (final review, item 4b).
            problems.append(f"{at}: {key!r} is given twice (first on line {lines[key]}) "
                            f"— the second would silently win; keep one")
        headers[key] = value
        lines.setdefault(key, n)

    for p in validate(headers_to_cfg(headers), where=where,
                      only=PER_LANE, lists=False):
        key = next((k for k in lines if repr(k) in p), None)
        problems.append(p.replace(f"{where}:", f"{where}:{lines[key]}:", 1)
                        if key else p)
    return problems


# What an idea has to say beyond its headers. Not a style rule: a lane whose idea
# omits these costs a full card cycle to discover, at the moment the researcher has
# nothing to refine or the code gate has no criterion to judge against.
DONE_MEANS_RE = re.compile(r"^#{1,6}\s*Done means\b", re.I | re.M)


def _body_problems(text, where):
    """The idea's prose, judged as lightly as it can be and still catch an empty
    lane file or a missing success criterion."""
    body = "\n".join(ln for ln in text.splitlines()
                      if not _LOOSE_HEADER_RE.match(ln)).strip()
    if not body:
        return [f"{where}: no idea here — a lane whose idea is empty stops the "
                f"chain, and the board cannot tell that from one still being typed"]
    out = []
    if not DONE_MEANS_RE.search(body):
        out.append(f"{where}: no '### Done means' section — the code gate judges the "
                   f"lane against it, and a reviewer with no criterion falls back to "
                   f"its own taste")
    else:
        tail = DONE_MEANS_RE.split(body)[-1].strip()
        if not tail:
            out.append(f"{where}: '### Done means' is empty")
    return out


def workdir_notices(cfg, *, where="board.json"):
    """What the tree the board works in already holds — REPORTED, never a refusal.

    The board makes no promise about the contents of its work directory: it may
    change anything inside it, staged and unstaged files included, and it discovers
    greenfield (empty) from brownfield (anything there) by reading it — see
    `workdir_state`. So a work directory with pending changes is not a fault to
    stop for; it is a fact worth printing where a person will see it, because
    `git diff --cached` lists the WHOLE index and the operator's pending entries
    then reach the reviewers' evidence. The driver reports the same thing as drift
    while a run is live (E17), which is where failing belongs — at the audit.
    """
    wd = cfg.get("default-workdir")
    if not wd or not os.path.isdir(wd):
        return []
    inside = subprocess.run(["git", "-C", wd, "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if inside.returncode != 0:
        return []                     # not a repo: nothing stages, nothing to say
    staged = subprocess.run(["git", "-C", wd, "diff", "--cached", "--name-only"],
                            capture_output=True, text=True)
    if staged.returncode != 0:
        # A failing index read is NOT a clean index: this notice exists to tell the
        # operator their pending entries are about to reach every reviewer's `git diff
        # --cached`, and "nothing staged" says the opposite (2026-09-23 review, I17).
        return [f"{where}: cannot read the index of {inside.stdout.strip()} (git diff "
                f"--cached exited {staged.returncode}: "
                f"{(staged.stderr.strip() or 'no message')[:120]}) — what is staged "
                f"there is unknown, not clean"]
    pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
    if not pending:
        return []
    return [f"{where}: the index of {inside.stdout.strip()} is not clean "
            f"({len(pending)} path(s) staged, e.g. {pending[0]}) — the board works "
            f"around it: it promises nothing about these files, and `git diff "
            f"--cached` lists the whole index, so scope every check with a pathspec"]


def review_model_notices(cfg, *, where="board.json"):
    """The reviews are no longer an independent model — REPORTED, never a refusal.

    Every shipped board pins `model_override` for one reason: the verdict must come
    from a model other than the author's. Naming a board `model` without that pin
    puts the reviews back on the author's model, which is a legitimate thing to want
    (one local model for everything, an experiment that does not care) and a
    catastrophic thing to do by omission. So it is a note at the door and a line in
    the driver's log, not an error.

    The driver reports the per-lane form when a lane opens, because only it knows
    the lane's resolved options then.
    """
    if cfg.get("model_override") or not cfg.get("model"):
        return []
    return [f"{where}: 'model' {cfg['model']!r} applies to every card and no "
            f"'model_override' is pinned — the review cards run the author's model, "
            f"so a verdict no longer comes from a different one"]


def workdir_problems(cfg, *, where="board.json", any_host=False):
    """Faults in an explicit `default-workdir` that only the filesystem can answer.

    `any_host=True` drops the existence half and keeps every other check: a CI runner is
    not the board's host, so an absolute path that names the owner's tree cannot be there
    by design, while the declaration itself is still worth validating. The default stays
    strict for the door scripts, which do run on the board's host.

    Kept out of `validate` because it touches disk: the pure checks have to run on
    any machine (a test, a review of someone else's board), while these are about
    THIS host. A board that omits the option builds in its own work/ and has none of
    these questions — the directory is the board's to create.

    EXISTENCE is the only fault here, and it is about the board's definition rather
    than the tree's contents: an absolute path that is not there points at nothing,
    and a lane would quietly build greenfield somewhere unintended. What the
    directory HOLDS is never a fault — it may be empty (greenfield), a previous
    run's product, or years of someone else's project.
    """
    wd = cfg.get("default-workdir")
    if not wd or any_host:
        return []
    if not os.path.isdir(wd):
        return [f"{where}: 'default-workdir' {wd} does not exist on this host — an "
                f"absolute path is host-local, so a board that names one does not "
                f"run as shipped; point it at a tree on this machine"]
    return []


def validate_or_die(path, *, any_host=False):
    """Print every problem with the file at `path` and exit non-zero, or return
    it. The pre-flight form, for the scripts. A `.md` path is an idea file and is
    judged on its headers; anything else is a manifest. `any_host` drops only the
    workdir-existence check (see `workdir_problems`)."""
    if path.endswith(".md"):
        try:
            with open(path) as f:
                text = f.read()
        except OSError as e:
            sys.exit(f"{path}: {e.strerror}")
        problems = validate_idea(text, where=path)
        if problems:
            sys.exit("\n".join(["idea headers rejected:"]
                               + [f"  - {p}" for p in problems]))
        return text
    try:
        with open(path) as f:
            cfg = json.load(f)
    except OSError as e:
        sys.exit(f"{path}: {e.strerror}")
    except json.JSONDecodeError as e:
        sys.exit(f"{path}: not valid JSON — {e.msg} at line {e.lineno}")
    problems = validate(cfg, where=path) + workdir_problems(cfg, where=path, any_host=any_host)
    # Notices never fail a door: the work directory's CONTENTS are not a fault.
    for notice in workdir_notices(cfg, where=path) + review_model_notices(cfg, where=path):
        print(f"note: {notice}")
    if problems:
        sys.exit("\n".join(["board manifest rejected:"]
                           + [f"  - {p}" for p in problems]))
    return cfg


def schema_text():
    """The option table, for `--help` and for a board author who wants the set."""
    width = max(len(k) for k in OPTIONS)
    rows = ["option".ljust(width) + "  type      lane?  default    hermes flag"]
    for key in sorted(OPTIONS):
        kind, default, per_lane, flag = OPTIONS[key]
        rows.append(f"{key.ljust(width)}  {kind:<9} {'yes' if per_lane else '-':<6} "
                    f"{'' if default is None else json.dumps(default):<10} {flag or ''}".rstrip())
    rows.append("")
    rows.append("A per-lane option ('lane? yes') takes one value for the board or a "
                "list with one")
    rows.append("entry per lane, and an idea file may override it with "
                "`<!-- option: value -->`.")
    return "\n".join(rows)


# The generated editor schema. DERIVED from the table above — never hand-written,
# or it becomes a second declaration of the option set and drifts from the first
# (the failure the header/manifest split already taught). `--check-schema` fails
# when the file on disk disagrees with this module, and the suite runs that.
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "board.schema.json")

# kind -> the JSON Schema a manifest value of that kind satisfies. `lanes`-length is
# the one rule JSON Schema cannot state (an array of exactly N entries needs a
# cross-field check), so the Python validator keeps that half; the schema carries it
# as a comment for whoever reads the file in an editor.
_KIND_SCHEMA = {
    "slug":     {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
    # `\\S`: validate strips before its non-empty check, so '   ' is refused there —
    # `minLength: 1` alone accepted it here (2026-09-23 review, Important 2).
    "text":     {"type": "string", "minLength": 1, "pattern": "\\S"},
    "count":    {"type": "integer", "minimum": 1},
    "bool":     {"type": "boolean"},
    # _DURATION_RE's language, with the surrounding whitespace validate strips. The
    # zero case ('0m') is not expressible here without refusing values validate
    # accepts; validate stays the authority for it, and json_schema()'s docstring below
    # lists it among the rules this file cannot state.
    "duration": {"type": "string",
                 "pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$"},
    "abspath":  {"type": "string", "pattern": "^/"},
    "paths":    {"type": "array", "uniqueItems": True,
                 "items": {"type": "string", "pattern": "^(/|~$|~/)"}},
    "cards":    {"type": "array", "uniqueItems": True,
                 "items": {"enum": list(GOAL_CODES)}},
    "gates":    {"type": "array", "uniqueItems": True,
                 "items": {"enum": list(GATE_CODES)}},
    "roles":    {"type": "object",
                 "propertyNames": {"enum": sorted(ROLES)},
                 "additionalProperties": {"type": "string", "minLength": 1}},
}


def json_schema():
    """The manifest's JSON Schema, for editors (IntelliJ, VS Code) to validate and
    complete a `board.json` as it is written.

    It is a CONVENIENCE, not the authority: `validate` above is what a board is
    actually judged by, and it decides five things this cannot — a per-lane array's
    length against `lanes`, an `abspath` that exists on this host, a `duration` of zero
    ('0m' satisfies the pattern here and means no budget at all), the cross-key rule
    that `provider_override` needs `model_override`, and the same rule for a per-lane
    `provider` declared beside one `model`.
    """
    props = {"$schema": {"type": "string",
                         "description": "Path to this generated schema."}}
    for key, (kind, default, per_lane, _flag) in OPTIONS.items():
        spec = dict(_KIND_SCHEMA[kind])
        if key in ONE_ATTEMPT:
            spec = {"const": 1, "description": ONE_ATTEMPT[key]}
        if per_lane:
            # one value for the whole board, or one per lane — EXACTLY `lanes` of
            # them, which JSON Schema cannot say; validate() checks the length
            spec = {"oneOf": [spec, {"type": "array", "items": spec, "minItems": 1,
                                     "description": "one entry per lane, in lane "
                                                    "order — exactly `lanes` entries"}]}
        if default is not None:
            spec["default"] = default          # on the option, not inside its items
        props[key] = spec
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "kanban board.json",
        "$comment": ("Generated by template/board_schema.py --write-schema; that "
                     "module is the authority. A manifest this schema ACCEPTS can still "
                     "be refused there: a per-lane array must have exactly `lanes` "
                     "entries, an `abspath` must exist on the host, a `duration` of "
                     "zero means no budget at all, and a `provider` (or "
                     "`provider_override`) needs a model beside it — one value per lane "
                     "when the provider is per-lane. Checks JSON Schema cannot "
                     "express."),
        "type": "object",
        "additionalProperties": False,
        # validate treats any `$`-prefixed key as a meta-key ($schema, $comment, $id);
        # without this, `{"$comment": "..."}` passed validate and failed the schema.
        "patternProperties": {"^\\$": {}},
        "properties": props,
        # no "required": `lanes` defaults to 1 in the option table, and validate
        # accepts a manifest that omits it (review Important 2)
    }


def write_schema(path=None):
    path = path or SCHEMA_PATH
    with open(path, "w") as f:
        json.dump(json_schema(), f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def schema_is_current(path=None):
    path = path or SCHEMA_PATH
    try:
        with open(path) as f:
            return json.load(f) == json_schema()
    except (OSError, ValueError):
        return False


USAGE = """template/board_schema.py — validate a board's files against the schema

  board_schema.py <board.json|lane-<k>.md>...   validate each; non-zero on any fault
  board_schema.py --any-host <board.json>...    validate the declaration only — skip the
                                            workdir-existence check (a CI runner is not
                                            the board's host, so an owner's absolute
                                            path cannot be there by design)
  board_schema.py --schema                      print the option table
  board_schema.py --jsonschema                  print the manifest's JSON Schema
  board_schema.py --write-schema [path]         (re)generate it, for editors
  board_schema.py --check-schema [path]         fail if the file is stale
  board_schema.py --help                        this text

A `.md` path is judged as an idea file: its headers against the per-lane options, and
its prose for an idea and a `### Done means`. Anything else is judged as a manifest.
Every problem is printed, not just the first. create-board.sh and start-board.sh run
this before a board is created or a driver reads it, and the driver runs it again on
the idea a human arms from the dashboard."""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0 if args else 2)
    if args[0] == "--schema":
        print(schema_text())
    elif args[0] in ("--jsonschema", "--write-schema", "--check-schema"):
        target = args[1] if len(args) > 1 else None
        if args[0] == "--jsonschema":
            print(json.dumps(json_schema(), indent=2, sort_keys=True))
        elif args[0] == "--write-schema":
            try:
                print(f"wrote {write_schema(target)}")
            except OSError as e:
                # every other branch answers with a line; this one was a traceback
                # (2026-09-23 review, errors S16)
                sys.exit(f"cannot write {target or SCHEMA_PATH}: {e.strerror or e}")
        elif schema_is_current(target):
            print(f"{target or SCHEMA_PATH} is current")
        else:
            sys.exit(f"{target or SCHEMA_PATH} is stale — regenerate it with "
                     f"`template/board_schema.py --write-schema`")
    elif args[0] == "--any-host":
        if len(args) < 2:
            sys.exit("--any-host needs at least one <board.json|lane-<k>.md>")
        for path in args[1:]:
            validate_or_die(path, any_host=True)
    else:
        for path in args:
            validate_or_die(path)
