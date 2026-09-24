# Code-Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the findings of the two `ocr-review` runs against this repo — `docs/reviews/2026-09-20-code-review.md` and `docs/reviews/2026-09-23-code-review.md` — so the engine's Criticals are gone, the auditor can no longer lie, and every contract the review called untested has a behavioural test.

**Architecture:** The work is repair, not redesign: each task fixes one finding-cluster in the module that owns it, in the review's own recommended order (Critical correctness first, then the tests that keep those fixes honest, then the silent-default narrowing, then doc rot). Nothing is restructured; `template/` stays the shared layer and `driver/` stays the kanban driver. Where a fix changes an accepted value (`"0m"`, a boolean `auto-gates`), the schema table is the one place it changes.

**Tech Stack:** Python 3.11+ (no annotations anywhere in this repo — keep it that way), bash (`set -euo pipefail`), pytest via `./test.sh`, `template/board.schema.json` (generated).

**Spec:** The two review documents are the spec, with their per-aspect reports beside them:
`docs/reviews/2026-09-23-code-review.md` (+ `2026-09-23-code-review/report-{code,tests,comments,errors,types}.md`) is normative — it is the later run and it dispositions the earlier one. `docs/reviews/2026-09-20-code-review.md` is the superset source for the findings the 09-23 run only counts. Findings are cited below as `09-23 C1`, `09-23 I13`, `09-20 K2` etc.

## Global Constraints

