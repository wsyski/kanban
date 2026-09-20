# Type & shape design review — kanban (all-files)

Repo: `/opt/projects/kanban/main/kanban` @ `9f80af2` (branch `main`). Scope: whole files, no diff.
Aspect: encapsulation, invariants and the shapes the engine passes between modules —
**what is validated, and what can be malformed with no error**.

Files read in full (18, all in scope):

- Java (6): `RomanMain.java`, `RomanNumeral.java`, `RomanServiceApplication.java`,
  `EvaluateController.java`, `RomanApiExceptionHandler.java`, `RomanEvaluationService.java`
- Schemas/shapes (7): `template/board.schema.json`, `boards/{arena-federated-search,blade-workspace,
  is-even,portfolio-engineering,roman-evaluator-java,roman-evaluator-js}/board.json`
- Python (5): `template/lanes.py`, `template/board_schema.py`, `template/card_render.py`,
  `driver/run.py` (all 3814 lines), `driver/runs_util.py`

Consulted for evidence only (not in my subject list): `driver/file_lanes.py` (l.128–200, 271–320),
`driver/start-board.sh` (l.55–115), `boards/roman-evaluator-java/work/roman-service/src/main/
resources/openapi/roman-service.yaml`, plus the brief and the manifest.

Checks actually executed (read-only): `board_schema --check-schema` (current: **True**), all six
`boards/*/board.json` through `board_schema.py` (**all six OK**), and in-memory probes of
`validate` / `validate_headers` / `parse_idea` / `card_render.render_body_values` for the cases
marked *verified* below. No file was modified; no driver was run.

**No Critical finding.** The strongest findings are Important: shapes that are accepted by the
declared authority and then used as if they were something else.

---

## Type: the `board.json` manifest option table (`board_schema.OPTIONS` → `validate`)

### Invariants identified
- `lanes` is a positive integer; every per-lane option is either one value or a list of **exactly**
  `lanes` entries, indexed from lane 1.
- A `provider` and its `model` are declared in the same scope, together or not at all.
- `max-retries` is exactly 1 (a failed card is final).
- kinds are closed: bool / count / text / slug / abspath / paths / gates / cards / duration / roles.
- keys are closed (`additionalProperties:false` in the generated schema; `$`-prefixed keys are meta).
- The generated `board.schema.json` is **derived** and `--check-schema` guards it.

### Ratings
- **Encapsulation: 9/10** — one declaration (`OPTIONS`) drives validation, the `--schema` table, the
  header key set and the editor schema; nothing else may restate an option. `PER_LANE`/`HEADER_KEYS`
  are derived, so they cannot drift.
- **Invariant Expression: 7/10** — the per-lane-vs-board distinction is expressed in the kind table
  and explained, but the *authority* and the *schema it generates* disagree on two rules (see T-14,
  T-15), so the file the editor reads is not the file that judges.
- **Invariant Usefulness: 9/10** — the invariants are the ones that actually bite (a bad lane shape
  silently arms the wrong cards; a bad duration becomes a zero-minute ceiling).
- **Invariant Enforcement: 7/10** — `validate` returns *every* problem, not the first, and rejects
  bool-as-int, `~` paths, unknown gate/card codes. But two rules are presence-only or cross-scope
  blind (T-1), duplicate header keys are silently last-wins (T-3), and `targets` escapes the abspath
  rule that `default-workdir` is held to (T-4).

### Strengths
Explicit `bool is not an int` guard; the `~`-is-not-expanded message; the rename table feeding
`_near`; the schema-not-key-list rationale; `ONE_ATTEMPT` refusing a knob whose only legal value is 1.

### Concerns / Recommended improvements
See findings; each is a small, local change to `_kind_error` / `validate` / `_LOOSE_HEADER_RE`.

---

## Type: the idea header (`<!-- key: value -->`) → resolved lane options

### Invariants identified
- A header is a whole line; a line *shaped* like a header is judged as one (the loose lexer).
- Keys are the per-lane subset; values are JSON literals bridged by `_as_json`.
- `resolve_lane_options` = schema default → board default (scalar or per-lane list) → idea header.
- The resolved dict is **one shape**: exactly the `PER_LANE` keys.

### Ratings
- **Encapsulation: 6/10** — `run.lane_options` adds an out-of-band `"idea"` key, so the resolved
  options dict is a union of "the option table" and "plus the idea prose"; nothing type-checks it.
