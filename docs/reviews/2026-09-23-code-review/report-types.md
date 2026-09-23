# Type & shape design review — kanban (whole-file manifest, no diff)

Aspect: **type design** (type-design-analyzer standard: encapsulation, invariant expression,
invariant usefulness, invariant enforcement). Repo `/opt/projects/kanban/main/kanban`, branch
`main`, HEAD `59bc279838b6a38fcd9e258a830702c1f84a94bc` ("Generic kanban plan").

Scope: every path in `docs/reviews/2026-09-23-code-review/scope/manifest.txt` (**76 files**),
whole files, no diff. Read-only: nothing in the repo was modified, no driver run, no board or
lane created.

**First, a correction to this aspect's premise.** The brief says "12 manifest modules carry `-> `
annotations; `driver/run.py` imports `typing`". Neither is true at HEAD `59bc279`. Verified:

```
$ grep -rn "^import typing\|^from typing" --include='*.py' driver template tests | wc -l
0
$ for f in $(grep '\.py$' scope/manifest.txt); do grep -c '\-> ' "$f"; done   # all matches
```

Every one of the 34 `->` occurrences in the manifest is inside a comment, a docstring or a
string literal (`run.py:95` `# gate code -> the review card …`, `lanes.py:359` `` `P1` … -> `P` ``,
`render-flow.py:124` `f"    {parent} --> {c['id']}"`). **No module in the manifest imports
`typing` and not one function in the 43 manifest `.py` files carries an annotation.** `driver/run.py`
is 3814 lines with ~40 module-level functions and zero type hints.

So "types" here means exactly what the brief's second half says: the **data-shape contracts** —
`template/board.schema.json` + `template/board_schema.py` (the board/card/run JSON contract every
other module validates against), the six shipped `boards/*/board.json` instances, and the dicts the
modules pass each other. The repo is uniformly a *dict-and-string-key* codebase whose contracts are
expressed in prose plus runtime checks, with no static layer at all.

**No Critical finding.** The strongest findings are Important: one shape documented, two shapes
passed; one contract declared twice, enforced differently by each copy.

---

## Coverage

* **Manifest files read in full (10):** `template/board_schema.py` (724 l.), `template/board.schema.json`
  (217 l.), `template/lanes.py` (489 l.), `template/card_render.py` (164 l.), and all six
  `boards/*/board.json`.
* **Opened and read in part (8):** `driver/run.py` (regions: 40–114, 140–230, 300–360, 374–402,
  611–630, 1185–1330, 1355–1370, 1430–1520, 2340–2400, 2415–2445, 2568–2590, 3335–3360, plus
  targeted greps over all 3814 lines), `driver/file_lanes.py` (120–284), `driver/run-audit.py`
  (58–75, 407–412, 570–577), `driver/runs_util.py` (145–155), `tests/test_board_schema.py` (40–120,
  490–539), `tests/test_shipped_boards.py` (1–60), `driver/render-flow.py`, `driver/timing-report.py`.
* **Inspected by targeted search (5):** `template/driver_lock.py`, `driver/doc-chain.py`,
  `driver/runs-report.py`, `driver/arm.sh`, `driver/create-board.sh` (the shape-bearing lines cited
  below).