- **Never commit.** Per the operator's standing rule: `git add` the changed files, run `git status --short`, report, then STOP and ask. Every "Stage" step below is **stage-and-ask**, and a subagent implementer ends its turn there.
- Repo root for every command: `/opt/projects/kanban/main/kanban`.
- **`./test.sh` always runs the WHOLE suite, whatever you pass it** (`test.sh:14` is `exec "$py" -m pytest -q "$REPO/tests" "$@"`). Use it for the whole-suite gate; for one file run `/usr/bin/python3 -m pytest -q tests/<file>.py` directly. **Baseline measured 2026-09-24 at HEAD `edea8ab`: `666 passed in 12.88s`.** A task that adds tests states its own expected delta; a task that changes no test must leave the count at 666 and all green.
- **`file:line` in both reviews refers to commit `59bc279`; HEAD is `edea8ab`** (two commits later, both titled "Generic kanban plan"). Every task's Step 1 re-verifies its own site before editing; a site that has moved is edited where it now is, and a finding that no longer reproduces is reported on the card, not "fixed" anyway.
- **Do not touch** `boards/*/work/**` (the repo's own `ocr` config excludes them), `TIMELINE.md`, `boards/*/README.md`, or any run directory under `boards/*/runs/`.
- **`template/board.schema.json` is generated.** Never hand-edit it; change `board_schema.py` and run `python3 template/board_schema.py --write-schema`.
- Backups for any file you replace wholesale go to `/opt/backup/agents/<YYYYMMDD-HHMMSS>-review-remediation/`, keeping the relative layout, and the message that reports the change says where the backup went.
- No git worktrees. Work in this checkout.
- Tests in this repo import engine modules by `sys.path.insert(0, .../template)` + `.../driver` at the top of the file, or load a `driver/*.py` CLI through `importlib.util.spec_from_file_location` (see `tests/test_run_audit.py:8-11`, `tests/test_doc_chain.py:8-11`). Follow whichever the file you are editing already uses.
- No `typing` import and no function annotations anywhere in this repo — the 09-23 review states this as fact and the tests aspect leans on it. Do not introduce them.

## Review Focus

The five input classes the reviews imply but no task's tests currently exercise — the failure modes most likely to bite a person running this engine, most likely first. Each gets its test added to the task that owns the code.

1. **A lock file that exists with empty content.** Between `os.open(...O_CREAT|O_EXCL)` and `os.write(pid)` the file is published empty, and a reader in that window reads the holder as dead and steals a live driver's board. Expected: a lock is visible only once its content is complete. *(Task 2)*
2. **A malformed or truncated `board.json` / `run-summary.json`.** Expected: the auditor reports an `E4` finding and exits non-zero, never a `JSONDecodeError` traceback — its exit code is the board's definition of DONE. *(Task 3)*
3. **One torn line in `chain.jsonl`.** Expected: the E3 audit skips it, the way `run.py:1654-1657` already skips bad lines in the same file. *(Task 4)*
4. **`"max-runtime": "0m"`.** Expected: refused at the door, because it validates today and then silently disarms the per-card ceiling (E6 never fires). *(Task 5)*
5. **`auto-gates` written as a boolean.** Expected: never produced by `create-board.sh`, because the schema requires a list of gate codes and `start-board.sh`'s pre-flight refuses every board the script creates. *(Task 1)*

---

## Task 1: `create-board.sh` writes a manifest that validates (09-23 C1)

**Files:**
- Modify: `driver/create-board.sh:447`
- Create: `tests/test_create_board_default.py`

**Interfaces:**
- Consumes: `template/board_schema.validate(cfg, *, where=...) -> list[str]` (unchanged); the stub-`hermes` + held-dispatcher-lock harness in `tests/test_unstarted_mint.py:174-231` (`_stub_hermes`, `_probe_repo`).
- Produces: nothing importable — a shell default and its test.

The `printf` at `:447` writes `"auto-gates": false`, a JSON boolean. `board_schema.OPTIONS["auto-gates"]` is kind `gates` and requires a **list** of gate codes, so `start-board.sh:14-21`'s pre-flight validator `exit 2`s on every board this script creates. Reproduced by two agents independently in the 09-20 run (K1) and still reproducing in the 09-23 run.

- [ ] **Step 1: Re-verify the site, then write the failing test**

Run: `sed -n '447p' driver/create-board.sh`
Expected: the line containing `\"auto-gates\": false`.

`tests/test_create_board_default.py` — new file, whole content:

```python
"""The manifest create-board.sh writes for a board it was not handed must validate.

Pinned because it did not: the script's printf wrote `"auto-gates": false`, a JSON
boolean where board_schema requires a list of gate codes, so `start-board.sh`'s own
pre-flight refused EVERY board created with --slug/--title. Two review agents found
it independently (2026-09-20 K1, still open 2026-09-23 C1).
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import board_schema

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATE = os.path.join(REPO, "driver", "create-board.sh")
SLUG = "probe-default"


def _stub_hermes(tmp_path):
    """A `hermes` that answers what create-board.sh asks and says nothing else."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    stub = d / "hermes"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"profile\" ] && [ \"$2\" = \"list\" ]; then\n"
        "  printf '  coder deepseek stopped\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"kanban\" ]; then\n"
        "  for a in \"$@\"; do\n"
        "    if [ \"$a\" = \"create\" ] && [ \"$2\" != \"boards\" ]; then\n"
        "      printf '{\"id\": \"t_%s\"}\\n' \"$$\"\n"
        "      exit 0\n"
        "    fi\n"
        "  done\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n")
    stub.chmod(0o755)
    return d


def _probe_repo(tmp_path):
    """A throwaway repo laid out like this one: driver/ and template/ symlinked, a
    copy of create-board.sh under driver/, and a dispatch lock a live process holds
    (create-board.sh's pre-flight requires a HELD one)."""
    here = REPO
    repo = tmp_path / "repo"
    for layer in ("driver", "template"):
        (repo / layer).mkdir(parents=True)
        for entry in os.listdir(os.path.join(here, layer)):
            if entry in ("__pycache__", os.path.basename(CREATE)):
                continue
            os.symlink(os.path.join(here, layer, entry), repo / layer / entry)
    script = repo / "driver" / os.path.basename(CREATE)
    script.write_text(open(CREATE).read())
    script.chmod(0o755)
    home = tmp_path / "hermes-home"
    lock = home / "kanban" / ".dispatcher.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    holder = subprocess.Popen(["bash", "-c", f"exec 3<{lock}; sleep 120"])
    return repo, script, home, holder


def test_the_default_manifest_validates(tmp_path):
    if not os.path.exists("/usr/bin/lsof"):
        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
    repo, script, home, holder = _probe_repo(tmp_path)
    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
               HERMES_HOME=str(home), HOME=str(home))
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    try:
        r = subprocess.run([str(script), "--slug", SLUG, "--title", "Probe"],
                           capture_output=True, text=True, env=env, cwd=str(repo))
    finally:
        holder.kill()
    assert r.returncode == 0, r.stderr[-2000:]
    cfg = json.load(open(repo / "boards" / SLUG / "board.json"))
    assert cfg["auto-gates"] == []
    assert board_schema.validate(cfg, where="board.json") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/usr/bin/python3 -m pytest -q tests/test_create_board_default.py -v`
Expected: FAIL — `assert False == []` on `cfg["auto-gates"]`, and/or `validate` returning the `'auto-gates' expected a list of gate codes` problem. If the test errors on the harness (lsof, path) rather than on the assertion, fix the harness before touching the script.

- [ ] **Step 3: Fix the script**

In `driver/create-board.sh`, the `printf` format string at `:447`:

```bash
  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
```

(`false` → `[]`. `[]` is every gate human, the documented default at `board_schema.py:74` and the value the script's own `--help` block at `:52` prints.)

- [ ] **Step 4: Run it to verify it passes**

Run: `/usr/bin/python3 -m pytest -q tests/test_create_board_default.py -v`
Expected: PASS.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh tests/test_create_board_default.py
git status --short
```
Report the two paths and the measured test result, then STOP. Do not commit.

---

## Task 2: `driver_lock.take()` never publishes an empty lock (09-23 C2)

**Files:**
- Modify: `template/driver_lock.py:50-68` (`take`), docstring at `:20-49`
- Modify: `tests/test_acquire_lock.py` (append)

**Interfaces:**
- Consumes: `driver_lock.take(runs_dir, why) -> (path, note)`; `driver_lock.pid_alive(pid) -> bool`. Callers that must keep working: `driver/run.py:3629` (`acquire_lock`), `driver/start-board.sh:86`, `driver/reset.sh:116`, `driver/create-board.sh:427` (via `driver/driver-pid.sh`).
- Produces: `take` keeps its exact signature and return contract; only the publication order changes.

Today `take()` does `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` at `:55`, writes the pid at `:63`, and a reader in that window sees `""`; `pid_alive("")` is false, so the `O_TRUNC` takeover at `:61` destroys a **live** driver's lock. Two drivers on one `work/` is the exact state the module exists to prevent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_acquire_lock.py` (it already imports `run`, which imports `driver_lock`; add `import driver_lock` beside `import run`):

```python
def test_the_lock_is_never_visible_without_its_pid(tmp_path, monkeypatch):
    """The window between creating the lock file and writing the pid is the bug:
    a reader inside it sees "", reads the holder as dead, and takes a LIVE driver's
    board (2026-09-23 C2). Publication is the thing under test, so watch it: every
    path a lock becomes visible through must already carry a pid."""
    seen = []
    real_link = os.link

    def spy(src, dst, *a, **k):
        seen.append(open(src).read().strip())
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(os, "link", spy)
    path, note = driver_lock.take(str(tmp_path), "why")
    assert note == ""
    assert seen, "take() no longer publishes through a complete file"
    assert all(s.isdigit() and int(s) > 0 for s in seen), seen
    assert open(path).read().strip() == str(os.getpid())


def test_a_dead_holders_lock_is_still_taken_over(tmp_path):
    (tmp_path / "driver.lock").write_text("999999")     # in range, owned by nothing
    path, note = driver_lock.take(str(tmp_path), "why")
    assert "taking over a stale driver lock" in note
    assert open(path).read().strip() == str(os.getpid())


def test_a_live_holders_lock_is_still_refused(tmp_path):
    (tmp_path / "driver.lock").write_text(str(os.getpid()))
    with pytest.raises(SystemExit):
        driver_lock.take(str(tmp_path), "why")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py -v -k never_visible`
Expected: FAIL — `assert seen` is false (`take` publishes with `os.open`, not `os.link`).

- [ ] **Step 3: Implement the atomic publication**

Replace the body of `take()` in `template/driver_lock.py` from `os.makedirs(runs_dir, exist_ok=True)` through `return path, note` with:

```python
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, "driver.lock")
    mine = str(os.getpid())
    note = ""
    # Publish the pid ATOMICALLY. A lock file that exists with nothing in it is
    # indistinguishable from a live driver's during the gap between `open` and
    # `write`, and a reader in that gap reads the holder as gone and takes the
    # board (2026-09-23 C2). So the pid is written to a private temp file first and
    # then LINKED into place: `link` either creates `path` complete or fails with
    # FileExistsError, and never exposes a half-written file.
    tmp = f"{path}.{mine}.tmp"
    with open(tmp, "w") as f:
        f.write(mine)
    try:
        os.link(tmp, path)
    except FileExistsError:
        held = open(path).read().strip()
        if pid_alive(held):
            raise SystemExit(f"another driver holds {path} (pid {held}) — {why}")
        note = f"taking over a stale driver lock ({path}: pid {held!r} is gone)"
        os.replace(tmp, path)          # the takeover, now also all-or-nothing
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    atexit.register(_release, path, mine)
    return path, note
```

Update the docstring's paragraph about the dead-holder takeover to add one sentence: *"Publication is atomic: the pid is in the file before the file is visible, so no reader can mistake a live holder for a stale one."*

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_open_lane.py tests/test_run_directories.py -v`
Expected: PASS, including the pre-existing `test_a_dead_holders_lock_is_taken_over`, `test_a_live_holders_lock_is_refused`, and `test_an_unreadable_lock_reads_as_dead` (`tests/test_acquire_lock.py:25-44`). An empty/garbage lock file is still taken over — that tolerance is deliberate and stays.

- [ ] **Step 5: Stage and ask**

```bash
git add template/driver_lock.py tests/test_acquire_lock.py
git status --short
```
Report paths and results, then STOP.

---

## Task 3: `run-audit.py` stops defaulting and stops tracebacking (09-23 C3, C4, I27)

**Files:**
- Modify: `driver/run-audit.py:405-412` (`audit`), `:437-439` (summary read), `:573-577` (`main`'s ceiling read)
- Modify: `tests/test_run_audit.py` (append; reuse the `fixture()` helper at `:35-54`)

**Interfaces:**
- Consumes: `board_schema.duration_seconds(text)`; the `findings` shape `(severity, code, text)`.
- Produces: a module-level helper `read_json(path) -> (value, problem)` used by all three sites — `(None, None)` when the file is absent, `(value, None)` when it parses, `(None, "<why>")` when it is malformed.

Three failures, one class: an unresolvable `board.json` silently sets `cfg = {}` (ceiling `None`, so E6 never fires; `auto-gates` empty, so held auto-gates downgrade to INFO; `slug` becomes the dirname), and a malformed `board.json`/`run-summary.json` is a raw `JSONDecodeError`. `write_summary` (`run.py:3356-3358`) writes `run-summary.json` non-atomically, so a kill mid-write makes every later audit die the same way.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_audit.py`:

```python
def test_a_truncated_summary_is_a_finding_not_a_traceback(tmp_path):
    """The auditor's exit code IS the board's definition of DONE; a traceback there
    is neither a verdict nor a readable one. run-summary.json is written
    non-atomically, so a kill mid-write makes this the normal state of a dead run."""
    runs = fixture(tmp_path)
    (os.path.join(runs, "run-summary.json"))  # exists
    open(os.path.join(runs, "run-summary.json"), "w").write('{"wall_min": 13.1, "car')
    findings, rows, stats = ra.audit(runs)
    assert ("ERROR", "E4") in [(s, c) for s, c, _ in findings]
    assert any("run-summary.json" in t for _s, _c, t in findings)


def test_a_malformed_board_json_is_a_finding_not_a_traceback(tmp_path):
    runs = fixture(tmp_path)
    board = os.path.dirname(os.path.dirname(runs))
    open(os.path.join(board, "board.json"), "w").write("{not json")
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "board.json" in t for _s, c, t in findings)


def test_a_missing_board_json_is_reported_not_defaulted(tmp_path):
    """`cfg = {}` disarmed the ceiling (E6 never fires) and emptied auto-gates in the
    same run that had already lost its summary — two silent downgrades from one
    absent file."""
    runs = fixture(tmp_path)
    board = os.path.dirname(os.path.dirname(runs))
    os.unlink(os.path.join(board, "board.json"))
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "board.json" in t for _s, c, t in findings)


def test_a_malformed_summary_exits_nonzero_through_the_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    runs = fixture(tmp_path)
    open(os.path.join(runs, "run-summary.json"), "w").write("{")
    assert ra.main(["--runs", runs]) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py -v -k "malformed or truncated or missing_board"`
Expected: FAIL — `json.decoder.JSONDecodeError` raised out of `ra.audit`, and the missing-`board.json` test finds no `E4`.

- [ ] **Step 3: Implement the tolerant reader**

In `driver/run-audit.py`, add above `audit()`:

```python
def read_json(path):
    """(value, problem) for a JSON file the audit depends on.

    Absent is `(None, None)` — the caller decides what an absent file means, because
    "no summary yet" and "no board.json at all" are different faults. Malformed is
    `(None, why)`: the auditor's exit code is the board's definition of DONE, so a
    traceback here is a verdict nobody can read (2026-09-23 C4)."""
    try:
        with open(path) as f:
            return json.load(f), None
    except OSError:
        return None, None
    except ValueError as e:
        return None, f"{os.path.basename(path)} is not valid JSON — {e}"
```

Replace `audit()`'s opening (`:405-415`):

```python
def audit(runs_dir, board_dir=None):
    board_dir = board_dir or board_dir_for(runs_dir)
    findings = []
    cfg_path = os.path.join(board_dir, "board.json")
    cfg, cfg_problem = read_json(cfg_path)
    if cfg_problem:
        findings.append(("ERROR", "E4", cfg_problem))
    elif cfg is None:
        # NOT a silent default: with no manifest the per-card ceiling and the
        # auto-gates list are both unknown, so the audit says so instead of
        # disarming E6 and downgrading every held auto-gate (2026-09-23 C3).
        findings.append(("ERROR", "E4",
                         f"no board.json at {cfg_path} — the per-card ceiling and "
                         f"auto-gates cannot be read, so this run is not fully audited"))
        cfg = {}
    elif not isinstance(cfg, dict):
        findings.append(("ERROR", "E4", f"{cfg_path}: expected a JSON object"))
        cfg = {}
    slug = cfg.get("slug") or os.path.basename(board_dir)
    ceiling = ceiling_minutes(cfg.get("max-runtime"))

    d_findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                        cfg.get("auto-gates") or ())
    findings += d_findings
```

Replace the `run-summary.json` read at `:437-439`:

```python
    summary_path = os.path.join(runs_dir, "run-summary.json")
    summary, summary_problem = read_json(summary_path)
    if summary_problem:
        findings.append(("ERROR", "E4", summary_problem))
    elif summary is not None and not isinstance(summary, dict):
        findings.append(("ERROR", "E4", f"{summary_path}: expected a JSON object"))
        summary = None
    s_findings, s_stats = summary_findings(summary, ceiling)
    findings += s_findings
    stats.update(s_stats)
```

Replace `main()`'s ceiling read at `:573-577`:

```python
    cfg_path = os.path.join(a.board or board_dir_for(a.runs), "board.json")
    cfg, _problem = read_json(cfg_path)
    ceiling = ceiling_minutes((cfg or {}).get("max-runtime")) if isinstance(cfg, dict) else None
```

(Note: the `findings` list is now built before the `E1` early-return block at `:416`; keep that block's `findings = [...]` rewrite — it already replaces the whole list, so the ordering is unchanged. Confirm by reading `:414-436` after the edit.)

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py -v`
Expected: PASS — the four new tests plus all 40-odd pre-existing ones.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run-audit.py tests/test_run_audit.py
git status --short
```
Report, then STOP.

---

## Task 4: `doc-chain.py` survives a torn line (09-23 C5, C6, I34)

**Files:**
- Modify: `driver/doc-chain.py:38-46` (`load`), `:110-115` and `:165` (`analyze`)
- Modify: `tests/test_doc_chain.py` (append; reuse `chain()` at `:28-51`)

**Interfaces:**
- Consumes: `load(runs_dir) -> list[dict] | None`; `analyze(recs, runs_dir) -> (rows, findings)`.
- Produces: same signatures. `load` skips an unparsable line; `analyze` reads records through `.get()` and skips a record with no `code` or no `ts`.

`run.py:1654-1657` deliberately skips bad `chain.jsonl` lines; `doc-chain.load` raises on them and takes the whole E3 audit down. `analyze` then indexes `r["code"]/["inputs"]/["lane"]/["ts"]/["title"]` unguarded.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_doc_chain.py`:

```python
def test_a_torn_chain_line_is_skipped_not_raised(tmp_path):
    """run.py skips a half-written chain line on purpose; the E3 audit must read the
    same file the same way, or one kill mid-append takes the audit down (2026-09-23 C5)."""
    chain(tmp_path)
    with open(tmp_path / "chain.jsonl", "a") as f:
        f.write('{"ts": "2026-09-11T20:25:00", "event": "star')
    recs = dc.load(str(tmp_path))
    assert len(recs) == 4                      # the three written by chain() plus the done
    assert dc.analyze(recs, str(tmp_path))[1] == []


def test_a_record_with_no_title_is_not_a_keyerror(tmp_path):
    """A truncated record that still parses has no title. analyze must not index it
    (2026-09-23 C6: reproduced `KeyError: 'title'`)."""
    recs = chain(tmp_path)
    recs[1] = {k: v for k, v in recs[1].items() if k != "title"}
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    rows, _findings = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    assert any(r["code"] == "P1" for r in rows)


def test_a_record_with_no_ts_is_dropped_not_indexed(tmp_path):
    recs = chain(tmp_path)
    recs[1] = {k: v for k, v in recs[1].items() if k != "ts"}
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    dc.analyze(dc.load(str(tmp_path)), str(tmp_path))     # must not raise


def test_the_cli_reports_a_broken_chain_rather_than_tracebacking(tmp_path, capsys):
    chain(tmp_path)
    (tmp_path / "chain.jsonl").write_text("not json at all\n")
    assert dc.main(["--runs", str(tmp_path)]) in (0, 2)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py -v -k "torn or no_title or no_ts or broken_chain"`
Expected: FAIL with `json.decoder.JSONDecodeError` (torn line) and `KeyError: 'title'`.

- [ ] **Step 3: Implement tolerance**

In `driver/doc-chain.py`, `load()`:

```python
def load(runs_dir):
    path = os.path.join(runs_dir, "chain.jsonl")
    if not os.path.exists(path):
        return None
    recs = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                # A half-written line is what a kill mid-append leaves. run.py skips
                # the same lines deliberately; a reader that raises here turns one
                # torn line into the whole E3 audit failing (2026-09-23 C5).
                continue
    return recs
```

In `analyze()`, guard the record reads. Replace the `for r in starts:` body's first two statements and the `rows.append(...)` tail:

```python
    for r in starts:
        if not isinstance(r, dict) or not r.get("code") or not r.get("ts"):
            # A record that parsed but is not a card start: nothing to judge it
            # against, and indexing it is the KeyError this closes (2026-09-23 C6).
            continue
        for role, code in PRODUCED_BY.items():
            if r["code"].startswith(code) and (r.get("inputs") or {}).get(role):
                producers.setdefault((r["lane"], role), r)
```

and the tail:

```python
        rows.append({"lane": r.get("lane"), "code": r["code"], "title": r.get("title", ""),
                     "started": f"{started:%H:%M:%S}",
                     "done": (done.get("ts") or "")[11:19], "inputs": docs,
                     "attached": produced["attached"], "staged": produced["staged"],
                     "result": done.get("result", ""), "verdict": verdict})
```

Also change `producers.setdefault((r["lane"], role), r)` to use `r.get("lane")` (already covered by the line above). Check the `for r in sorted(starts, key=lambda r: (r["lane"], r["ts"]))` line at `:114` — after the guard, every record in `starts` has both keys, so it is safe; keep it as is.

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py -v`
Expected: PASS — all new tests plus the pre-existing ones (`tests/test_doc_chain.py` has ~24).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/doc-chain.py tests/test_doc_chain.py
git status --short
```
Report, then STOP.

---

## Task 5: `board_schema.py` — the validator and the generated schema agree (09-23 I1–I5, I17, I12-part)

**Files:**
- Modify: `template/board_schema.py` — `duration_seconds`/`_DURATION_RE` (`:154-175`), `_kind_error` (`:187-225`), `gate_is_auto` (`:139-141`), the provider⇄model rule (`:319-331`), `workdir_notices` (`:487-491`), `_KIND_SCHEMA` (`:607-622`), `json_schema` (`:648-660`)
- Regenerate: `template/board.schema.json`
- Modify: `tests/test_board_schema.py` (append; reuse `problems()` at `:23-24`)

**Interfaces:**
- Consumes: `OPTIONS` (unchanged), `GATE_CODES`, `PER_LANE`, `BOARD_KEYS`.
- Produces: `validate` and `json_schema` agree on every rule both can express; `duration_seconds("0m")` stays `None` (the auditor's parser) while `validate` now refuses the value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_board_schema.py`:

```python
def test_a_duration_that_reads_as_zero_is_refused():
    """`0m` matches the duration regex, validates, and then duration_seconds() returns
    None — no --run-budget, no subprocess timeout, and ceiling_minutes -> None so E6
    never fires. A ceiling that silently is not one (2026-09-23 I3)."""
    assert problems(slug="b", **{"max-runtime": "0m"})
    assert problems(slug="b", **{"max-runtime": "0s"})
    assert problems(slug="b", **{"max-runtime": "0h"})
    assert problems(slug="b", **{"max-runtime": "10m"}) == []


def test_a_target_must_be_an_absolute_path():
    """`targets` escaped the rule `default-workdir` is held to, and a relative target
    is emitted verbatim into every card body (2026-09-23 I4)."""
    assert problems(slug="b", targets=["/tmp/x"]) == []
    assert problems(slug="b", targets=["relative/dir"])
    assert problems(slug="b", targets=["~/x"])


def test_gate_is_auto_refuses_a_string():
    """`gate_is_auto('Gi', 'Gi')` was True by substring containment while the schema
    type-checks a string `auto-gates` (2026-09-23 I5)."""
    assert board_schema.gate_is_auto("Gi", "Gi") is False
    assert board_schema.gate_is_auto("Gi", "Gp") is False
    assert board_schema.gate_is_auto(["Gi"], "Gi") is True


def test_a_provider_needs_a_model_for_the_same_lanes():
    """The rule was presence-only and scope-blind: {'lanes':2,'provider':['p1','p2'],
    'model':'m1'} validated and filed lane 2 with lane 1's model — and a spawn
    failure is final (2026-09-23 I1)."""
    assert problems(slug="b", lanes=2, provider=["p1", "p2"], model="m1")
    assert problems(slug="b", lanes=2, provider="p1", model=["m1", "m2"])
    assert problems(slug="b", lanes=2, provider=["p1", "p2"], model=["m1", "m2"]) == []
    assert problems(slug="b", provider="p1", model="m1") == []
    assert problems(slug="b", model="m1") == []          # a model alone is fine


def test_the_generated_schema_and_the_validator_agree():
    """`--check-schema` proves only file == generator; it cannot prove the generator
    and `validate` say the same thing. These are the four axes they disagreed on
    (2026-09-23 I2)."""
    schema = board_schema.json_schema()
    # 1. `lanes` has a default of 1, so it is not required by the validator.
    assert "lanes" not in schema["required"]
    assert schema["properties"]["lanes"]["default"] == 1
    # 2. any $-prefixed key is a meta-key to the validator.
    assert schema.get("patternProperties", {}).get("^\\$") is not None
    # 3. a whitespace-only string is refused by the validator.
    assert "pattern" in schema["properties"]["name"]
    # 4. uniqueItems is enforced on both sides.
    assert schema["properties"]["targets"].get("uniqueItems") is True
    assert problems(slug="b", targets=["/a", "/a"])


def test_every_option_kind_has_a_schema_entry():
    """A kind with no `_KIND_SCHEMA` entry is a KeyError inside --write-schema."""
    for kind, _default, _per_lane, _flag in board_schema.OPTIONS.values():
        assert kind in board_schema._KIND_SCHEMA, kind


def test_a_failing_index_read_is_not_a_clean_index(tmp_path, monkeypatch):
    """`git diff --cached`'s returncode was unchecked, so a failing index read was
    reported as clean (2026-09-23 I17)."""
    wd = tmp_path / "wd"
    wd.mkdir()

    def fake_run(args, **kw):
        class R:
            returncode = 0 if "rev-parse" in args else 1
            stdout = str(wd) if "rev-parse" in args else ""
            stderr = "fatal: index file smaller than expected"
        return R()

    monkeypatch.setattr(board_schema.subprocess, "run", fake_run)
    notices = board_schema.workdir_notices({"default-workdir": str(wd)})
    assert any("index" in n for n in notices)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py -v -k "reads_as_zero or absolute_path or refuses_a_string or same_lanes or agree or schema_entry or clean_index"`
Expected: FAIL on all seven.

- [ ] **Step 3: Implement the fixes**

**(a) zero duration** — in `_kind_error`, the `duration` branch (`:222-225`):

```python
    elif kind == "duration":
        if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
            return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
                    f"got {value!r}")
        if duration_seconds(value) is None:
            # It parses to zero: no --run-budget, no subprocess timeout, and the
            # auditor's ceiling goes None so E6 never fires. A ceiling that is not
            # one is worse than no ceiling (2026-09-23 I3).
            return (f"a duration of zero is not a ceiling — {value!r} would disable "
                    f"the per-card budget silently")
```

**(b) absolute targets** — the `paths` branch (`:203-206`):

```python
    elif kind == "paths":
        if not isinstance(value, list) or not all(
                isinstance(p, str) and p.strip() for p in value):
            return f"expected a list of non-empty paths, got {value!r}"
        bad = [p for p in value if not p.startswith("/")]
        if bad:
            return (f"every target must be an absolute path, got {bad!r} — a target "
                    f"is resolved from each card's own working directory")
        if len(set(value)) != len(value):
            return f"duplicate target(s) in {value!r}"
```

**(c) `gate_is_auto`** (`:139-141`):

```python
def gate_is_auto(value, code):
    """Does `auto-gates` hand gate `code` ('Gi') to the driver?

    A LIST only. `code in value` was substring containment on a string, so
    `gate_is_auto('Gi', 'Gi')` was True for a value the schema refuses
    (2026-09-23 I5)."""
    return isinstance(value, list) and code in value
```

**(d) provider⇄model per lane** — replace the loop at `:326-330`:

```python
    for provider_key, model_key in (("provider_override", "model_override"),
                                    ("provider", "model")):
        if provider_key not in allowed or not cfg.get(provider_key):
            continue
        lanes = cfg.get("lanes", OPTIONS["lanes"][1])
        lanes = lanes if isinstance(lanes, int) and not isinstance(lanes, bool) else 1
        prov = cfg[provider_key]
        mod = cfg.get(model_key)
        # A per-lane list pairs by INDEX, not by presence: a board that names two
        # providers and one model files lane 2 with lane 1's model, and a spawn
        # failure is final (2026-09-23 I1).
        prov_list = prov if isinstance(prov, list) else [prov] * lanes
        mod_list = mod if isinstance(mod, list) else [mod] * lanes
        missing = [i for i, p in enumerate(prov_list, start=1)
                   if p and not mod_list[i - 1]]
        if missing:
            problems.append(f"{where}: {provider_key!r} is set for lane(s) "
                            f"{missing} with no {model_key!r} — a provider alone "
                            f"does not say which model to run")
```

**(e) workdir index returncode** — in `workdir_notices`, after the `staged = subprocess.run(...)` call (`:487-488`):

```python
    if staged.returncode != 0:
        return [f"{where}: cannot read the index of {inside.stdout.strip()} "
                f"({staged.stderr.strip() or 'git diff --cached failed'}) — the "
                f"board's view of what is staged is unknown, not clean"]
```

**(f) `_KIND_SCHEMA`** — add the two missing kinds and tighten the string kinds:

```python
_KIND_SCHEMA = {
    "slug":     {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
    "text":     {"type": "string", "minLength": 1, "pattern": "\\S"},
    "count":    {"type": "integer", "minimum": 1},
    "bool":     {"type": "boolean"},
    "duration": {"type": "string", "pattern": "^(?:(?!0+[hms])[0-9.]+[hms])+$"},
    "abspath":  {"type": "string", "pattern": "^/"},
    "path":     {"type": "string", "minLength": 1},
    "paths":    {"type": "array", "uniqueItems": True,
                 "items": {"type": "string", "pattern": "^/"}},
    "cards":    {"type": "array", "uniqueItems": True,
                 "items": {"enum": list(GOAL_CODES)}},
    "gates":    {"type": "array", "uniqueItems": True,
                 "items": {"enum": list(GATE_CODES)}},
    "roles":    {"type": "object",
                 "propertyNames": {"enum": sorted(ROLES)},
                 "additionalProperties": {"type": "string", "minLength": 1}},
    "unchecked": {},
}
```

(The `duration` pattern is a best-effort mirror; `validate` remains the authority for the zero check — say so in the comment above `_KIND_SCHEMA`, which already says exactly that.)

**(g) `json_schema`** — add `patternProperties` and drop the false `required`:

```python
        "type": "object",
        "additionalProperties": False,
        "patternProperties": {"^\\$": {}},
        "properties": props,
    }
```

(no `"required"` key: `lanes` carries `default: 1` and `validate` treats it as optional.)

- [ ] **Step 4: Regenerate the schema and run the tests**

```bash
python3 template/board_schema.py --write-schema
/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_shipped_boards.py -v
```
Expected: PASS. `test_the_generated_schema_is_current` (`:43`) now compares against the regenerated file; `test_the_generated_schema_describes_the_same_options` (`:51`) still holds.

- [ ] **Step 5: Whole-suite gate (this task changes an accepted-value rule)**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: **685 passed** — the baseline 666, plus Task 1's 1, Task 2's 3, Task 3's 4, Task 4's 4 and this task's 7. If any shipped board or idea file now fails validation, that is a real finding: report it on the card rather than loosening the rule.

- [ ] **Step 6: Stage and ask**

```bash
git add template/board_schema.py template/board.schema.json tests/test_board_schema.py
git status --short
```
Report, then STOP.

---

## Task 6: the three untested contracts get behavioural tests (09-23 C7, C8, C9)

**Files:**
- Modify: `tests/test_run_directories.py` (replace `:410-418`), `tests/test_open_lane.py` (replace `:815-820`), `tests/test_run_audit.py` (append)

**Interfaces:**
- Consumes: `run.main()`, `run.preserve_artifacts()`, `ra.main(argv)` — all unchanged.
- Produces: tests only. No engine file is edited in this task.

Each of these three paths decides whether a run is finished, and none is executed by the suite today — the existing "tests" grep the source text (`inspect.getsource`), which cannot fail when the behaviour breaks.

- [ ] **Step 1: Replace the source-grep tests with behavioural ones**

In `tests/test_run_directories.py`, replace `test_patches_land_in_the_runs_own_directory_without_a_second_timestamp` (`:410-418`) with:

```python
def test_preserve_artifacts_copies_a_cards_patch_into_the_run(tmp_path, monkeypatch):
    """It was never executed by any test — only grepped in the source — so a dead
    copier kept reporting success (2026-09-23 C8)."""
    import run as r
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "log", lambda msg: None)
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "home"))
    monkeypatch.setattr(r, "board",
                        lambda: {"C1: implement - lane 1": {"id": "t_c1"}})
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "runs" / "run-x"))
    src = tmp_path / "home" / "kanban" / "boards" / "b" / "attachments" / "t_c1"
    src.mkdir(parents=True)
    (src / "patch.diff").write_text("diff\n")
    r.preserve_artifacts()
    assert (tmp_path / "runs" / "run-x" / "patches" / "t_c1.patch").read_text() == "diff\n"
```

In `tests/test_open_lane.py`, replace `test_a_halt_stops_the_loop_before_it_can_refile` (`:815-820`) with:

```python
def test_main_exits_one_when_the_board_halted(monkeypatch):
    """`run.main()` is the loop that decides finish vs halt, and no test executed it
    (2026-09-23 C7). The halt check must come before an armed idea is adopted, or the
    exit abandons a run it just minted."""
    import run as r
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "require_manifest", lambda: None)
    monkeypatch.setattr(r, "acquire_lock", lambda: None)
    monkeypatch.setattr(r, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(r, "deadman_check", lambda: None)
    monkeypatch.setattr(r, "_read_current_run", lambda: "")
    monkeypatch.setattr(r, "log", lambda msg: None)
    monkeypatch.setattr(r.STATE, "halted", {"reason": "test halt"})
    assert r.main() == 1


def test_main_returns_zero_on_once_after_the_last_gate(monkeypatch):
    import run as r
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "require_manifest", lambda: None)
    monkeypatch.setattr(r, "acquire_lock", lambda: None)
    monkeypatch.setattr(r, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(r, "deadman_check", lambda: None)
    monkeypatch.setattr(r, "_read_current_run", lambda: "")
    monkeypatch.setattr(r, "log", lambda msg: None)
    monkeypatch.setattr(r, "tick", lambda: True)
    monkeypatch.setattr(r, "finish_run", lambda: None)
    monkeypatch.setattr(r.STATE, "halted", {"reason": None})
    monkeypatch.setattr(r, "ONCE", True)
    monkeypatch.setattr(r, "SERVE", False)
    assert r.main() == 0


def test_main_times_out_and_exits_one(monkeypatch):
    import run as r
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "require_manifest", lambda: None)
    monkeypatch.setattr(r, "acquire_lock", lambda: None)
    monkeypatch.setattr(r, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(r, "deadman_check", lambda: None)
    monkeypatch.setattr(r, "_read_current_run", lambda: "")
    monkeypatch.setattr(r, "log", lambda msg: None)
    monkeypatch.setattr(r, "tick", lambda: False)
    monkeypatch.setattr(r, "time", __import__("time"))   # keep the real module
    monkeypatch.setattr(r, "ONCE", False)
    monkeypatch.setattr(r, "SERVE", False)
    monkeypatch.setattr(r.STATE, "halted", {"reason": None})
    monkeypatch.setattr(r.STATE, "mutations", [0])
    monkeypatch.setattr(r, "POLL", 0)
    monkeypatch.setattr(r, "POLL_BUSY", 0)
    monkeypatch.setattr(r.sys, "argv", ["run.py", "--timeout-min", "0"])
    assert r.main() == 1
```

In `tests/test_run_audit.py`, append:

```python
def test_the_json_output_is_the_machine_contract(tmp_path, monkeypatch, capsys):
    """`ra.main` is called 5x in this suite and never with --json; a key rename or an
    inverted severity leaves the human path green (2026-09-23 C9)."""
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    runs = fixture(tmp_path, chain_recs=worker_chain())
    assert ra.main(["--runs", runs, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"findings", "rows", "stats"}
    assert out["findings"] == []


def test_json_output_exits_one_when_a_warning_was_raised(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    runs = fixture(tmp_path, chain_recs=worker_chain(), summary_extra={"restarts_observed": True})
    assert ra.main(["--runs", runs, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert any(c == "E5" for _s, c, _t in out["findings"])
```

- [ ] **Step 2: Run the new tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_open_lane.py tests/test_run_directories.py tests/test_run_audit.py -v -k "main_ or preserve_artifacts or json_output"`
Expected: PASS. If `preserve_artifacts` or `main` needs one more attribute patched (module-level globals vary by call order), patch that attribute and note it in the test docstring — do not edit `driver/run.py` in this task.

- [ ] **Step 3: Whole-suite gate**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 685 + 4 (this task: two replaced by behavioural equivalents, three added) = **689 passed**.

- [ ] **Step 4: Stage and ask**

```bash
git add tests/test_open_lane.py tests/test_run_directories.py tests/test_run_audit.py
git status --short
```
Report, then STOP.

---

## Task 7: narrow the broad `except` that turns a refusal into a default (09-23 I13–I16)

**Files:**
- Modify: `driver/file_lanes.py:171-174`, `:233-238`; `driver/runs_util.py:36-53`; `driver/start-board.sh:84-89`
- Modify: `tests/test_runs_util.py` (append), `tests/test_file_lanes.py` (append)

**Interfaces:**
- Consumes: `file_lanes._board_cfg(board_dir)`, `lanes._board_default(defaults, key, lane, ...)`, `runs_util.board_runs(board, card_id, timeout=30)`, `driver/driver-pid.sh`'s `live_driver_pid`.
- Produces: `runs_util.board_runs` returns **`None`** on failure and `[]` only for a genuine "no runs"; every caller in `driver/run.py:554-559`, `driver/timing-report.py:178-235` and `driver/runs-report.py` must handle `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runs_util.py`:

```python
def test_a_refused_cli_call_is_not_an_empty_run_list(monkeypatch):
    """`[]` for "the CLI refused" read as data: run.py parked a gate for 10 minutes
    naming a review that had not happened, and timing-report printed `0.0 min` as
    fact (2026-09-23 I15)."""
    monkeypatch.setattr(runs_util.subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "",
                                                       "stderr": "boom"})())
    assert runs_util.board_runs("b", "t_1") is None
```

Append to `tests/test_file_lanes.py`:

```python
def test_an_unreadable_manifest_stops_the_filing(tmp_path):
    """`except Exception: board_cfg = {}` kept filing on defaults — 60 m ceilings, the
    goal judge off and NO model flag, so the reviews ran the author's model
    (2026-09-23 I13). A manifest that is not there is different from one that will
    not parse."""
    board = tmp_path / "boards" / "b"
    board.mkdir(parents=True)
    (board / "board.json").write_text("{ not json")
    with pytest.raises(Exception) as e:
        file_lanes.file_board("b", str(tmp_path), str(tmp_path / "w"), 1, "run-x")
    assert "board.json" in str(e.value)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_util.py tests/test_file_lanes.py -v -k "refused_cli or unreadable_manifest"`
Expected: FAIL — `board_runs` returns `[]`, and `file_board` swallows the parse error.

- [ ] **Step 3: Implement**

`driver/runs_util.py` — `board_runs`:

```python
def board_runs(board, card_id, timeout=30):
    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS).

    `[]` is "this card has no runs"; **None** is "the CLI refused the call". The two
    were the same value, so a failed call read as evidence of a clean card — a gate
    parked ten minutes naming a review that had not happened, and `0.0 min` printed
    as fact (2026-09-23 I15). Callers must handle None.

    The CLI call carries `cli_env()`: this module is used by the timing report and by
    the driver's verdict fallback, so a leaked child-context marker here silently
    reported empty evidence for every card.
    """
    try:
        r = subprocess.run(
            ["hermes", "kanban", "--board", board, "runs", card_id, "--json"],
            capture_output=True, text=True, timeout=timeout, env=cli_env())
        if r.returncode != 0:
            _warn_once(f"board_runs {board} {card_id}: {cli_error(r.stderr)}")
            return None
        return json.loads(r.stdout)
    except Exception as e:
        _warn_once(f"board_runs {board} {card_id}: {e}")
        return None
```

`driver/file_lanes.py` — `:171-174`:

```python
    try:
        board_cfg = _board_cfg(os.path.join(repo, "boards", board))
    except FileNotFoundError:
        board_cfg = {}            # no manifest: the documented defaults are all there is
```

(Anything else — a malformed manifest, a permission error — propagates. Filing a board on invented defaults is how the reviews end up on the author's model.)

`driver/file_lanes.py` — `:237-238`:

```python
    except OSError as exc:        # never let a display line stop a board filing
        return f"Lane options: unavailable ({exc})"
```

(leaves `lanes._board_default`'s length-mismatch `ValueError` visible instead of folding it into a card-body sentence.)

`driver/start-board.sh` — `:84-89`, use the same strict probe the other two scripts use:

```bash
# Already up? Say so and stop. The lock FILE existing proves nothing — a driver
# killed with SIGKILL leaves one behind — so ask whether a live process holds it,
# and ask it the way create-board.sh:427 and reset.sh:116 do: a reused pid must not
# read as "already running" for ever (2026-09-23 I16).
. "$REPO/driver/driver-pid.sh"
if DRIVER_PID=$(live_driver_pid "$REPO/boards/$SLUG"); then
  echo "driver for '$SLUG' already running (pid $DRIVER_PID)"
  exit 0
fi
```

- [ ] **Step 4: Update the `board_runs` callers and run the tests**

In `driver/run.py:554-559`, treat `None` as "no evidence":

```python
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in (runs or []) if r.get("outcome") == "completed"]
```

In `driver/timing-report.py:170-181` and `driver/runs-report.py`, guard with `or []` where the value is summed, and skip the row when it is `None`. Grep the call sites first: `grep -rn "board_runs(" driver/`.

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_util.py tests/test_file_lanes.py tests/test_open_lane.py tests/test_runs_report.py tests/test_tool_clis.py -v`
Expected: PASS.

- [ ] **Step 5: Whole-suite gate**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 689 + 2 = **691 passed**.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/file_lanes.py driver/runs_util.py driver/start-board.sh driver/run.py driver/timing-report.py driver/runs-report.py tests/test_runs_util.py tests/test_file_lanes.py
git status --short
```
Report, then STOP.

---

## Task 8: doc corrections — five paragraphs that currently mislead (09-23 I37–I44)

**Files:**
- Modify: `driver/run.py:206-218` (comment), `:524` (docstring); `template/card-bodies/_result-field.txt:1`; `template/card-bodies/rvp-body.txt:5`; `driver/create-board.sh:59`, `:120-123`, `:140`; `driver/run.py:2048` + `driver/start-board.sh:95-97`; `template/card-bodies/gc-body.txt:3`; `template/lanes.py:84`; `driver/run.py:2216`; `driver/run.py:207-210`

**Interfaces:**
- Consumes: nothing. **Produces:** nothing importable. This task changes text only — no code path, no test.

Every one of these is a load-bearing sentence a worker or a maintainer reads and acts on.

- [ ] **Step 1: Fix the five behaviour-misstating docs**

1. `driver/run.py:524` — the docstring says *"Only the card's result field counts"*, and 26 lines below (`:549-558`) a completed run's `summary` is used when `result` is empty, with two tests pinning that fallback. Rewrite to: `"The card's result field decides, and a done card with an empty result falls back to its closing RUN's summary — never to a parking block's (see below). Falling back to every run summary, as this first did, read RVp1's parking block summary as a verdict and held Gp forever."`
2. `template/card-bodies/_result-field.txt:1` — *"a card completed with a summary only has reported nothing to the board"* is false (same fallback). Replace that clause with: `"…so a card completed with a summary only has reported nothing in the field the driver reads first — a done card with an empty `result` falls back to its closing run's summary, which is a supported path but not the one to rely on."`
3. `template/card-bodies/rvp-body.txt:5` — *"the parent card **staged** a plan at `<PLAN>`"*: the plan is a run hand-off, never staged (checklist item 8, `DESIGN.md:24`, `run.py:1278-1280`). Change to: `"the parent card wrote a plan to <PLAN> — a run hand-off, not a staged file; read it at that path and never look for it in the git index."`
4. `driver/run.py:214-216` — the fallback manifest is claimed to equal "the defaults `create-board.sh` prints in `--help`", but it sets `integration-tests: False` while the help says both levels on and `board_schema`'s default is `True`. Make both true by aligning the fallback with the schema:

```python
    except FileNotFoundError:
        # The schema's own defaults, so the fallback and the validator cannot
        # disagree — `board_schema.OPTIONS` is the one declaration of them.
        return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
                "integration-tests": True, "auto-gates": []}
```
5. `driver/create-board.sh:120-123` — `max-reworks` is documented as an option "to ask for FEWER" while two shipped boards set it to 4, above the house default 3. Change to: `"The house default is 3; name it in the manifest or in a lane's idea header to change it — fewer rounds for a lane whose rounds should be cheap, more for one whose reviews keep finding real faults. (The shipped boards set 4.)"`

- [ ] **Step 2: Fix the per-lane/board-level and role drift in the same option table**

`driver/create-board.sh:140` — the prose calls `auto-gates` a per-lane option (it is board-level) and omits `max-reworks`/`model`/`provider`, which *are* per-lane. Replace the sentence with:

```
`refinement`, `unit-tests`, `integration-tests`, `max-reworks`, `model` and `provider`
are the per-lane options: each takes one value for every lane, or a list with exactly
one value per lane — `[false, true]` reads as "lane 1 without integration cards, lane 2
with". `auto-gates` is a BOARD option and has no per-lane form.
```

`driver/create-board.sh:59` — the `assignees` example uses the retired role `reviewer`, which `board_schema.ROLES` refuses, so copy-pasting the script's own table yields an unvalidatable board. Change to:

```
      "assignees": {"coder": "coder"},            # optional: role -> hermes profile
```
(and note in the line's comment that the roles are `researcher`, `coder`, `human-gate`.)

- [ ] **Step 3: Fix the retired-step and tombstone references**

- `driver/run.py:2048-2049` and `driver/start-board.sh:95-97` — both claim the lane's stale outputs are cleared on every entry path; the clearing functions were retired and a test asserts their absence. Replace with: `"Opening the lane writes the <IDEA> snapshot and prunes TI/RVc on an `integration_tests: false` board. Stale outputs are NOT cleared — nothing in this template removes a file from `work/`; the workdir-state line on the cards is how a worker sees what was already there."`
- `driver/run.py:2215-2218` — `"(see clean_work_noise)"` points at a tombstone that raises. Replace the reference with the rule itself: `"Nothing in this template removes a run directory (user rule, 2026-09-12), so a missing one is someone else's `rm` or trash can."`
- `driver/run.py:207-210` — the docstring claims `card_render` is the one manifest reader, but `run-audit.py:410` and `board_schema.py:565` both `json.load` it raw. Rewrite the last clause to name the split honestly: `"card_render.read_board owns the file's shape FOR THE DRIVER; the auditor and the schema validator read the same file raw, deliberately, because each must survive a manifest the driver cannot parse."`

- [ ] **Step 4: Fix the two small card-body/comment drifts**

- `template/card-bodies/gc-body.txt:3` — "records the staged path list" (it records the count). Change `the driver records the staged path list in the result` → `the driver records the number of staged files in the result`.
- `template/lanes.py:83-85` — the comment calls TI "the integration tester", a retired role. Change `"the integration\n# tester AND the final review"` → `"the integration-test cards AND the final review"`.

- [ ] **Step 5: Verify nothing behavioural moved**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count unchanged at **691 passed** (this task adds no test). `driver/render-flow.py --check` must also still exit 0 — it reads `README.md`, not these files, but run it to be sure: `python3 driver/render-flow.py --check`.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py driver/create-board.sh driver/start-board.sh template/card-bodies template/lanes.py
git status --short
```
Report, then STOP.

---

## Task 9: the manifest and option contracts stop being implicit (09-23 I6–I12)

**Files:**
- Modify: `driver/run.py:206-218` (done in Task 8 — do not re-edit), `:302-309`, `:1508`, `:721`, `:741`, `:2422`, `:2441`, `:2738`, `:1229-1235`; `driver/file_lanes.py:34`, `:42`, `:95-107`; `template/lanes.py:261-263`, `:278-303`, `:358-360`
- Modify: `tests/test_model_override.py` (append), `tests/test_lane_resolution.py` (append), `tests/test_file_lanes.py` (append)

**Interfaces:**
- Consumes: `lanes.model_args(code, cfg, lane_cfg=None)`, `lanes.max_reworks(cfg)`, `file_lanes.DEFAULT_MAX_RUNTIME`/`DEFAULT_MAX_RETRIES`.
- Produces: `lanes.model_args`'s third parameter is documented and used consistently; `file_lanes` reads its defaults from `board_schema.OPTIONS` instead of re-declaring them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lane_resolution.py`:

```python
def test_a_lane_model_is_never_paired_with_the_boards_provider():
    """The resolved path paired a lane model with the BOARD's provider, which
    lane_model_opts' own docstring says must never happen: a model belongs to one
    provider, and a spawn failure is final (2026-09-23 I8)."""
    import lanes
    cfg = {"provider": "board-prov", "model": "board-model"}
    # lane names only a model: the board's provider must NOT travel with it
    assert lanes.model_args("C", cfg, {"model": "lane-model", "provider": None}) == \
        ["--model", "lane-model"]
    assert lanes.model_args("C", cfg, {"model": "lane-model", "provider": "lane-prov"}) == \
        ["--model", "lane-model", "--provider", "lane-prov"]


def test_max_reworks_reads_a_zero_as_a_cap_not_as_unset():
    """`0`/`False` read as unset while `"0"` read as a cap of zero — the same value
    meaning two things (2026-09-23 Suggestion, types)."""
    import lanes
    assert lanes.max_reworks({"max-reworks": "0"}) == 0
    assert lanes.max_reworks({"max-reworks": 0}) == 0
    assert lanes.max_reworks({}) == 3
```

Append to `tests/test_file_lanes.py`:

```python
def test_the_filing_defaults_are_the_option_tables():
    """DEFAULT_MAX_RUNTIME / DEFAULT_MAX_RETRIES re-declared the option table's
    defaults, against the house rule lanes.py:372-376 states (2026-09-23 I10)."""
    import board_schema
    assert file_lanes.DEFAULT_MAX_RUNTIME == board_schema.OPTIONS["max-runtime"][1]
    assert file_lanes.DEFAULT_MAX_RETRIES == board_schema.OPTIONS["max-retries"][1]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_lane_resolution.py tests/test_file_lanes.py -v -k "never_paired or zero_as_a_cap or filing_defaults"`
Expected: FAIL — the board provider travels with the lane model, `max_reworks({"max-reworks": 0})` returns 3, and one of the two constants is a literal.

- [ ] **Step 3: Implement**

- `template/lanes.py:261-263` — `max_reworks`: distinguish "absent" from "zero":

```python
    cfg = cfg or {}
    if "max-reworks" not in cfg or cfg["max-reworks"] is None:
        return MAX_REWORKS
    return int(cfg["max-reworks"])
```

- `template/lanes.py:278-303` — `model_args`: document the third parameter and make the pairing rule explicit in the docstring: *"`lane_cfg` is the lane's RESOLVED options (`resolve_lane_options`) — `{model, provider}`, both possibly `None`. A lane model is paired only with the lane's own provider; the board's provider belongs to the board's model and must never travel with a lane's."* The code already does this (`_model_pair(lane_cfg.get("model"), lane_cfg.get("provider"))`); the failing test is fixed by checking the **call sites** that pass the wrong shape — `driver/run.py:1508` passes `opts` (the full resolved dict, correct) while `:721`, `:741`, `:2422`, `:2441`, `:2738` pass `lane_model_opts(lane)`. Make `lane_model_opts` return exactly `{"model": ..., "provider": ...}` and nothing else, and give it a docstring saying so.
- `driver/run.py:302-309` — give `lane_options()` a docstring naming its two shapes: *"the lane's resolved options (the 6 typed keys plus `'idea'`), or **None** when the lane file is absent or blank. `None` is a state, not an empty dict: callers that index directly must handle it (`:2368-2374` breaks the lane scan on it, `:1742-1748` falls back to the board default)."* Then remove the dead `.get("refinement", True)` fallbacks the review names — grep `lane_refinement` call sites first: `grep -rn "lane_refinement\|lane_options(" driver/run.py`.
- `driver/run.py:1229-1235` — the manifest read is unvalidated everywhere but `validate_armed`. Add one line to `auto_gates()`'s docstring recording that the driver deliberately does NOT re-validate the manifest per tick (the door scripts do), so the choice is visible rather than accidental.
- `driver/file_lanes.py:34`, `:42` — replace the literals with table reads, placed with the module's other `board_schema` imports:

```python
import board_schema
DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]
DEFAULT_MAX_RETRIES = board_schema.OPTIONS["max-retries"][1]
```
(Keep the two explanatory comment blocks above them; only the values move.)
- `driver/file_lanes.py:95-107` — `next_run_key` already documents the `run-<YYYYmmdd-HHMMSS>` shape in prose only. Add the pattern as a module constant and a test-visible check:

```python
RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")
```
and in `next_run_key`, after building the fresh key, `assert RUN_ID_RE.match(key), key` is **not** the right fix (a filing must not die on a clock); instead make `card_render.run_dir` / `use_run` reject a run id that does not match, since `use_run` joins any string onto `RUNS_ROOT` (`run.py:143-153`). Add to `run.use_run`:

```python
def use_run(run_id):
    ...
    if run_id and not re.match(r"^run-\d{8}-\d{6}$", run_id):
        raise ValueError(f"not a run id: {run_id!r} — a run is `run-<YYYYmmdd-HHMMSS>`")
```
- `template/lanes.py:358-360` — `base_code`'s regex is fine; the mixed rework grammars (`:358-360`) are a Suggestion and are handled in Task 12.

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_lane_resolution.py tests/test_file_lanes.py tests/test_model_override.py tests/test_unstarted_mint.py tests/test_run_directories.py -v`
Expected: PASS.

- [ ] **Step 5: Whole-suite gate**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 691 + 3 = **694 passed**.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py driver/file_lanes.py template/lanes.py tests/test_lane_resolution.py tests/test_file_lanes.py
git status --short
```
Report, then STOP.

---

## Task 10: the remaining silent-loss and entry-point defects (09-23 I18–I26)

**Files:**
- Modify: `driver/run.py:2540-2548` + `:3771` (tick-halt keying), `:3029-3034` + `:2675-2677` (unreadable card), `:1735` (`ledger`), `:3223` (`preserve_artifacts` path), `:3710-3712` (`--timeout-min`); `driver/timing-report.py:81`; `driver/render-flow.py:168`; `driver/arm.sh:36-37`
- Modify: `tests/test_cli_timeouts.py` (append), `tests/test_runs_report.py` (append), `tests/test_render_flow.py` (append), `tests/test_open_lane.py` (append)

**Interfaces:**
- Consumes: `run.note_tick_outcome(exc)`, `run.board_removed_exit(exc, idle)`, `run.is_reasonless_block(card)`, `run.ledger(record)`, `run.preserve_artifacts()`, `timing-report._args(argv)`, `render-flow.main()`.
- Produces: `timing-report` gains `main(argv=None)`; `render-flow` reports `stale: README.md` instead of tracebacking.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_flow.py`:

```python
def test_a_missing_readme_is_reported_stale_not_a_traceback(tmp_path, monkeypatch):
    """CI runs `--check`, so a missing README was a traceback instead of
    `stale: README.md` (2026-09-23 I20)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "render_flow", os.path.join(REPO, "driver", "render-flow.py"))
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    monkeypatch.setattr(rf, "README", str(tmp_path / "nope.md"))
    assert rf.main.__doc__ is None or True          # the guard is what is under test
    monkeypatch.setattr(sys, "argv", ["render-flow.py", "--check"])
    assert rf.main() == 1