- **Invariant Expression: 7/10** — the precedence is documented once and implemented generically
  (nothing names individual options), which is the right shape.
- **Invariant Usefulness: 8/10** — resolves the exact class of bug the module was written for.
- **Invariant Enforcement: 4/10** — a duplicate header key is silently overwritten (`validate_headers`
  verified `[]`, `parse_idea` verified last-wins); error line numbers can point at the wrong line
  (verified); and the *resolved* options are re-derived from disk on every call, so one tick can hold
  two answers.

### Concerns
T-2, T-3, T-19 below; plus the file is re-read (and re-parsed) dozens of times per tick.

---

## Type: the lane card graph (`lanes.LANE_CARDS` / `PARENTS` / `lane_cards()`)

### Invariants identified
- Card ids are `{code}{lane}`, titles embed `LABELS` text, parents are ids of codes (`PARENTS`) or
  the chain predecessor; dropped codes are filtered out of both.
- A lane's root is *positional* (`lane_root_code`), never a hardcoded code.
- `base_code` maps `P1` / `P1-rev-1` / `RVa1-r2` back to the code.
- `JUDGE_CODES`/`WORKER_CODES`/`IT_CODES`/`UT_CODES`/`REFINEMENT_CODES` partition the graph by intent.

### Ratings
- **Encapsulation: 8/10** — the graph is declarative data with one walker; `PARENTS` exists because a
  walk cannot express the fork, and that is stated.
- **Invariant Expression: 7/10** — ids/titles encode code+lane+round and the round grammar is only in
  prose (`-rev-N` for revisions, `-rN` for re-reviews); `base_code`'s own docstring mixes the two
  spellings (T-23).
- **Invariant Usefulness: 9/10** — the id-then-title split is what makes a relabelled card still
  findable.
- **Invariant Enforcement: 5/10** — the graph is filtered with `startswith` on titles and matched with
  a boundary-aware `title_of_prefix`; consumers are inconsistent about which one they use
  (`card_id_lane` vs `is_lane_card`, T-11), and code rework rounds are counted by scanning titles
  (`code_rework_rounds`), so the count is a property of the *board read*, not of the loop.

---

## Type: run state, the ledger and the CLI boundary (`run.RunState`, `chain.jsonl`, `verdicts.jsonl`)

### Invariants identified
- One run = one directory = one `current` pointer; cards carry their run's paths in their bodies.
- Every record reader rejoins from disk on restart and is idempotent.
- Every external call is bounded (`CLI_TIMEOUT_S`); a failed read is recorded (`STATE.read_error`)
  and never passes for "a card with no events".
- A JSONL reader skips a malformed line rather than dying.

### Ratings
- **Encapsulation: 5/10** — `RunState` is one home for 29 holders (good), but `reset()` clears only 7
  of them, which is exactly the "a seventh holder added later is silently left behind" failure the
  class docstring says it exists to prevent — now one level down (T-19b). Import-time side effects
  (`ONCE`/`SERVE`/`BOARD`, `use_run`, `manifest()`) make the module's shape a property of the
  importing process (T-20).
- **Invariant Expression: 6/10** — record shapes are literals built ad hoc in ~10 places (`ledger`,
  `chain_record`, `card_log`, the summary) with the round-trip key set only visible by reading both
  writers and readers.