* **Remaining 53 manifest files** (15 `template/card-bodies/*.txt`, 29 `tests/*.py`, the other shell
  scripts, `ci.yml`, `.gitignore`, `.opencodereview/rule.json`, the prior review's `manifest.json`)
  were not re-read here: they were read in full by the four sibling reports of this run
  (`report-code.md`, `report-tests.md`, `report-comments.md`, `report-errors.md`), which are the
  source for every cross-aspect claim below. **Manifest files directly examined by this aspect:
  23 / 76; the shape-defining subset (all of `template/`, all six boards, the four readers of the
  manifest) is complete.**
* **Static checks run (read-only):** `python3 -m py_compile` on every manifest `.py` (0 failures,
  bytecode to the scratch dir); `python3 template/board_schema.py --check-schema` → "is current",
  exit 0. Probes were run in
  `/home/wos/.hermes/profiles/coder/cache/scratch/typeprobe/{probe.py,probe2.py}` — never in the
  repo. Evidence blocks below are actual output.
* **Repo state:** `git status --porcelain` before and after is exactly
  `AM .opencodereview/rule.json` + `?? docs/reviews/2026-09-23-code-review/` — the expected
  pre-review state. (Bytecode caches under `__pycache__/` — `.gitignore:15`, untracked — were
  created by importing the modules and were removed afterwards; no tracked file changed.)

---

## Type: the board manifest contract (`board_schema.OPTIONS` → `validate` → `json_schema()`)

### Invariants identified
1. One declaration drives everything: `OPTIONS` (key → kind, default, per-lane, flag) is the source
   for `validate`, `schema_text`, `PER_LANE`/`HEADER_KEYS`/`PASS_THROUGH`, `ROLES`, `GOAL_CODES`,
   `GATE_CODES`, and the generated `board.schema.json`.
2. Kinds are closed (bool / count / text / slug / abspath / paths / gates / cards / duration / roles).
3. A per-lane option is a scalar for the whole board or a list of **exactly** `lanes` entries,
   indexed from lane 1.
4. Keys are closed; `$`-prefixed keys are meta.
5. `max-retries` is exactly 1 (`ONE_ATTEMPT`); a failed card is final.
6. `provider` and its `model` travel together, in the same scope.
7. The generated schema is **derived**, and `--check-schema` guards it.

### Ratings
* **Encapsulation: 8/10** — invariant 1 is real and enforced: `PER_LANE`/`HEADER_KEYS`/`PASS_THROUGH`
  are comprehensions over `OPTIONS` (`board_schema.py:114-117`), so the header set cannot drift from
  the option set, and `tests/test_board_schema.py:74-81` pins that. The weak point is invariant 6,
  which is not a property of any declaration — it is re-implemented by *which dict a caller passes*
  (finding **I1**).
* **Invariant Expression: 6/10** — the option table is beautifully self-documenting, but the
  authority and the file it generates disagree on four rules (invariants 3, 4 and two value rules —
  finding **I5**), so the file an editor reads is not the file that judges. Invariant 2 is expressed
  twice, in `_kind_error` and `_KIND_SCHEMA`, and the two lists differ (`path`, `unchecked`).
* **Invariant Usefulness: 9/10** — these are the invariants that actually bite: a wrong lane shape
  arms the wrong cards, a wrong duration becomes a zero-minute ceiling, a lone provider is a
  spawn-time failure that is final.
* **Invariant Enforcement: 6/10** — `validate` returns *every* problem, rejects bool-as-int and
  `~`-paths, and closes the gate/card vocabularies. But the per-lane length check is silently skipped
  when `lanes` itself is bad (`board_schema.py:310`), `targets` escapes the abspath rule (**I8**),
  a zero duration passes (**I9**), and no consumer except the door and `validate_armed` ever calls it
  (**I7**).

### Strengths
The `bool is not an int` guard (`:185`); the `~`-is-not-expanded message (`:200-201`); the rename
table feeding `_near` (`:337-353`); `ONE_ATTEMPT` refusing a knob whose only legal value is 1
(`:149-152`); `_kind_error`'s closed-vocabulary messages naming the codes it will accept.

### Concerns
Findings I4, I5, I8, I9, S8, S9 below.

---

## Type: the resolved lane-options dict (`lanes.resolve_lane_options` → `run.lane_options`)

### Invariants identified
1. `resolve_lane_options` returns **exactly** the six `PER_LANE` keys — one shape, no more, no less
   (verified: `sorted(opts) == sorted(board_schema.PER_LANE)`).
2. Precedence is schema default → board default (scalar or per-lane list) → idea header.
3. A per-lane board default whose length ≠ `lanes` is an error, not a shrug (`lanes.py:454-459`).
4. `run.lane_options` adds one out-of-band key, `"idea"` (the idea's prose), and returns `None` when
   the idea file is missing **or blank**.

### Ratings
* **Encapsulation: 5/10** — invariant 1 is true of the resolver and false of what the driver actually
  passes around: `run.lane_options` returns a union of "the option table" and "plus the idea prose"
  (`run.py:308`), the function has **no docstring at all** (`run.py:302-309`), and consumers disagree
  about whether the shape is guaranteed — some index (`opts["integration-tests"]`, `opts["idea"]`),
  others carry their own fallback (`(lane_options(lane) or {}).get("refinement", True)`). Finding
  **I2**.
* **Invariant Expression: 6/10** — the precedence is documented once and implemented generically
  (`lanes.py:463-478` names no individual option), which is the right shape. But the `None` of
  invariant 4 is overloaded: `read_idea` returns `None` for "not entered yet" and for "exists but
  blank" (`lanes.py:481-489`), and the two mean different things to the driver (finding **I6**).
* **Invariant Usefulness: 8/10** — it resolves the exact bug the module was written for (a lane
  silently getting the wrong lane's shape).
* **Invariant Enforcement: 4/10** — a duplicate header key is silently overwritten (`lanes.py:402`,
  prior T-3), error line numbers are recovered by string search (prior T-2), the resolved options are
  re-derived from disk on every call so one tick can hold two answers (prior T-19a), and the one
  consumer that pairs a lane model with a provider is fed a different dict shape than the one the
  docstring documents (**I1**).

---

## Type: the run/ledger record shapes (`RunState`, `chain.jsonl`, `verdicts.jsonl`, `run-summary.json`)

### Invariants identified
1. One run = one directory = one `current` pointer; the run id is `run-<YYYYmmdd-HHMMSS>`.
2. Every record reader rejoins from disk and is idempotent; a JSONL reader skips a malformed line.
3. A failed read is recorded (`STATE.read_error`) and never passes for "a card with no events".
4. Every external call is bounded (`CLI_TIMEOUT_S`).

### Ratings
* **Encapsulation: 4/10** — `RunState` is one home for the holders, but `reset()` clears 7 of ~29
  (prior T-19b, still unfixed: `opened`, `timed`, `drift`, `run_finished`, `announced`, `reported`,
  `timing_prev`), the class declares no field types, and import-time side effects (`ONCE`, `SERVE`,
  `BOARD`, `use_run(_read_current_run())` at `run.py:203`) make the module's shape a property of the
  importing process (prior T-20, still unfixed).
* **Invariant Expression: 5/10** — record shapes are dict literals built ad hoc in ~10 places with
  the round-trip key set visible only by reading both writers and readers. `run-summary.json` is the
  one place the shape is written down (`run.py:3335-3355`) and it is also the one file the auditor
  reads unguarded.
* **Invariant Usefulness: 8/10** — the guards are load-bearing (idempotency keys, log offsets,
  rejoin, the parking brake).
* **Invariant Enforcement: 5/10** — the `hermes --json` boundary is consumed untyped at two sites
  (`run.py:376-379`, `:391-401`, prior T-7); one reader crashes on a malformed record where its
  siblings skip (`runs_util.py:151`, prior T-13); the run-id shape is enforced nowhere at the
  consumer (finding **S3**).

---

## Type: the closed code vocabularies (gate codes, worker/goal codes, roles)

### Invariants identified
1. The gate vocabulary is `{Gi, Gp, Gc}`; the goal-judge vocabulary is `{I, P, TW, C, TI}`; roles are
   `{researcher, coder, human-gate}`.
2. These are *closed*: an unknown code is refused where a board is declared, not at spawn.

### Ratings
* **Encapsulation: 4/10** — `board_schema.GATE_CODES` is declared there "so a code that left the
  graph should fail this module's own test" (`:134-136`), but `run.py` declares the same vocabulary
  three more times: `GATE_NAMES` (`:1056`), `GATE_CODE_OF` (`:1057`), and the literal
  `if kind not in ("gi", "gp", "gc")` (`:2337`). `board_schema.GOAL_CODES` (`:132`) and
  `lanes.WORKER_CODES` (`:365`) are byte-identical tuples in two modules. No test pins any pair
  equal. Finding **S4**.
* **Invariant Expression: 5/10** — `lanes.LANE_CARDS` is the real declaration; the four copies are
  restatements of it.
* **Invariant Usefulness: 7/10** — a closed vocabulary is the right call; the enforcement is what is
  missing.
* **Invariant Enforcement: 5/10** — `GATE_CODE_OF[kind]` (`run.py:1241`, `:1248`) is a bare dict
  index reached from `gate_action`, so a gate added to the graph raises `KeyError` mid-tick rather
  than failing at the declaration. `gate_is_auto` does not guard its argument type (**S2**).

---

# Findings

Severity: Critical > Important > Suggestion. Every line cites `file_path:line_number`.
*(prior)* marks a finding carried from `docs/reviews/2026-09-20-code-review/report-types.md`.

## Critical

**None.** The prior run reached the same conclusion, and re-checking every prior Critical-class
subject confirms it: the schema-invalid default manifest is a code/comment defect already carried as
C1 in `report-code.md`, and no *type* defect in this manifest loses data or wedges a board on its own.

## Important

**I1 (NEW) `template/lanes.py:278-303` (with `driver/run.py:1508`, `:721`, `:741`, `:2422`, `:2441`,
`:2738`) — `lanes.model_args`'s third parameter is passed two different shapes, and the two shapes
produce two different provider answers for the same lane.**

`model_args(code, cfg, lane_cfg)`'s docstring defines `lane_cfg` as the *resolved* lane options:
"`model`/`provider`, per lane, resolved by `resolve_lane_options` into `lane_cfg` (idea header over
board default)" (`lanes.py:287-291`). One call site does that:

```python
1508:  want = lanes.model_args(c["code"], board_cfg, opts)      # opts = lane_options(lane), RESOLVED
```

Every other call site passes the header-only dict instead — `lane_model_opts(lane)` (`run.py:312-327`),
whose own docstring says the opposite of `model_args`':

> "Deliberately NOT the resolved options: `resolve_lane_options` fills a missing provider from the
> board, so a lane naming a local model on a board whose provider is a cloud one would ask that cloud
> backend for a model it does not serve."

```
 721:  + lanes.model_args(base, manifest(), lane_model_opts(lane))
 741:  lanes.model_args(rr_code, manifest(), lane_model_opts(lane))
2422:  + lanes.model_args(owner, manifest(), lane_model_opts(lane))
2441:  lanes.model_args("RVa", manifest(), lane_model_opts(lane))
2738:  args = lanes.model_args(code, manifest(), lane_model_opts(lane))
```

The consequence is concrete. `resolve_lane_options` fills `provider` from the board
(`lanes.py:472-477`), so on the `set-model` path a lane whose idea says only `<!-- model: qwen38-27b -->`
gets `_model_pair("qwen38-27b", <board provider>)` → `--model qwen38-27b --provider <board provider>`,
exactly the pairing `lane_model_opts`' docstring says must not happen; on the filing path the same lane
gets `_model_pair("qwen38-27b", None)` → `--model qwen38-27b` alone, resolved against the profile's own
provider. The initial card and its own revision cards therefore run under different provider
semantics, and which one you get depends on which shape the caller happened to pass.
Why it matters: the review/work model split is the board's author-versus-judge separation, and the
provider half of it is decided by an undocumented argument-shape convention rather than by the
function. *Fix:* make `lane_cfg` one shape — either always pass `lane_model_opts(lane)` and say so in
the docstring, or add an explicit `resolved=False` parameter so the two semantics are named.

**I2 (NEW) `driver/run.py:302-309` (with `:1247`, `:1451`, `:1527`, `:1748`, `:2582`, `:3347`) —
`lane_options()` returns an undocumented union (six typed keys + `"idea"` prose, or `None`) and its
consumers disagree about whether the shape is guaranteed.**

The function has **no docstring**. `lanes.resolve_lane_options` guarantees all six `PER_LANE` keys
(verified: `sorted(resolve_lane_options({}, {}, 1)) == sorted(PER_LANE)`), and `run.lane_options`
then adds `opts["idea"] = body` — a key of a different type in the same dict. Consumers split three
ways:

```python
1247:  opts = lane_options(lane) or {}                      # masks None
1451:  if not opts["integration-tests"]:                    # trusts the shape
1527:  f.write(opts["idea"])                                # trusts the extra key
1748:  return bool((lane_options(lane) or {}).get("refinement", True))
2582:  unit_tests=opts["unit-tests"], refinement=opts.get("refinement", True)
3347:  if lane_options(l) is not None]
```

The `refinement` fallback at `:1748` and `:2582` is **dead**: `resolve_lane_options` iterates
`sorted(board_schema.PER_LANE)`, which always contains `refinement`, so the default can never fire.
Why it matters: this is the shape the whole per-lane half of the driver passes around, and a consumer
that carries a fallback for a key the producer guarantees will keep working (silently, with the wrong
value) if the key is ever renamed — which is exactly the "a shape change degrades in one consumer
only" failure this aspect exists to find. *Fix:* give `lane_options` a docstring naming the returned
shape (`dict[str, object] | None`, keys `PER_LANE | {"idea"}`), and delete the dead `refinement`
fallbacks so the guarantee is asserted in one place.

**I3 (NEW) `driver/run.py:206-218` (with `:250`, `:510-511`, `:626`, `:675`, `:1235`, `:1517`) —
the manifest dict has two shapes and only 4 of its 22 keys exist in the fallback.**

`manifest()` returns `card_render.read_board(BOARD_DIR)` — the file's own dict, up to 22 keys — or, on
`FileNotFoundError`, a hand-written 4-key dict:

```python
217:  return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
218:          "integration-tests": False, "auto-gates": []}
```

Missing from the fallback: `slug`, `name`, `unit-tests`, `refinement`, `sequential`, `goal-cards`,
`goal-max-turns`, `max-runtime`, `max-retries`, `max-reworks`, `timeout-min`, `assignees`, `targets`,
`model`, `provider`, `model_override`, `provider_override`. Nothing declares which keys are optional,
so **every** consumer must use `.get` with its own fallback — `manifest().get("max-runtime")`
(`:626`), `manifest().get("sequential")` (`:250`), `manifest().get("goal-cards", …)`,
`manifest().get("auto-gates", …)` (`:1235`), `cfg.get("model_override")` (`:1517`) — and a consumer
that indexes instead crashes on the fallback shape only.
Why it matters: this is the "keys whose absence silently changes behaviour" case in its purest form.
A board that loses its `board.json` runs with no work model, no review pin (so its reviews run the
author's model — the condition `board_schema.review_model_notices:498-515` calls "catastrophic by
omission"), a 60 m ceiling and every gate human, and nothing states that this is a legal instance of
the manifest shape. *(The fallback's `integration-tests: False` also contradicts the help text the
comment above it names — already carried as `report-comments.md` I4; not re-reported here.)*
*Fix:* make the fallback a complete instance (all defaults from `board_schema.OPTIONS`) and assert
`set(fallback) == set(BOARD_KEYS)` in a test, so the two shapes are one shape.

**I4 (prior T-1, still unfixed) `template/board_schema.py:326-330` — the provider⇄model pairing rule
is presence-only and scope-blind.**

```python
328:  if provider_key in allowed and cfg.get(provider_key) and not cfg.get(model_key):
```

It asks only whether *a* model key exists somewhere in the same file. Reproduced:

```
validate({'lanes':2,'provider':['p1','p2'],'model':'m1'}): []       # lane 2 files provider p2 + lane 1's model m1
validate({'lanes':2,'provider':['p1','p2'],'model':['m1','m2']}): []
```

The comment two lines above states the rule the code does not implement ("a model belongs to one
provider — the flag pair is filed together or not at all"). Why it matters: the failure is a
spawn-time model/provider mismatch, and a spawn failure is final (one attempt). *Fix:* for the list
forms require **both** keys to be lists of `lanes` entries (or both scalars) and report the offending
lane.

**I5 (prior T-14 + T-15, still unfixed; one axis NEW) `template/board_schema.py:607-622` vs `:178-241`
(with `template/board.schema.json:212-214`) — the JSON schema and `validate` are two sources of truth
that disagree on four rules, and `--check-schema` cannot see any of them.**

The module's own docstring calls `json_schema()` "a CONVENIENCE, not the authority"
(`:629-633`) — but the shipped schema is what the editor and the `$schema` pointer in all six boards
resolve to, and `--check-schema` only proves the *file* equals the *generator*:

```
$ python3 template/board_schema.py --check-schema
…/template/board.schema.json is current                       # exit 0
file == json_schema(): True                                   # probe2.py
```

What it does not check is whether the generator agrees with the validator. Reproduced — all four of
these are accepted by the authority and refused (or accepted) differently by the schema:

```
validate({'lanes':1,'auto-gates':['Gi','Gi']}): []   # schema: uniqueItems:true  → editor refuses
validate({'name':'x'}):                          []   # schema: required:["lanes"] → editor refuses
validate({'$anything':1}):                       []   # schema: additionalProperties:false + only $schema declared
validate({'name':'   '}): ["… expected a non-empty string, got '   '"]   # schema: minLength:1 → editor accepts
```

The `$`-prefixed axis is new: `validate` skips **any** `$`-prefixed key (`:265-271`, deliberately, so
`$schema` can ride along), while `json_schema()` declares exactly one (`:634-635`) under
`additionalProperties: false`. So `{"$comment": "…"}` — the natural thing for a board author to write
— passes the door and is flagged by the editor the schema exists for.
Why it matters: the file that a board author's editor judges against and the file that decides whether
the board may be served state different contracts, and the check the repo trusts
(`test_board_schema.py:43-48`, CI) proves only internal consistency of the generator. *Fix:* add
`uniqueItems`/`required` handling to `validate` (or drop them from the schema), allow `^\\$` in the
schema's `additionalProperties`, use a `.strip()`-aware `pattern` for text, and add a test that
`validate(cfg) == []` implies the schema accepts `cfg` for a fixture set.

**I6 (prior T-6, still unfixed) `driver/run.py:302-309`, `:2370`, `:1748` — `None` from
`lane_options` is overloaded and silently reinterpreted.**

`lanes.read_idea` returns `None` for a missing file **and** for a file that exists but is blank
(`lanes.py:483-489`), so the two states are one value. The completion scan reads that `None` as "this
lane has no idea yet" and `break`s (`:2370-2374`), leaving `last = 0` and returning `False` forever
even with the last gate done — no `ALL GATES COMPLETE`, no `run-summary.json`, and no log line. The
refinement check reads the same `None` as `refinement=True` (`:1748`) and therefore changes the lane's
root code mid-run. Reproduced shape (from the probe of the underlying resolver): the value carries no
information about *which* of the two states produced it.
Why it matters: `lane-<k>.md` is a hand-editable file the driver re-reads every tick. *Fix:* return a
named state (`("no-idea" | "blank" | dict)`) or make `read_idea` raise on a blank file after the lane
opened, and halt loudly instead of reinterpreting.

**I7 (prior T-8, still unfixed) `driver/run.py:1229-1235` (with `:250`, `:510-511`, `:626`, `:675`,
`:1517`) — the manifest is read unvalidated everywhere except the armed-refile path.**

`board_schema.validate` is called from exactly one place in the driver, `validate_armed` (`:3484`).
Every other read is raw, and `auto_gates()` is the clearest instance:

```python
1235:  return manifest().get("auto-gates", board_schema.OPTIONS["auto-gates"][1])
```

`"max-runtime": "banana"` reaches the engine, which `board_schema`'s own module docstring says the
auditor then reads as 0 minutes (`:12-13`). Why it matters: editing `board.json` while a serve driver
is up is the normal operator action, and the door scripts — the only other validators — have already
run. *Fix:* call `board_schema.validate(cfg)` once per tick (or on mtime change) and `record_halt` on
problems, the way `validate_armed` reports them on the card.

**I8 (prior T-4, still unfixed) `template/board_schema.py:203-206` (with `template/card_render.py:116-120`)
— `targets` escapes the abspath rule.**

`default-workdir` is held to an absolute path *because* a relative path resolves differently for
create-board.sh, the driver and each card, and `~` means nothing to `os.path.abspath` (`:192-202`).
The `paths` kind applies none of that — it only requires non-empty strings:

```
validate({'targets':['relative/dir']}): []      # accepted
validate({'targets':[' ']}): ["… expected a list of non-empty paths, got [' ']"]   # the only check
```

`targets_text` then expands `~` but emits the relative path verbatim into every card body
(`card_render.py:120`), where the worker runs in `WORKDIR`. Why it matters: the board tells a worker to
write outside the tree the board owns, at a path that resolves somewhere different per card. *Fix:*
require `stripped.startswith("/")` in the `paths` branch (or abspath+expand in `targets_text`).

**I9 (prior T-2, prior code-review I2, still unfixed) `template/board_schema.py:156`, `:175`, `:222-225`
— a zero duration validates and means "no budget".**

```
validate({'max-runtime':'0s'}): []        # _DURATION_RE matches
duration_seconds('0s'): None              # `return int(round(total)) if total else None`
duration_seconds('1h 30m'): 5400          # but…
validate({'max-runtime':'1h 30m'}): ["… expected a duration like '90s'…"]
```

The validator and the parser also disagree on internal whitespace: the parser's
`(\d+(?:\.\d+)?)\s*([hms])` accepts `1h 30m`, `_DURATION_RE` (and the schema's `pattern`) does not.
So `max-runtime: "0s"` passes the door, yields no `--run-budget` and no subprocess timeout (an
unbounded card), and `run-audit.ceiling_minutes` → `None`, silently disabling E6. *Fix:* reject a zero
total in `_kind_error("duration", …)` and make the regex and the parser share one whitespace class.

## Suggestion

**S1 (NEW) `driver/file_lanes.py:34`, `:42` — the option table's defaults are re-declared outside it.**
`DEFAULT_MAX_RUNTIME = "60m"` and `DEFAULT_MAX_RETRIES = 1` duplicate
`board_schema.OPTIONS["max-runtime"][1]` and `["max-retries"][1]` (`board_schema.py:85-86`).
`lanes.py:372-376` states the house rule for exactly this ("Read FROM the option table so there is one
declaration of it") and `lanes.MAX_REWORKS` follows it; these two do not. `file_lanes` already imports
`board_schema` (it reads `OPTIONS` at `:176`), so deriving them costs nothing. *Fix:*
`DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]`.

**S2 (NEW; same class as prior T-24) `template/board_schema.py:139-141` — `gate_is_auto` accepts the
bare-string shape.**
`return code in (value or [])` works for any container, including a string:
```
gate_is_auto('Gi','Gi'): True
gate_is_auto('xxGi','Gi'): True
gate_is_auto(False,'Gi'): False
```
`validate` refuses a string `auto-gates` (`tests/test_board_schema.py:507-510`), and the schema types
it `array`, so this is unreachable through the validated path — but the function's own contract does
not refuse the shape it exists to be protected from, and `lanes.goal_args` (`lanes.py:155`,
`goal_args('C', cards='C')` → armed, reproduced) is the identical anti-pattern. *Fix:*
`if not isinstance(value, (list, tuple)): return False` in both.

**S3 (NEW) `driver/file_lanes.py:95-107` → `driver/run.py:52-63`, `:143-153` — the run-id shape
`run-<YYYYmmdd-HHMMSS>` is enforced only where it is minted.**
`next_run_key` builds it; its docstring is the only statement of the shape, and
`tests/test_unstarted_mint.py:140-149` pins it on the producer. The consumer takes any string:
`_read_current_run()` returns `f.read().strip() or None`, and `use_run` does
`os.path.join(RUNS_ROOT, run_id)` with no shape check — so a `runs/current` holding `../../x` or an
absolute path escapes `RUNS_ROOT`, and the same string is baked into card bodies by
`card_render.lane_paths`. *Fix:* one `RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")` beside
`next_run_key`, checked in `use_run`/`mint_run` and by the audit.

**S4 (NEW) gate/goal vocabularies declared four times with no test pinning them equal.**
`board_schema.GATE_CODES` (`:136`), `run.py:1056 GATE_NAMES`, `run.py:1057 GATE_CODE_OF`, and the
literal `if kind not in ("gi", "gp", "gc")` (`run.py:2337`) are four statements of one vocabulary;
`board_schema.GOAL_CODES` (`:132`) and `lanes.WORKER_CODES` (`:365`) are byte-identical tuples in two
modules. `grep -rn "GATE_CODE_OF\|GOAL_CODES" tests/*.py` finds no equality assertion. A gate or worker
code added to `lanes.LANE_CARDS` is refused by the option table (good) but raises `KeyError` inside
`gate_action` (`run.py:1241`) if it ever reaches the driver. *Fix:* derive `GATE_CODE_OF` from
`board_schema.GATE_CODES` (lowercase the code) and add one test per vocabulary asserting the copies
agree.

**S5 (NEW) `template/lanes.py:261-263` — `max_reworks` coerces three types and reads three sentinels
inconsistently.**
```
max_reworks({'max-reworks':0}):     3     # 0 is falsy → the house default
max_reworks({'max-reworks':False}): 3     # same
max_reworks({'max-reworks':'0'}):   0     # a truthy string → a cap of ZERO rounds
max_reworks({'max-reworks':True}):  1     # int(True) → a cap of ONE
```
A header cannot produce these (`_as_value`'s `count` branch raises below 1, `lanes.py:430-433`) and
`validate` refuses them (`count`, `minimum: 1`), so this needs an unvalidated manifest (I7) — but the
function's own contract accepts a union of `int | str | bool` and reads `0` as "unset" while `"0"` is
"a cap of zero". *Fix:* `if not isinstance(set_to, int) or isinstance(set_to, bool): raise`, and
treat `0` as an error rather than a fallback.

**S6 (NEW) `driver/run.py:207-210` — the manifest has three readers with three resulting shapes,
while the code claims one owner.**
> "Board manifest, through the SAME reader: `card_render` owns the file's shape, and a second
> `json.load` here is one edit away from two answers."

But `driver/run-audit.py:410` (`json.load(open(cfg_path))`) and
`board_schema.validate_or_die:565` (`cfg = json.load(f)`) both read the same file raw, and
`card_render.read_board` additionally injects `slug` from the directory name (`card_render.py:29`) —
so "the manifest dict" has `slug` guaranteed in one reader, guessed in another, and absent in the
third. *Fix:* have both readers call `card_render.read_board` (or move `slug` defaulting into
`board_schema.validate`'s contract and say so).

**S7 (NEW) observation: there is no static type layer at all.**
Zero `typing` imports and zero function annotations across the 43 manifest `.py` files; `run.py` is
3814 lines. Every contract in this report is prose + runtime check. This is a deliberate house style
(the comments are the specification) and I am not proposing a rewrite — but it is why findings I1–I3
are reachable: a dict's shape is asserted nowhere the reader can see, and two call sites can disagree
about it for years. A single `TypedDict` for the manifest, the resolved lane options and the run
record would make each of those disagreements a lint error, at the cost of three declarations.
*Fix (optional, in that order):* `TypedDict` for the resolved lane options and the manifest first —
they are the two dicts with the most consumers.

**S8 (prior T-16, still unfixed) `template/board_schema.py:237-240` vs `:607-622` — dead kind
branches take the schema generator with them.**
`_kind_error` accepts kinds `unchecked` and `path`; `_KIND_SCHEMA` declares neither. Reproduced:
```
accepted by _kind_error: [..., 'path', 'unchecked']
declared in _KIND_SCHEMA: ['abspath','bool','cards','count','duration','gates','paths','roles','slug','text']
json_schema() with an 'unchecked' option: KeyError 'unchecked'
```
So an option declared with either kind makes `json_schema()` raise and takes `--write-schema` /
`--check-schema` (which the suite runs) with it. *Fix:* delete the two dead branches, or declare their
schema.

**S9 (prior T-15, cosmetic half) `template/board_schema.py:644-646` — the per-lane array branch
cannot express the length rule and misplaces `default`.**
`{"type": "array", "items": spec, "minItems": 1}` where `spec` still carries `"default"` — a `default`
inside `items` means nothing to an editor, and `minItems: 1` is not "exactly `lanes` entries" (the
`$comment` and the module docstring both say so honestly). The result is an editor that accepts a
2-entry array on a 1-lane board and offers the wrong completion. *Fix:* move `default` to the `oneOf`
branch level and drop it from the array `items`.

**S10 (NEW) `tests/test_board_schema.py:65-71` — the six shipped manifests are never validated
against the schema they point at.**
The only test of the `$schema` link asserts the *string* `"../../template/board.schema.json"`. Every
shipped board is validated by `board_schema.validate` (`tests/test_shipped_boards.py:30-40`) but none
by the JSON schema — and since `validate` and the schema disagree on four rules (I5), a board can be
schema-invalid and still ship green. (All six currently satisfy both; verified by running `validate`
over each: `arena-federated-search, blade-workspace, is-even, portfolio-engineering,
roman-evaluator-java, roman-evaluator-js → OK`.) *Fix:* one `jsonschema`-backed test over
`boards/*/board.json` (skip if the library is absent), which also makes I5 fail loudly the moment it
is introduced.

---

## Prior-findings status (`docs/reviews/2026-09-20-code-review/report-types.md`, 27 findings)

| prior | subject | status at `59bc279` |
|---|---|---|
| T-1 | provider⇄model pairing presence-only / scope-blind | **STILL UNFIXED** — reproduced → I4 |
| T-2 | header error line numbers by substring search (`board_schema.py:436`) | **STILL UNFIXED** |
| T-3 | duplicate header keys last-wins (`board_schema.py:431`, `lanes.py:402`) | **STILL UNFIXED** |
| T-4 | `targets` escapes the abspath rule | **STILL UNFIXED** → I8 |
| T-5 | rework idempotency keys not run-scoped (`run.py:719,740,2420,2440`) | **STILL UNFIXED** — all four keys still `f"{BOARD}-…"` |
| T-6 | `None` from `lane_options` silently reinterpreted | **STILL UNFIXED** — `run.py:2370` `is None: break`, `:1748` `or {}` → I6 |
| T-7 | the `hermes --json` boundary consumed untyped | **STILL UNFIXED** — `run.py:376-379`, `:391-401` |
| T-8 | manifest trusted unvalidated outside the armed-refile path | **STILL UNFIXED** — `auto_gates()` `:1235` → I7 |
| T-9 | `preserve_artifacts` hardcodes `~/.hermes` (`run.py:3223-3224`) | **STILL UNFIXED** (also `report-errors.md` I7) |
| T-10 | loose `card_id_lane` used where `is_lane_card` belongs | **STILL UNFIXED** — `run.py:1898,1925,1955` vs `:2006` |
| T-11 | Java `RomanApiExceptionHandler` flattens client errors | **N/A** — board product code, out of this manifest |
| T-12 | Java `VALUES`/`SYMBOLS` invariants are documentation | **N/A** — board product code, out of this manifest |
| T-13 | `runs_util.py:151` `int(rec.get("log_offset") or 0)` can raise | **STILL UNFIXED** — still outside the per-record `try` |
| T-14 | `uniqueItems` in the schema, no dedupe in `_kind_error` | **STILL UNFIXED** — reproduced → I5 |
| T-15 | `required: ["lanes"]` contradicts the default | **STILL UNFIXED** — reproduced → I5, S9 |
| T-16 | unreachable/incoherent kind branches | **STILL UNFIXED** — reproduced `KeyError` → S8 |
| T-17 | dead re-merge + enrichment written into live state (`run.py:1359-1363`) | **STILL UNFIXED** |
| T-18 | `opts = lane_options(lane) or {}` unused (`run.py:1247`) | **STILL UNFIXED** — `opts` appears once in `_gate_action`'s body |
| T-19a | resolved lane options have no per-tick snapshot | **STILL UNFIXED** |
| T-19b | `RunState.reset()` clears 7 of ~29 holders | **STILL UNFIXED** — `opened, timed, drift, run_finished, announced, reported, timing_prev` |
| T-20 | import-time globals (`run.py:14-20`, `:203`) | **STILL UNFIXED** |
| T-21 | substitution order / unknown placeholders (`card_render.py:156-163`) | **STILL UNFIXED** |
| T-22 | ownership decided by `abspath` prefix, not `realpath` (`card_render.py:90-91`) | **STILL UNFIXED** |
| T-23 | `base_code` docstring mixes the two rework grammars (`lanes.py:359`) | **STILL UNFIXED** |
| T-24 | `goal_args` accepts the bare-string shape (`lanes.py:155`) | **STILL UNFIXED** — reproduced → S2 |
| T-25 | Java `RomanMain` rewrites EOF as the empty string | **N/A** — board product code, out of this manifest |
| T-26 | Java `EvaluateController` trusts the request shape | **N/A** — board product code, out of this manifest |

**Verified fixed: 0. Still unfixed: 23. Not applicable (board product code removed from this
manifest by the `bots/` → `driver/`+`template/` split and `.opencodereview/rule.json`'s
`boards/*/work/**` exclusion): 4** (T-11, T-12, T-25, T-26).

---

## What is validated vs what is not (the shape boundary, updated)

| Shape | Validated where | Malformation with no error |
|---|---|---|
| `board.json` | `board_schema.validate` at the door scripts + `validate_armed`; generated schema in the editor | edited while a driver runs (I7); `targets` relative (I8); the schema/authority four-way drift (I5); a zero duration (I9); a 4-key fallback instance (I3) |
| resolved lane options | `resolve_lane_options` guarantees all six keys; `validate_headers` at every door | the union with `"idea"` and `None` is undocumented (I2); `None` conflates two states (I6); dead per-consumer fallbacks |
| `lanes.model_args`' `lane_cfg` | nothing | two shapes, two provider semantics (I1) |
| gate/goal vocabularies | the option table, at the door | four restatements, no equality test, `KeyError` at the consumer (S4); `gate_is_auto` string containment (S2) |
| run-id `run-<ts>` | the producer (`next_run_key`) + one test | the consumer joins any string onto `RUNS_ROOT` (S3) |
| `hermes --json` | nowhere | object-where-list (prior T-7); `log_offset` conversion (prior T-13) |
| run/chain/ledger records | readers skip malformed JSONL lines | no declared record shape; `reset()` covers 7 of ~29 holders (prior T-19b) |
| the manifest's *default* values | `OPTIONS` for the validator and the schema | re-declared in `file_lanes` (S1); the fallback dict's `integration-tests: False` contradicts the help text |