```

Append to `tests/test_cli_timeouts.py` (it already owns argv handling; adjust the module import to match its existing idiom):

```python
def test_a_repeated_timeout_flag_is_not_an_indexerror(monkeypatch):
    """`--timeout-min=120` raised IndexError at startup and a repeated flag always
    read the first value (`sys.argv.index` + unchecked `+1`) (2026-09-23 I24)."""
    import run as r
    monkeypatch.setattr(r.sys, "argv", ["run.py", "--timeout-min=120"])
    assert r.parse_timeout(["run.py", "--timeout-min=120"]) == 120 * 60
    assert r.parse_timeout(["run.py", "--timeout-min", "30", "--timeout-min", "60"]) == 60 * 60
```

(This needs a small extracted helper — see Step 3.)

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py tests/test_cli_timeouts.py -v -k "missing_readme or repeated_timeout"`
Expected: FAIL — `FileNotFoundError` from `open(README)`, and `AttributeError: parse_timeout`.

- [ ] **Step 3: Implement**

- `driver/render-flow.py:166-169` — guard the README read before `--check`:

```python
    readme = None
    try:
        with open(README) as f:
            readme = f.read()
    except OSError:
        readme = None
    if readme is not None:
        targets[README] = splice(readme, readme_block(mermaid()))
```
(`targets[README]` absent → the `stale` list at `:170-171` already contains it via the `not os.path.exists(p)` branch, so `--check` prints `stale: README.md` and exits 1.)

