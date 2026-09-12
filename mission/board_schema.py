"""The schema for `boards/<slug>/board.json` — one declaration, validated.

WHY A SCHEMA AND NOT A KEY LIST. `file_lanes.BOARD_KEYS` checks that every key
is spelled right and nothing else, so a manifest can name only known options and
still describe a board that cannot exist:

    "integration-tests": ["yes", "no"]   right length, both entries pass, resolve
                                         to the STRING "yes" — truthy — so BOTH
                                         lanes get integration cards
    "goal": "false"                      bool("false") is True: the judge runs on
                                         a board whose manifest says it must not,
                                         which is the wedge-every-card failure
    "max-runtime": "banana"              handed to --max-runtime; the auditor's
                                         <n><unit> parser reads it as 0 minutes

All three are typos in the board's shape that no key check can see, and the first
is precisely the silently-wrong lane shape the per-lane array's length check
exists to prevent. So the unit of declaration here is the OPTION, not the key:
its type, its default, whether a lane may override it, and the `hermes kanban`
flag it becomes.

NAMING. Every option that reaches Hermes keeps Hermes's spelling of its name —
`max-runtime` because the flag is `--max-runtime`, `name` because it is `--name`,
`goal` because it is `--goal`, `default-workdir` because it is
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
    "unit-tests":        ("bool",     True,  True,  None),
    "integration-tests": ("bool",     True,  True,  None),
    "auto-gates":        ("bool",     False, True,  None),
    "goal":              ("bool",     True,  False, "--goal"),
    "max-runtime":       ("duration", "60m", False, "--max-runtime"),
    "max-retries":       ("count",    1,     False, "--max-retries"),
    "goal-max-turns":    ("count",    40,    False, "--goal-max-turns"),
    "rework-max-retries": ("count",   1,     False, None),
    "timeout-min":       ("count",    240,   False, None),
    "assignees":         ("roles",    {},    False, None),
}

BOARD_KEYS = frozenset(OPTIONS)
PER_LANE = frozenset(k for k, o in OPTIONS.items() if o[2])
HEADER_KEYS = PER_LANE
PASS_THROUGH = {k: o[3] for k, o in OPTIONS.items() if o[3]}
# `timeout-min` is the DRIVER's cap, not a card's: start-board.sh passes it to
# run.py, so it has no `hermes kanban` flag even though the name is Hermes-shaped.
# Options the driver applies itself rather than passing through under that name.
# `rework-max-retries` becomes `--max-retries` on a REVISION card only, so it
# cannot be a pass-through: the same flag already carries `max-retries` for the
# board's first filing.
DRIVER_OPTIONS = frozenset({"timeout-min", "rework-max-retries"})

# The roles the card graph fills. `assignees` remaps role -> hermes profile for one
# board; a role it does not mention keeps the graph's own name. Declared here rather
# than imported from lanes.py, which imports this module — and a role that vanished
# from the graph should fail this module's own test, not silently accept a key
# nothing reads.
ROLES = frozenset({"researcher", "manager", "coder", "tester", "reviewer",
                   "human-gate"})

# Options whose VALUE the board's contract fixes, whatever their type allows. A
# failed card is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks it
# on that first failure and the driver halts the board. The only retry the board
# recognises is a REVIEW that failed, which asks for one by filing a revision
# card. `max-retries: 2` would re-enable the "run it again and hope" mechanism the
# rule removes, so it is refused where the board is declared rather than filed.
ONE_ATTEMPT = {
    "max-retries": ("a failed card is final — only a REVIEW sends work back, by "
                    "filing a revision card"),
    "rework-max-retries": ("a failed revision card is final — the round budget "
                           "(2 idea / 3 plan / 2 code rounds) is what retries work, "
                           "not the dispatcher"),
}

# `<n><unit>` one or more times, as run-audit.py's ceiling parser reads it, so a
# manifest cannot state a ceiling the auditor scores as zero minutes.
_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?[hms])+$")


def _kind_error(kind, value):
    """Why `value` is not a `kind`, or None when it is."""
    if kind == "bool":
        if not isinstance(value, bool):
            return f"expected true or false, got {value!r}"
    elif kind == "count":
        # bool is an int in Python; `"lanes": true` is not a lane count.
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return f"expected a positive integer, got {value!r}"
    elif kind in ("text", "slug", "path", "abspath"):
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
    elif kind == "duration":
        if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
            return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
                    f"got {value!r}")
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
    elif kind == "unchecked":
        return None
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
        if isinstance(value, list) and kind not in ("paths", "roles") and not lists:
            problems.append(f"{where}: {key!r} takes a single value here — an "
                            f"idea file is one lane, so a list has nothing to "
                            f"index")
            continue
        if not isinstance(value, list) or kind in ("paths", "roles"):
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
    return problems


# Options that were called something else before the naming rule, so the error
# message can name the replacement instead of only refusing. A rename is not a
# typo and punctuation-blindness cannot find it.
RENAMED = {"title": "name", "workdir": "default-workdir", "goal_mode": "goal",
           "goal-mode": "goal"}


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
        headers[key] = value
        lines[key] = n

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
    pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
    if not pending:
        return []
    return [f"{where}: the index of {inside.stdout.strip()} is not clean "
            f"({len(pending)} path(s) staged, e.g. {pending[0]}) — the board works "
            f"around it: it promises nothing about these files, and `git diff "
            f"--cached` lists the whole index, so scope every check with a pathspec"]


def workdir_problems(cfg, *, where="board.json"):
    """Faults in an explicit `default-workdir` that only the filesystem can answer.

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
    if not wd:
        return []
    if not os.path.isdir(wd):
        return [f"{where}: 'default-workdir' {wd} does not exist on this host — an "
                f"absolute path is host-local, so a board that names one does not "
                f"run as shipped; point it at a tree on this machine"]
    return []


def validate_or_die(path):
    """Print every problem with the file at `path` and exit non-zero, or return
    it. The pre-flight form, for the scripts. A `.md` path is an idea file and is
    judged on its headers; anything else is a manifest."""
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
    problems = validate(cfg, where=path) + workdir_problems(cfg, where=path)
    # Notices never fail a door: the work directory's CONTENTS are not a fault.
    for notice in workdir_notices(cfg, where=path):
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


USAGE = """mission/board_schema.py — validate a board's files against the schema

  board_schema.py <board.json|lane-<k>.md>...   validate each; non-zero on any fault
  board_schema.py --schema                      print the option table
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
    else:
        for path in args:
            validate_or_die(path)