- **Invariant Usefulness: 8/10** — the guards are load-bearing (idempotency keys, log offsets,
  rejoin, the parking brake vs a worker's block).
- **Invariant Enforcement: 5/10** — the CLI's `--json` output is consumed untyped at three sites
  (T-7), one reader crashes on a malformed record where its siblings skip (T-13), and two of eleven
  idempotency keys omit the run id that the other nine rely on (T-5).

---

## Type: the numeral contract (`RomanNumeral` → `RomanEvaluationService` → `EvaluateController` → `EvaluationResponse`)

### Invariants identified
- Accepted input: a *canonical* roman spelling of 1..3999, taken verbatim (no trimming, no case
  folding, no unicode tolerance).
- Output: an `int` in 1..3999.
- Failure: `IllegalArgumentException`, mapped to 400 at the HTTP edge.
- `VALUES`/`SYMBOLS` are index-parallel.

### Ratings
- **Encapsulation: 8/10** — `RomanNumeral` is a final, uninstantiable, side-effect-free rule holder;
  the service consumes it and does not reimplement it, as documented.
- **Invariant Expression: 4/10** — the 1..3999 invariant lives in javadoc, not in a type: `parse`
  returns a bare `int` and `new EvaluationResponse(value)` accepts any int. The accepted *input* shape
  is expressed in no declaration at all — `roman-service.yaml` declares `roman` as an unconstrained
  string (l.40–46) and `value` as an unconstrained integer (l.47–52).
- **Invariant Usefulness: 8/10** — canonical-only is the board's actual rule, enforced by
  `encode(value).equals(numeral)` (a genuinely strong check).
- **Invariant Enforcement: 6/10** — construction is validated at the one true entry point, but the
  error channel is a single generic `IllegalArgumentException`, which the HTTP edge cannot
  distinguish from an internal fault (T-11); and `VALUES`/`SYMBOLS` correspondence is enforced by
  nothing (T-12).

---

# Findings

Severity: Critical > Important > Suggestion. Every line cites `file_path:line_number`.

## Important

**T-1 `template/board_schema.py:326-330` — the provider⇄model pairing rule is presence-only and
scope-blind.**
`cfg.get(provider_key) and not cfg.get(model_key)` asks only whether *a* model key exists somewhere
in the same file. *Verified:* `{"lanes":2,"provider":["p1","p2"],"model":"m1"}` validates clean, so
lane 2 files with provider `p2` and lane 1's model `m1` — the exact mismatched pair the comment two
lines above says must be refused ("a model belongs to one provider — the flag pair is filed together
or not at all"). Why it matters: the failure is a spawn-time model/provider mismatch, and a spawn
failure is final (one attempt). *Fix:* for the list forms require **both** keys to be lists of
`lanes` entries (or both scalars); report the offending lane.

**T-2 `template/board_schema.py:436-438` — header error line numbers can point at the wrong line.**
Line attribution is `next((k for k in lines if repr(k) in p), None)` — a substring search of the
problem text. The "is a board-level option … only [...] are per-lane" message embeds the whole
per-lane key list, so any *valid* per-lane header earlier in the file wins the match. *Verified:*
`"<!-- model: m1 -->\n<!-- lanes: 2 -->\n"` reports the error at `lane-<k>.md:1` (the `model` line)
instead of line 2. Why it matters: the driver prints these at the door and the author edits the wrong
line. *Fix:* have `validate` return `(key, message)` pairs (or a key→line map) instead of
re-deriving the key from the message.

**T-3 `template/board_schema.py:431` (with `template/lanes.py:402`) — duplicate header keys are
silently last-wins.**
`headers[key] = value` overwrites with no error, in both the validator and the extractor.
*Verified:* an idea with `<!-- unit-tests: false -->` then `<!-- unit-tests: true -->` yields
`validate_headers → []` and `parse_idea → {'unit-tests': 'true'}`. Why it matters: a lane's shape
silently becomes whichever line was written last, which is precisely the "silently wrong lane shape"
class this module was built to refuse. *Fix:* report a duplicate key with both line numbers and
refuse the file.

**T-4 `template/board_schema.py:203-206` (with `template/card_render.py:118-122`) — `targets` escapes
the abspath rule.**
`default-workdir` is held to an absolute path *because* a relative path resolves differently for
create-board.sh, the driver and each card, and `~` means nothing to `os.path.abspath` (l.192-202).
The `paths` kind applies none of that. *Verified:* `{"lanes":1,"targets":["relative/dir"]}` validates;
`targets_text` then expands `~` but emits the relative path verbatim into every card body
(`card_render.py:122`), where the worker runs in WORKDIR. Why it matters: the board tells a worker to
write outside the tree the board owns, in a path that resolves somewhere different per card — the
same wrong-evidence class the pathspec fixes in `staged_files` are for. *Fix:* in `_kind_error`'s
`paths` branch require `stripped.startswith("/")` (or abspath+expand at `targets_text`).

**T-5 `driver/run.py:719,740,2420,2440` (key built at 679) — rework idempotency keys are not
run-scoped, unlike every filing key.**
Filing: `driver/file_lanes.py:190` `f"{key_prefix}-{card['id']}"`, `:315` `-idea-{lane}`, where
`key_prefix` is the run key minted at `run.py:3555`. Rework: `f"{BOARD}-rev-{base}{lane}-{round_no}"`,
`f"{BOARD}-rr-{base}{lane}-r{n}"`, `f"{BOARD}-rev-{owner}{lane}-{round_no}"`, `f"{BOARD}-rr-C{lane}-r{n}"`
— no run key. `run.py:3553` states the convention: "One id for the cards' idempotency keys AND the run
directory, so a card in the engine names the directory holding its evidence." A refile **archives**
the old cards, it does not delete them, and card titles/round numbers repeat across runs by design.
Why it matters: if the engine's idempotency lookup is not status-filtered, run 2's round 1 dedupes to
run 1's archived card — `create` returns that (archived) card, `kb("link", rr_id, gate_id)` links a
dead card, the rework never runs and the gate is never released. The filing keys were scoped for this
reason and the rework keys were not. *Fix:* prefix the four rework keys with the current run key
(`_read_current_run()`).
*(Honesty note: the engine's dedupe semantics are not in this repo — no `hermes`/`kanban_db` package
is installed — so the collision is inferred from the two conventions disagreeing, not observed.)*

**T-6 `driver/run.py:2368-2374` (with `1742-1748`, `302-309`, `2249-2250`) — `None` from
`lane_options` is silently reinterpreted.**
`lanes.read_idea` returns `None` for a missing/empty file, and there are exactly two outcomes
(parsed / None). `lane_options(lane) is None` in the completion scan `break`s out and leaves
`last = 0`, so the tick returns `False` forever even with `Gc1` done — no `ALL GATES COMPLETE`, no
`run-summary.json`, and *no log line*. `lane_refinement(lane)` reads the same `None` as
`refinement=True` (`(lane_options(lane) or {}).get(...)`) and therefore changes the lane's ROOT code
mid-run: on a `refinement:false` lane whose file is blanked, P stops being the root, falls into the
`elif not parents` branch (`lane_cards` gives it no parents) and is never promoted again — a stall
with no error, no comment, no halt. Why it matters: `lane-<k>.md` is a hand-editable file the driver
re-reads every tick, and the run's own snapshot is the copy the cards were told to trust. *Fix:*
snapshot the resolved options per lane per run (like the idea snapshot) and halt loudly when the file
disappears or blanks after the lane opened.

**T-7 `driver/run.py:376-379` and `391-401` — the `hermes --json` boundary is consumed untyped.**
`card_show` does `json.loads(kb(...))` and returns whatever shape arrives; `board()` does
`json.loads(kb("list","--json"))` and immediately iterates it as a list of dicts (`card["title"]`).
Compare `card_record` (l.2911), which *does* guard `isinstance(record, dict)` — the same boundary,
two different levels of trust. Why it matters: a CLI that prints an object (or an error page) instead
of a list crashes the tick; on `board()` that is every tick, halting the board with a TypeError from a
shape the code declared impossible. *Fix:* one `_as_list(parsed)` / `_as_dict(parsed)` helper at both
sites, returning `[]`/`{}` plus a `_warn_once`-style log.

**T-8 `driver/run.py:625-633` and `666-681` (with `206-221`) — the manifest is trusted unvalidated
outside the armed-refile path.**
`manifest()`→`card_render.read_board` is a bare `json.load`, and `board_schema.validate` is called
from exactly one place in the driver: `validate_armed` (l.3484), i.e. only in serve mode when a
Triage card has been armed. Every other read is raw: `max-runtime` → `--max-runtime` on every rework
card (626/678), `targets` (627), `assignees` (675), `goal-cards`/`goal-max-turns` (510-511),
`sequential` (250), `auto-gates` (1235), `model`/`provider` (2738). `"max-runtime": "banana"` reaches
the engine, which the module docstring itself says the auditor then reads as **0 minutes**
(`board_schema.py:12-13`). Why it matters: editing `board.json` while a serve driver is up (raising
`max-reworks`, adding a target) is the normal operator action, and the door scripts — the only other
validators — have already run. *Fix:* call `board_schema.validate(cfg)` once per tick (or on mtime
change) and `record_halt` on problems, the way `validate_armed` reports them on the card.

**T-9 `driver/run.py:3223-3224` — `preserve_artifacts` hardcodes `~/.hermes` while the rest of the
file resolves the kanban root through `hermes_kanban_dir()`.**
`hermes_kanban_dir()` (l.3457-3465) exists precisely because "a profiled shell leaks HERMES_HOME, so
probe both", and `worker_log_path` (l.2823) uses it plus `HERMES_KANBAN_LOGS_DIR`. The patch sweep
globs `os.path.expanduser("~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")` — no probe,
no env override. Why it matters: under any non-default (or leaked) HERMES_HOME the glob matches
nothing, `shutil` is never called, and the run's provenance patches are silently never kept — a
missing artefact with no error, in the one function whose docstring says the patches "were written
exactly for this". *Fix:* build the path from `hermes_kanban_dir()` (and honour
`HERMES_KANBAN_LOGS_DIR`-style overrides) as `worker_log_path` does.

**T-10 `driver/run.py:1896-1900, 1925, 1951-1957` — the loose title regex is used where the strict
lane-card predicate belongs.**
`card_id_lane` (l.2000-2003, `^[A-Za-z]+(\d+)(?:-r(?:ev-)?\d+)?:`) matches *any* card titled like a
lane card, while `is_lane_card` (l.2006-2010) exists to exclude non-lane cards and its own docstring
names the case ("an idea card, whose title is the idea's own heading and may look like `Idea2: …`").
`record_chain_starts`, `record_chain_done` and `attach_hand_offs` gate only on `card_id_lane`; the
preflight (l.2172) and the handler guards use `is_lane_card`. Worse, `record_chain_done` then treats
`code.lower().startswith(("rv","g"))` as a *verdict* card (l.1975-1997), so a human card titled
`Gate2: …` or `RVx1: …` writes a verdict line into the run's ledger. Why it matters: the chain and the
ledger are the run's audit surface (`doc-chain.py`, `run-audit.py` read them by card id), and a
phantom row is indistinguishable from evidence. *Fix:* use `is_lane_card` at the three call sites
that ask "is this a lane card".

**T-11 `boards/roman-evaluator-java/work/roman-service/src/main/java/com/example/roman/service/RomanApiExceptionHandler.java:16-20`
— one generic exception type flattens client errors and internal faults into 400.**
The domain's only error channel is `IllegalArgumentException` (`RomanNumeral.java:41-52`,
`RomanEvaluationService.java:20-22`), and the advice maps **every** `IllegalArgumentException` from
anywhere in request handling to `400 Bad Request`, with the exception's own message echoed to the
caller. Why it matters: a future internal invariant violation (a null deref that surfaces as IAE, a
library contract breach) is reported to the client as their malformed input and never as a 500 — the
one case the class docstring claims it handles ("A rejected numeral and an unreadable body are both
client errors, never 500") is exactly what is no longer checkable. *Fix:* introduce
`InvalidNumeralException extends IllegalArgumentException` (or a sealed `NumeralError`) at the
domain boundary and narrow the handler to it.

## Suggestion

**T-12 `RomanNumeral.java:8-14` (with `EvaluateController.java:22-24` and
`openapi/roman-service.yaml:40-52`) — the numeral's invariants are documentation, not types.**
`VALUES`/`SYMBOLS` are two parallel arrays whose index correspondence *is* the algorithm's core
invariant, enforced by nothing (a reordered entry silently mangles every value); `parse` returns a
bare `int`, so "always between 1 and 3999" exists only in javadoc while `EvaluationResponse(value)`
accepts any int; and the request/response schemas declare `roman` as an unconstrained string and
`value` as an unconstrained integer, so the contract the controller's docstring says "owns the
contract" expresses none of it either. *Fix:* a single `List<Entry>` (symbol, value) instead of
parallel arrays, and a `pattern`/`minimum`/`maximum` in `roman-service.yaml` so invalid shapes are
rejected where they are declared.

**T-13 `driver/runs_util.py:151` — `int(rec.get("log_offset") or 0)` can raise out of a reader whose
siblings skip malformed records.**
The enclosing `try` catches only `OSError`; the per-record `try` covers `json.loads` alone. A single
garbled `log_offset` in `verdicts.jsonl` raises `ValueError` → `load_one_shots` (run.py:1677) → the
tick → after `TICK_ERROR_LIMIT` (3) ticks the board halts naming the exception. Every other JSONL
reader in the codebase (`load_chain_ids:1654`, `load_one_shots:1683`, `lane_opened_on_record:1840`)
skips a bad record. *Fix:* move the `int(...)` inside the per-record `try` (or `continue` on a
non-numeric offset).

**T-14 `template/board_schema.py:617-618` vs `207-221` — two declarations of the uniqueness rule.**
`_KIND_SCHEMA` emits `uniqueItems: true` for `gates`/`cards`, but `_kind_error` does not dedupe.
*Verified:* `validate({'lanes':1,'auto-gates':['Gi','Gi']})` → `[]`, i.e. the authority accepts what
the shipped schema refuses. *Fix:* report duplicates in `_kind_error` (matching the schema) or drop
`uniqueItems` from the schema; today a board can be "valid" or not depending on which file asks.

**T-15 `template/board_schema.py:659` vs `280` — `required: ["lanes"]` contradicts the default.**
The schema demands `lanes`; `validate` defaults it to 1 (`OPTIONS["lanes"][1]`). *Verified:*
`validate({'name':'x'})` → `[]`. A manifest the authority accepts is refused by the shipped schema —
the editor and the door disagree. *Fix:* drop `required` (the default makes `lanes` genuinely
optional) or require it in `validate`.

**T-16 `template/board_schema.py:237-240` and `426-429` — unreachable/incoherent kind branches.**
`_kind_error` accepts kinds `unchecked` and `path`, which have no entry in `_KIND_SCHEMA` (l.607-622),
so an option declared with either kind makes `json_schema()` raise `KeyError` and takes
`--write-schema`/`--check-schema` (which the suite runs) with it. `_as_value`'s `"gates"` branch
(`lanes.py:426`) is unreachable for the same reason in reverse: no per-lane option has kind `gates`.
*Fix:* delete the dead kinds/branches, or declare their schema.

**T-17 `driver/run.py:1359-1363` — dead re-merge, plus enrichment written into live state.**
`full = state.get(t) or c; if full is not c: full.update(c); full = {**state[t], **full}` — the last
line re-merges the dict with itself (a no-op that reads as if it combined two sources).
`full.update(c)` also injects `last_run`/`gave_up` into the live card dicts the rest of the tick
reads, so the shape of a state entry depends on whether `record_timing` has run yet. *Fix:* build a
local dict for the log entry and leave `state` alone.

**T-18 `driver/run.py:1247` — `opts = lane_options(lane) or {}` in `_gate_action` is unused.**
The value is never read (the auto-gates decision moved to `manifest()` at l.1235 after the
`KeyError: 'auto-gates'` incident), but it still costs a per-tick file read and re-parse of
`lane-<k>.md`. *Fix:* delete the line.

**T-19a `driver/run.py:1193, 1584, 1600, 1615, 2369, 1759` — resolved lane options have no per-tick
snapshot.**
Each call re-reads and re-parses `lane-<k>.md`, so one tick can hold two different answers for the
same lane (the cap in `gate_rework` vs the cap in `rework_rounds`; `lane_root_code(...)` in the
preflight vs in the promotion loop at 2249). *Fix:* resolve once per tick behind a tick-scoped cache
the way `show_memo` does for cards.

**T-19b `driver/run.py:125-133` — `RunState.reset()` clears 7 of ~29 holders.**
Not cleared: `chain_started`, `chain_done`, `attached`, `empty_result_noted`, `read_error`,
`unreadable_ticks`, `log_offsets`, `requeued`, `repromoted`, `dependency_noted`, `gate_tag`,
`gate_evidence`, `waiting`, `deadman_stuck`, `escalated`, `timing_path`/paths. Most are card-id keyed
(new ids each run, so stale entries are only an unbounded-serve-process leak), but `gate_tag` is keyed
by card *code*, which repeats across runs. The class docstring names this exact failure ("a seventh
holder added later is silently left behind — carried from the finished run into the new one") — the
reset list is hand-written, so it is the same hazard one level down. *Fix:* reset by construction
(build a fresh `RunState` and rebind `STATE`, keeping only the deliberate survivors).

**T-20 `driver/run.py:14-20, 203, 221` — import-time globals.**
`BOARD`, `ONCE`, `SERVE` are read from `os.environ`/`sys.argv` **at import**, and importing also
mints the run paths (`use_run(_read_current_run())`) and reads the manifest. The module's behaviour
therefore depends on the importing process's argv (the file notes the test suite imports it).
*Fix:* read them in `main()` / pass a small config object.

**T-21 `template/card_render.py:158-165` — substitution order and unknown placeholders.**
Fragments are expanded first (correct, and load-bearing: `<PLAN_CHECKLIST>` must be gone before
`<PLAN>` is substituted), then values in dict order, where `<WORKDIR>` precedes `<WORKDIR-STATE>` —
safe only because the closing angle bracket prevents `<WORKDIR>` from matching inside
`<WORKDIR-STATE>`. A future placeholder that is a prefix of another *without* that boundary would be
corrupted silently. `render_body` also never reports a placeholder it does not know; the check lives
in `run.py:1788-1790` and only reaches the chain record (doc-chain's F4). *Verified*: the shipped
bodies' placeholder set exactly equals `render_body_values()` keys + `FRAGMENTS` + `<YOUR-CARD-ID>`,
so today there is no live defect — this is a shape fragility, not a bug. *Fix:* one
`re.sub(r"<[A-Z][A-Z0-9_-]*>", lookup)` pass that raises on an unknown token.

**T-22 `template/card_render.py:92-95` — ownership is decided by string prefix, unresolved.**
`own = os.path.abspath(workdir).startswith(os.path.abspath(board_dir) + os.sep)`; `abspath` does not
resolve symlinks, so a workdir reached through a symlink (or a symlinked board dir) is announced to
every lane as "an EXISTING PROJECT this board did not create" — the misreading this field exists to
prevent. *Fix:* compare `os.path.realpath(...)` on both sides.

**T-23 `template/lanes.py:358-360` — `base_code`'s docstring mixes the two rework grammars.**
It documents `P1 / P1-rev-1 -> P` and `RVa1-r2 -> RVa` in one line, but the file's real families are
`-rev-N` (revision cards) and `-rN` (re-reviews) — and `newest_of_prefix` (run.py:470) `lstrip("-r")`
tolerates both by accident. The distinction is what the rework holds key on. *Fix:* document the two
grammars separately (comment-only change).

**T-24 `template/lanes.py:151-158` — `goal_args` accepts the bare-string shape.**
`code not in (cards or ())` works for any container, including a string: with `cards="C"` (the shape
`board_schema` exists to refuse, see its own docstring l.10-11) `"C" in "C"` is True and the goal
judge is armed. Unreachable through the validated path, but the function's own contract does not
refuse the shape it was written to be protected from. *Fix:* `if not isinstance(cards, (list, tuple))
or code not in cards: return []`.

**T-25 `boards/roman-evaluator-java/work/roman-cli/src/main/java/com/example/roman/RomanMain.java:30-32`
— EOF is rewritten as the empty string.**
`numeral == null` (no input at all) becomes `""`, so the user sees
`invalid roman numeral: out of range: ` — an empty numeral in the middle of an error message, with
the wrong diagnosis (nothing was read, rather than something invalid). *Fix:* return a distinct
"no input" message/status before parsing.

**T-26 `boards/roman-evaluator-java/work/roman-service/src/main/java/com/example/roman/service/EvaluateController.java:22-25`
— the request's shape is trusted to the service.**
`evaluationRequest.getRoman()` is forwarded with no null check even though `roman` is declared
`required` in the contract document and the generated model does not enforce it: `{}` reaches
`RomanNumeral.parse(null)`, which happens to throw (and is then flattened into a 400, T-11). *Fix:*
either enforce `required` in the generated model or check explicitly at the boundary.

**T-27 `driver/run.py:3708-3712` — `--timeout-min` parsing is token-shape dependent.**
`a.startswith("--timeout-min")` matches the `--timeout-min=N` form too, whose value is then read from
`sys.argv[index + 1]` — the *next, unrelated* argument — and raises `IndexError` when the flag is
last. `driver/start-board.sh:103/109` always passes the space form, so this only bites a hand-run
driver, at startup, outside the try loop. *Fix:* match `--timeout-min` exactly and take the next
token, or use `argparse`.

---

## What is validated vs what is not (summary of the shape boundary)

| Shape | Validated where | Malformation with no error |
|---|---|---|
| `board.json` | `board_schema.validate` at the door scripts + `validate_armed`; generated schema in the editor | edited while a driver runs (T-8); `targets` relative (T-4); schema/authority divergences (T-14, T-15) |
| idea header | `validate_headers` at every door + on every read | duplicate keys (T-3); wrong error line (T-2); file blanked mid-run (T-6) |
| lane card graph | `lane_cards` is generated; consumers re-derive | loose `card_id_lane` vs `is_lane_card` (T-10) |
| `hermes --json` | nowhere (untyped `json.loads`) | object-where-list (T-7), runs where list expected (T-13) |
| run/chain/ledger records | readers skip malformed JSONL lines | `log_offset` conversion (T-13); no schema for the records themselves |
| numeral input/output | `RomanNumeral.parse` (strong) | no type for 1..3999, no pattern in the contract, generic IAE at the HTTP edge (T-11, T-12, T-26) |