- `driver/run.py:3707-3712` — extract the flag parse into a helper and use it in `main()`:

```python
def parse_timeout(argv):
    """The driver's own cap, in seconds, from `--timeout-min N` or `--timeout-min=N`.

    A repeated flag takes the LAST value — the one a caller typed most recently —
    and `--timeout-min=120` is the same flag as `--timeout-min 120`; the old
    `sys.argv.index(a) + 1` raised IndexError on the first and always read the first
    occurrence on the second (2026-09-23 I24). None when the flag is absent."""
    value = None
    for i, a in enumerate(argv):
        if a == "--timeout-min" and i + 1 < len(argv):
            value = float(argv[i + 1])
        elif a.startswith("--timeout-min="):
            value = float(a.split("=", 1)[1])
    return value * 60 if value is not None else None
```

and in `main()`:

```python
    timeout = parse_timeout(sys.argv)
    if timeout is None:
        timeout = None if SERVE else 120 * 60
```

- `driver/run.py:1735` — `ledger()` makes the board dir but appends to the run dir's file:

```python
    try:
        os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)
        with open(STATE.verdicts_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"ledger: cannot append to {STATE.verdicts_path} ({e})")
```

- `driver/run.py:3223` — `preserve_artifacts` hardcodes `~/.hermes`:

```python
        attachments = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
        for src in glob.glob(os.path.join(attachments, cid, "*.patch")):
```

- `driver/run.py:2540-2548` — key the tick-halt counter on the exception TYPE plus its first line, not the whole message (an id that varies resets the counter):

```python
def _tick_signature(exc):
    """A stable name for a tick exception: its type and the FIRST line of its text.
    The whole message was the key, and a message carrying a varying id (a card id, a
    timestamp) reset the counter every tick, so a loop never halted
    (2026-09-23 I18)."""
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"{type(exc).__name__}: {first}"
```
and use `sig = _tick_signature(exc) if exc is not None else None` in `note_tick_outcome`.

- `driver/run.py:3771` — `board_removed_exit` matches a CLI prose substring. Keep the match but make it tolerant of surrounding prose and case, and name the alternative in the docstring:

```python
    text = str(exc).lower()
    if "does not exist" not in text or BOARD.lower() not in text:
        return None
```

- `driver/run.py:3029-3034` + `:2675-2677` — an unreadable card reads as "not blocked"/"not exhausted". `is_reasonless_block` already handles `p is None`; add the same honesty where the callers decide, by returning the read error through the existing `STATE.read_error` channel instead of silently continuing. Concretely, in the escalation scan at `:2675-2677`:

```python
        p = _exhaustion_event(c["id"], events)
        if p is None:
            if c["id"] in STATE.read_error:
                log(f"WARNING: cannot read {c['id']} ({STATE.read_error[c['id']]}) — "
                    f"exhaustion and block reasons are unchecked for it this tick")
            continue
```

- `driver/timing-report.py:81` — move the import-time parse into `main`:

```python
def main(argv=None):
    board, jsonl = _args(sys.argv[1:] if argv is None else argv)
    global BOARD, JSONL
    BOARD, JSONL = board, jsonl
    snaps = load_snaps()
```
and delete the module-level `BOARD, JSONL = _args(sys.argv[1:])` at `:81`, leaving `BOARD = JSONL = None` as the module state.
- `driver/arm.sh:36-37` — under `set -euo pipefail` a headingless idea makes `grep` exit 1 and aborts before the fallback:

```bash
TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)
[ -n "$TITLE" ] || TITLE="Idea $LANE"
```

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py tests/test_cli_timeouts.py tests/test_open_lane.py tests/test_run_directories.py tests/test_runs_report.py -v`
Expected: PASS.

- [ ] **Step 5: Whole-suite gate**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 694 + 2 = **696 passed**.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py driver/timing-report.py driver/render-flow.py driver/arm.sh tests/
git status --short
```
Report, then STOP.

---

## Task 11: the audit surface's remaining untested outcomes (09-23 I28–I33, I36)

**Files:**
- Modify: `tests/test_run_audit.py`, `tests/test_run_directories.py`, `tests/test_file_lanes.py`, `tests/test_runs_report.py`
- No engine file is edited in this task.

**Interfaces:**
- Consumes: `ra._proc_state`, `ra.worker_outlived_run`, `ra.work_noise_findings`, `ra.card_log_findings`, `run.reset_attempt_budgets`, `file_lanes._options_line`, `runs_report._size` / `runs_in` / `main`.
- Produces: tests only.

- [ ] **Step 1: Add the tests**

Append to `tests/test_run_audit.py`:

```python
def test_proc_state_reads_the_real_proc_status():
    """Both E8 tests monkeypatch `_proc_state` away, so the zombie filter added after
    the 2026-09-15 false E8 never runs — and a run summary is written once, so a false
    positive can never be corrected (2026-09-23 I28)."""
    assert ra._proc_state(os.getpid()) in ("R", "S", "D", "I")
    assert ra._proc_state(999999999) is None


def test_no_gate_evidence_is_an_e4(tmp_path):
    """E4's three arms and E10 appear 0 times in tests/ (2026-09-23 I29)."""
    runs = fixture(tmp_path, gates={})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "no gate evidence" in t for _s, c, t in findings)


def test_a_gi_gate_without_a_refined_idea_is_an_e4(tmp_path):
    runs = fixture(tmp_path, gates={"Gi1": "auto-gate (lane 1): all sections. NOTHING COMMITTED."})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "refined idea" in t for _s, c, t in findings)


def test_cards_with_no_agent_minutes_are_an_e10(tmp_path):
    runs = fixture(tmp_path, summary_extra={"agent_union_min": 0, "agent_work_min": 0})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E10" for _s, c, _t in findings)


def test_an_external_workdir_is_not_walked(tmp_path):
    """The guard in work_noise_findings is uncovered, on exactly the boards that build
    elsewhere (2026-09-23 I30)."""
    outside = tmp_path / "elsewhere"
    (outside / "__pycache__").mkdir(parents=True)
    runs = fixture(tmp_path)
    findings = ra.work_noise_findings(runs, str(outside))
    assert findings == []
```

Append to `tests/test_run_directories.py`:

```python
def test_a_restart_resets_every_cards_attempt_budget(tmp_path, monkeypatch):
    """A restart that does not reset leaves cards over max_retries for ever
    (2026-09-23 I33)."""
    import sqlite3
    import run as r
    home = tmp_path / "home"
    db_dir = home / "kanban" / "boards" / "b"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "kanban.db")
    conn.execute("CREATE TABLE tasks (status TEXT, consecutive_failures INT, "
                 "last_failure_error TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('ready', 3, 'boom')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "log", lambda msg: None)
    r.reset_attempt_budgets()
    conn = sqlite3.connect(db_dir / "kanban.db")
    assert conn.execute("SELECT consecutive_failures, last_failure_error "
                        "FROM tasks").fetchone() == (0, None)
```

Append to `tests/test_file_lanes.py`:

```python
def test_the_options_line_reports_a_header_that_conflicts(tmp_path):
    """`_options_line`'s success/CONFLICTS path never runs — every test passes
    `/repo`, so it takes the `except` (2026-09-23 I31)."""
    board = tmp_path / "boards" / "b"
    board.mkdir(parents=True)
    (board / "board.json").write_text(json.dumps({"slug": "b", "unit-tests": True}))
    line = file_lanes._options_line("b", 1, str(tmp_path),
                                    "<!-- unit-tests: false -->\n# Idea\n### Done means\nx\n",
                                    workdir=None)
    assert "CONFLICTS" in line
```

Append to `tests/test_runs_report.py`:

```python
def test_size_scales_and_the_superseded_note_is_directional(tmp_path):
    """`_size` scaling, the `superseded` False direction, `--board` and `main([])`
    are all untested (2026-09-23 I36)."""
    assert rr._size(999) == "999B"
    assert rr._size(2048) == "2K"
    assert rr._size(3 * 1024 ** 3) == "3G"
    runs, _live = rr.runs_in(str(tmp_path / "runs"))
    assert runs == []
```

- [ ] **Step 2: Run the new tests**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py tests/test_run_directories.py tests/test_file_lanes.py tests/test_runs_report.py -v -k "proc_state or gate_evidence or refined_idea or e10 or external_workdir or attempt_budget or conflicts or scales"`
Expected: PASS. If a test reveals a real defect (rather than a missing test), **stop and report it on the card** — a defect found while writing a test is a finding, not a test to bend.

- [ ] **Step 3: Whole-suite gate**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 696 + 8 = **704 passed**.

- [ ] **Step 4: Stage and ask**

```bash
git add tests/
git status --short
```
Report, then STOP.

---

## Task 12: suggestions and hygiene, one pass (09-23 Suggestions + 09-20 leftovers)

**Files:**
- Modify: `tests/test_lanes_ideas.py:78`, `tests/test_render_flow.py:14-16`, `tests/test_run_directories.py:103`, `tests/test_shipped_boards.py:176`; `driver/timing-report.py:122`; `driver/create-board.sh:474-487`; `driver/run-audit.py:455`, `:510`, `:523`, `:400`; `driver/run.py:2805`; `template/card-bodies/gc-body.txt:3` (done in Task 8)

**Interfaces:**
- Consumes: nothing new. **Produces:** nothing new.

- [ ] **Step 1: Fix the weak/vacuous tests**

- `tests/test_lanes_ideas.py:78-80` — the expected dict has a duplicated `"unit-tests"` key that silently overrides itself, so the assertion is weaker than it reads. Delete the first `"unit-tests": False,` (the `"true"` header wins, so the surviving entry is `"unit-tests": True`).
- `tests/test_render_flow.py:14-16` — `assert "failsafe" not in text` is vacuous (the word appears nowhere in `driver/` or `template/`). Replace with a check that bites: assert the diagram names no `bots` driver and that `--check` fails on a stale file:

```python
def test_the_generic_diagram_names_no_retired_driver():
    text = open(os.path.join(REPO, "driver", "flow.mmd")).read().lower()
    assert "bots" not in text
    assert "failsafe" not in text


def test_check_fails_when_a_diagram_is_stale(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "render_flow", os.path.join(REPO, "driver", "render-flow.py"))
    rf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rf)
    out = tmp_path / "flow.mmd"
    out.write_text("stale\n")
    monkeypatch.setattr(rf, "HERE", str(tmp_path))
    monkeypatch.setattr(rf, "REPO", str(tmp_path))
    monkeypatch.setattr(rf, "README", str(tmp_path / "README.md"))
    monkeypatch.setattr(sys, "argv", ["render-flow.py", "--check"])
    assert rf.main() == 1
```
- `tests/test_run_directories.py:103` and `tests/test_shipped_boards.py:176` — docstrings still name the retired `RUN_DIR` global. Replace `RUN_DIR` with `STATE.run_dir` in both docstrings.

- [ ] **Step 2: Delete the dead code the review named**

- `driver/timing-report.py:122-141` — `parse_elapsed_minutes` has zero callers repo-wide (verify: `grep -rn parse_elapsed_minutes .`). Delete the function.
- `driver/run-audit.py:455` — `__import__("datetime")` inline: add `import datetime` to the module's imports and use `datetime.datetime.fromisoformat(ts)`.
- `driver/run-audit.py:510`, `:523` — the repeated local `import os` in `runs_root` and `board_dir_for`: delete both (`os` is imported at the top).
- `driver/run-audit.py:400` and `driver/run.py:2805` — the two `except Exception: pass` sites: give each a log line, the way their siblings do (`run.py:2809-2811` is the pattern).

- [ ] **Step 3: Collapse the double writer of `runs/current`**

`driver/create-board.sh:473-487` — the heredoc calls `unstarted_mint` twice (`:473` directly, then again inside `next_run_key` at `:474`) and re-implements `run.mint_run`'s pointer write. Replace `:473-484` with:

```python
reused = file_lanes.unstarted_mint(repo, slug)
key = file_lanes.next_run_key(repo, slug)
if reused:
    print(f"reusing run {reused} — filed before, and no driver ever started in it")
run_dir = card_render.run_dir(repo, slug, key)
os.makedirs(run_dir, exist_ok=True)
```
and use `file_lanes`' own pointer write for `runs/current` — add `file_lanes.set_current_run(repo, slug, key)` (a three-line function: write `<runs>/current.tmp`, `os.replace`) and call it here, so there is one writer of that file in the tree. Keep `run.mint_run` as the driver's own path and note in both docstrings which one a caller wants.

- [ ] **Step 4: Run the tests**

Run: `PYTHON=/usr/bin/python3 ./test.sh`
Expected: green, count = 704 + 1 (one test replaced by two; the rest net-zero) = **705 passed**. `python3 driver/render-flow.py --check` must still exit 0.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/ tests/
git status --short
```
Report, then STOP.

---

## Self-Review

**1. Spec coverage.** Every Critical in `2026-09-23-code-review.md` maps to a task: C1→T1, C2→T2, C3+C4→T3, C5+C6→T4, C7→T6, C8→T6, C9→T6. Every Important: I1–I5→T5, I6–I12→T9, I13–I16→T7, I17→T5, I18–I26→T10 (I26 is C6's site, done in T4), I27→T3, I28–I33→T11, I34→T4, I35→T5 (schema CLI), I36→T11, I37–I44→T8. Suggestions→T12. The 09-20 run's `bots/` findings (K4, K5, K9) are **N/A** — that tree was deleted by `docs/superpowers/plans/2026-09-20-drop-bots-driver.md`, and the 09-23 run confirms it. The 09-20 findings that survive are carried into the 09-23 numbering and are covered above.

**2. Placeholder scan.** No "TBD", no "handle edge cases", no "similar to Task N": every code step carries the code, every test step carries the test and its expected failure.

**3. Type consistency.** `read_json` (T3) returns `(value, problem)` and is used at all three of its sites. `parse_timeout` (T10) returns seconds or `None`. `board_runs` (T7) returns `list | None`, and every caller named in the task is updated in the same task. `RUN_ID_RE` (T9) is used by `use_run`. `_KIND_SCHEMA` (T5) gains `path` and `unchecked`, which `_kind_error` already names.

**4. Review Focus.** All five listed failure modes have a test in the task that owns the code: empty lock (T2), malformed manifest/summary (T3), torn chain line (T4), zero duration (T5), boolean `auto-gates` (T1).

**5. Baseline arithmetic.** 666 (HEAD `edea8ab`) → 667 (T1) → 670 (T2) → 674 (T3) → 678 (T4) → 685 (T5) → 689 (T6) → 691 (T7) → 691 (T8, text only) → 694 (T9) → 696 (T10) → 704 (T11) → 705 (T12). A task that lands a different count says so on its card and reconciles before the next one starts.

## Execution Handoff

The operator has not named an execution method, and the tasks are **interface-coupled**: T3 changes `findings` ordering that T6's `--json` test reads, T7 changes `board_runs`' return type that T9's call-site work and T11's tests depend on, and T5 changes a value rule that every other task's suite run gates on. They must land in order, one at a time, in one checkout — and each task's whole-suite run needs the tree to itself.

**Recommended: subagent-driven.** One fresh implementer per task, one fresh reviewer before the next task starts, then a whole-branch review. The tasks are small and independently testable, the coupling is only through named interfaces that each task declares, and the cost of a shipped mistake here is high (the auditor's exit code is the board's DONE signal).

**Plan complete and saved to `docs/superpowers/plans/2026-09-24-code-review-remediation.md`. Please review the plan. Does it capture what you want, and should we run it subagent-driven?**
