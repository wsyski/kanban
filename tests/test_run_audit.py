import datetime
import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "run_audit", os.path.join(REPO, "driver", "run-audit.py"))
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)
import runs_util  # noqa: E402  (run-audit put its own directory on the path)

BASE = datetime.datetime(2026, 9, 11, 21, 21, 0)
GOOD_LOG = ["[21:21:04] LANE 1 open: its=True uts=True auto-gates=['Gi', 'Gp', 'Gc'] snapshot=… idea='## Idea 1'",
            "[21:22:34] unblocked Gi1 (parents done)",
            "[21:22:35] GATE Gi1: auto-completed — nothing committed",
            "[21:33:30] artifact kept: boards/b/runs/artifacts/2026/t_x.patch",
            "[21:33:53] ALL GATES COMPLETE — scenario finished"]
GOOD_GATES = {
    "Gi1": "auto-gate (lane 1): refined idea present, all sections, 4 finding(s) with evidence. NOTHING COMMITTED.",
    "Gp1": "auto-gate (lane 1): plan verdict PASS (2 file(s) staged). NOTHING COMMITTED.",
    "Gc1": "auto-gate (lane 1): 2 files staged, verdict PASS. NOTHING COMMITTED.",
}


STORM = ("⚠️  API call failed (attempt 1/3): BadRequestError [HTTP 400]\n"
         "   📝 Error: HTTP 400: Error from provider (Console Go): Upstream request failed\n")


def at(seconds):
    return (BASE + datetime.timedelta(seconds=seconds)).isoformat()


def fixture(tmp_path, log=None, gates=None, cards=None, restarts=False,
            chain_recs=None, ceiling="4m", summary_extra=None):
    """A board directory with one run inside it."""
    board = tmp_path / "boards" / "b"
    runs = board / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (board / "board.json").write_text(json.dumps(
        {"slug": "b", "auto-gates": ["Gi", "Gp", "Gc"], "max-runtime": ceiling} if ceiling
        else {"slug": "b", "auto-gates": ["Gi", "Gp", "Gc"]}))
    (runs / "driver.log").write_text("\n".join(log if log is not None else GOOD_LOG) + "\n")
    summary = {
        "wall_min": 13.1, "agent_work_min": 5.6, "restarts_observed": restarts,
        "gates": GOOD_GATES if gates is None else gates,
        "cards": cards if cards is not None else {"C1: implement - lane 1": {"agent_min": 0.63}}}
    summary.update(summary_extra or {})
    (runs / "run-summary.json").write_text(json.dumps(summary))
    if chain_recs is not None:
        (runs / "chain.jsonl").write_text(
            "\n".join(json.dumps(r) for r in chain_recs) + "\n")
    return str(runs)


def codes(findings, sev=None):
    return [c for s, c, _ in findings if sev is None or s == sev]


def clean_probe(monkeypatch):
    """The board-end-state probe talks to the CLI and pgrep — stub both."""
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])


class _NoProcesses:
    """subprocess.run stand-in: no live cards, no workers outliving the run."""
    returncode = 0
    stdout = ""

    def __init__(self, *a, **kw):
        pass


def worker_chain(placeholders=None, result="did the thing", attached=None):
    return [
        {"ts": at(0), "event": "start", "lane": 1, "code": "C1", "card_id": "t_c",
         "title": "C1: implement - lane 1", "status": "ready",
         "inputs": {}, "unresolved": placeholders or []},
        {"ts": at(120), "event": "done", "lane": 1, "code": "C1", "card_id": "t_c",
         "title": "C1: implement - lane 1", "status": "done",
         "attached": attached or ["t_c.patch"], "staged": ["boards/b/work/x.py"],
         "result": result},
    ]


def test_a_clean_run_has_no_findings(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, rows, stats = ra.audit(fixture(tmp_path, chain_recs=worker_chain()))
    assert findings == [], findings
    assert [r["code"] for r in rows] == ["C1"]


def test_a_traceback_in_the_log_is_an_error(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, log=GOOD_LOG[:3] + ["[21:31:00] Traceback (most recent call last):"] + GOOD_LOG[3:]))
    assert "E2" in codes(findings, "ERROR")


def test_a_line_the_driver_carries_on_from_does_not_fail_the_run(tmp_path, monkeypatch):
    """`(non-fatal)` is the driver's own marker for a line it continues past — a summary
    it could not write, a timing report that timed out. The vocabulary reads
    `warning|failed|error` off the log, so without the marker in BENIGN these were E2
    errors, and a clean run went permanently red because the summary is written once
    (measured 2026-09-20)."""
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, log=GOOD_LOG[:3] + [
            "[21:31:00] WARNING: timing report timed out (non-fatal)",
            "[21:31:01] WARNING: summary generation failed (non-fatal): TypeError('x')",
        ] + GOOD_LOG[3:]))
    assert findings == [], findings


def test_a_warning_the_driver_did_not_disclaim_is_still_an_error(tmp_path, monkeypatch):
    """The marker is the exemption, never the word: a warning the driver did not carry
    on from is exactly what E2 is for."""
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, log=GOOD_LOG[:3] + ["[21:31:00] WARNING: the work directory moved"] + GOOD_LOG[3:]))
    assert "E2" in codes(findings, "ERROR")


def test_a_run_that_did_not_finish_is_an_error(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(tmp_path, log=GOOD_LOG[:3]))
    assert "E1" in codes(findings, "ERROR")


def test_a_halted_run_says_why(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, log=["[21:31:00] BOARD HALTED — card C1 timed_out 2x; human retry required"]))
    assert "E1" in codes(findings, "ERROR")
    assert any("halted" in t for _s, _c, t in findings)


def test_a_card_over_the_ceiling_is_a_warning(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(tmp_path, cards={
        "C1: implement - lane 1": {"agent_min": 4.7}}))
    assert "E6" in codes(findings, "WARNING")


def test_a_broken_chain_is_an_error(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, chain_recs=worker_chain(placeholders=["<PLAN>"])))
    assert "E3" in codes(findings, "ERROR")


def test_a_worker_with_no_result_warns(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, chain_recs=worker_chain(result="")))
    assert "E7" in codes(findings, "WARNING")


def test_a_gate_that_did_not_pass_is_an_error(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(tmp_path, gates={
        **GOOD_GATES, "Gc1": "auto-gate (lane 1): waiting: final review verdict = 'REJECT: x'."}))
    assert "E4" in codes(findings, "ERROR")


def test_a_restart_is_a_warning(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(tmp_path, restarts=True))
    assert "E5" in codes(findings, "WARNING")


def test_a_held_gate_warns_on_an_auto_gated_board_but_not_a_human_one(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    log = GOOD_LOG[:2] + ["[21:22:40] Gc1: waiting: final review verdict = 'REJECT: x'"] + GOOD_LOG[2:]
    findings, _rows, _s = ra.audit(fixture(tmp_path, log=log))
    assert "E2" in codes(findings, "WARNING")
    runs = fixture(tmp_path / "second", log=log)
    (tmp_path / "second" / "boards" / "b" / "board.json").write_text(
        json.dumps({"slug": "b", "auto-gates": [], "max-runtime": "4m"}))
    findings, _rows, _s = ra.audit(runs)
    assert "E2" in codes(findings, "INFO")


def test_dirt_in_the_repo_root_is_an_error(tmp_path, monkeypatch):
    """The real repo_findings: only the CLI/pgrep probe is stubbed."""
    clean_probe(monkeypatch)
    monkeypatch.setattr(ra, "REPO", str(tmp_path))
    (tmp_path / "boards" / "runs").mkdir(parents=True)
    findings, _rows, _s = ra.audit(fixture(tmp_path / "tree", chain_recs=worker_chain()))
    assert "E9" in codes(findings, "ERROR")


def test_a_worker_outliving_the_run_is_a_warning(monkeypatch):
    """The real board_findings, with the CLI and pgrep both stubbed."""

    class R:
        stdout = "1234 hermes kanban work kanban task t_x\n"
        returncode = 0

    calls = {"n": 0}

    def fake_run(cmd, **kw):
        if cmd[:2] == ["pgrep", "-af"]:
            return R()
        return R()

    monkeypatch.setattr(ra.subprocess, "run", fake_run)
    # pid 1234 is a real /proc entry on SOME hosts — in state Z there, the zombie filter
    # would drop the E8 this test expects. The real read has its own test below; here it
    # is pinned to a live state (review tests S6).
    monkeypatch.setattr(ra, "_proc_state", lambda pid: "S")
    findings = ra.board_findings("b", "unused")
    assert "E8" in codes(findings, "WARNING")


def test_a_zombie_worker_is_not_an_e8(monkeypatch):
    """A worker that has EXITED but not been reaped still shows up in `pgrep`, so it reads
    as a live worker. is-even's run on 2026-09-15 warned E8 about one whose card had
    completed minutes earlier — and a run summary is written once, so the warning can
    never be corrected afterwards."""
    class R:
        stdout = "471154 hermes kanban work kanban task t_x\n"
        returncode = 0

    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **kw: R())
    monkeypatch.setattr(ra, "_proc_state", lambda pid: "Z")
    assert "E8" not in codes(ra.board_findings("b", "unused"), "WARNING")


def test_a_worker_whose_card_is_done_is_not_an_e8(monkeypatch):
    """A worker that has completed its card is finishing its turn, not stranded — the
    card's status is where the run's state lives."""
    class R:
        stdout = "471154 hermes kanban work kanban task t_done\n"
        returncode = 0

    class RJ:
        stdout = json.dumps([{"id": "t_done", "title": "RVa1", "status": "done"}])
        returncode = 0

    monkeypatch.setattr(ra.subprocess, "run",
                        lambda cmd, **kw: R() if cmd[:2] == ["pgrep", "-af"] else RJ())
    monkeypatch.setattr(ra, "_proc_state", lambda pid: "S")
    assert "E8" not in codes(ra.board_findings("b", "unused"), "WARNING")


def test_warnings_alone_fail_the_loop(tmp_path, monkeypatch, capsys):
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, restarts=True)
    assert ra.main(["--runs", runs]) == 1
    assert "0 error(s), 1 warning(s)" in capsys.readouterr().out


def test_a_clean_run_exits_zero(tmp_path, monkeypatch, capsys):
    clean_probe(monkeypatch)
    assert ra.main(["--runs", fixture(tmp_path, chain_recs=worker_chain())]) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_an_unfinished_run_reports_one_line_not_a_cascade(tmp_path, monkeypatch):
    """And the line is about the RUN, not about the driver: a live driver is the reason
    to wait rather than the thing in the way — a serve-mode driver stays up after the
    banner and a finished run audits underneath it."""
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    runs = fixture(tmp_path, log=GOOD_LOG[:3], chain_recs=worker_chain(result=""))
    (tmp_path / "boards" / "b" / "runs" / "driver.lock").write_text(str(os.getpid()))
    findings, rows, _s = ra.audit(runs)
    assert [c for _s2, c, _t in findings] == ["E1"], findings
    text = findings[0][2]
    assert "this run has not finished yet" in text and "Wait for the banner" in text
    assert "may keep serving" in text        # never "stop the driver"
    assert rows == []


def test_a_run_whose_driver_died_without_a_halt_is_reported_dead(tmp_path, monkeypatch):
    """roman-evaluator-java-20260912-235127: the log ends on "unblocked P2" with no halt
    and no banner, and nothing noticed. The board's own lock says whether its driver
    lives — a pgrep for `run.py --timeout-min` misses a serve driver started without
    one, and matches any other board's."""
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    runs = fixture(tmp_path, log=GOOD_LOG[:3])
    import subprocess
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()                                  # reaped: its pid names no process
    (tmp_path / "boards" / "b" / "runs" / "driver.lock").write_text(str(gone.pid))
    findings, _rows, _s = ra.audit(runs)
    assert [(s, c) for s, c, _t in findings] == [("ERROR", "E1")], findings
    assert "driver died" in findings[0][2] and str(gone.pid) in findings[0][2]
    (tmp_path / "boards" / "b" / "runs" / "driver.lock").unlink()
    findings, _rows, _s = ra.audit(runs)
    assert "driver died" in findings[0][2]


def test_an_in_flight_worker_is_not_called_empty_result(tmp_path, monkeypatch):
    """A card with only a start record has no result yet — the #32 misreading."""
    clean_probe(monkeypatch)
    recs = [r for r in worker_chain(attached=[]) if r["event"] == "start"]
    findings, rows, _s = ra.audit(fixture(tmp_path, chain_recs=recs))
    assert "E7" not in codes(findings, "WARNING")
    assert rows and rows[0]["done"] == ""


def test_a_verdict_reporting_warnings_is_a_warning(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    findings, _rows, _s = ra.audit(fixture(
        tmp_path, chain_recs=worker_chain(result="PASS: 4 passed, 2 warnings (deprecation)")))
    assert "E11" in codes(findings, "WARNING")


def test_null_warnings_are_not_findings(tmp_path, monkeypatch):
    """'no warnings', '0 warnings', '0 failed, 0 errors' are all clean."""
    clean_probe(monkeypatch)
    for text in ("PASS: 4 passed, 0 warnings", "PASS: no warnings, 0 errors",
                 "PASS: 4 passed, zero warnings"):
        findings, _rows, _s = ra.audit(fixture(tmp_path, chain_recs=worker_chain(result=text)))
        assert "E11" not in codes(findings), (text, findings)


def test_a_warning_in_a_card_log_is_a_warning(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    (home / "t_c.log").write_text("ok\npytest: warning: fixture 'x' uses deprecated API\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ra.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    findings, _rows, _s = ra.audit(runs)
    assert "E13" in codes(findings, "WARNING")


def test_prose_about_a_deprecated_field_is_not_a_warning(tmp_path, monkeypatch):
    """Card logs are transcripts: a worker quoting the tool schema is not the run
    emitting a warning. The line that tripped this on 2026-09-12 is a wrapped
    continuation of the worker's own reasoning — no tool printed a warning at all."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    (home / "t_c.log").write_text(
        "Also need the result field. kanban_complete's `result` param is "
        "deprecated legacy; prefer summary.\r\n"
        " that the card is already complete — calling kanban_block would be wrong. "
        "The protocol\r\n"
        " warning is based on stale state; the live read (kanban_show) showed "
        "status done. So\r\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    findings, _rows, _s = ra.audit(runs)
    assert "E13" not in codes(findings), findings


def test_the_word_is_a_warning_only_in_a_tool_form():
    """The FORM is the rule, not the word. A review reasoning about the checklist
    quotes it — `Item 4's warning: "A [TW] step that demands a FAIL …"` — and that
    sentence is the board's own text, carried in the card body: prose, whatever it is
    about. Real case: 2026-09-12's blade-workspace run audited red (E13) on exactly
    that line while no tool in it printed a warning at all."""
    for line in ("warning: no handler for /x",
                 "  WARNING: stale cache",
                 "src/foo.c:12: warning: unused variable",
                 "pytest: warning: fixture 'x' uses deprecated API",
                 "DeprecationWarning: x is deprecated"):
        assert ra.WARN_LINE.search(line), line
    for line in ('Item 4\'s warning: "A [TW] step that demands a FAIL its own '
                 'Findings contradict fails this item"',
                 "the plan has no [TW] steps, so a warning would be wrong here",
                 "Potential item 4 issue: nothing to warn about",
                 # A worker's reasoning is HARD-WRAPPED in the transcript, so a
                 # continuation line can begin with the bare word and is still prose.
                 # Live, RVa1 on 2026-09-12's blade-workspace run: the sentence
                 # before it ended with "The protocol".
                 " warning is based on stale state; the live read (kanban_show) "
                 "showed status done. So"):
        assert not ra.WARN_LINE.search(line), line


def test_a_possessive_warning_in_a_verdict_is_prose():
    """The same guard on the result field: 'item 4\'s warning does not apply' is a
    review card citing a checklist item, not a run reporting a warning."""
    assert not ra.WARN_TEXT.search("PASS: item 4\'s warning does not apply")
    assert ra.WARN_TEXT.search("PASS: 2 warnings (deprecation)")


def test_a_provider_storm_the_run_survived_is_a_warning(tmp_path, monkeypatch):
    """A flake the run rode out lives only in the card's own log: the worker
    retried, the card finished, the driver logged nothing. Measured 2026-09-13 —
    the same 400 storm cost an earlier run of the same board an hour before, and
    the run that survived one read clean."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    (home / "t_c.log").write_text(
        "ok\n" + STORM * 2 + "session_id: 20260911_212130_bbbbbb\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ra.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    findings, _rows, _s = ra.audit(runs)
    assert "E18" in codes(findings, "WARNING"), findings
    # One finding per card, not per line: a storm is thirty identical lines.
    assert len([c for c in codes(findings, "WARNING") if c == "E18"]) == 1


def test_prose_about_status_codes_is_not_a_provider_storm(tmp_path, monkeypatch):
    """The forms are the transport's own — its failed-call line and error line, or
    the goal loop's error sentence. A card reasoning about 4xx handling is prose, and
    a tool's or a test's status code is the work, not the provider."""
    for line in ("the run had no provider storm", "a 400 in the logs would be odd",
                 "upstream was slow but answered",
                 "E       assert response status 404", "status 503",
                 "HTTP 404 from the stub, as the contract test expects",
                 "- HTTP serve → html/js/css all 200"):
        assert not runs_util.UPSTREAM_ERROR.search(line), line
    for line in ("HTTP 400: Error from provider (Console Go): Upstream request failed",
                 "⚠️  API call failed (attempt 1/3): BadRequestError [HTTP 400]",
                 "   📝 Error: HTTP 503: Service Unavailable",
                 "goal judge: API call failed"):
        assert runs_util.UPSTREAM_ERROR.search(line), line


def test_an_earlier_attempt_in_the_same_card_log_is_not_this_runs_storm(tmp_path, monkeypatch):
    """The log is append-only per card, so a file touched by this run still holds the
    attempts before it — here flushed after their own session id, as -Q writes them.
    The run's first recorded attempt offset is where its lines start."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    earlier = ("session_id: 20260911_200000_aaaaaa\n"
               + "HTTP 400: Error from provider (Console Go): Upstream request failed\n" * 3)
    (home / "t_c.log").write_text(earlier + "ok\nsession_id: 20260911_212130_bbbbbb\n")
    with open(os.path.join(runs, "verdicts.jsonl"), "a") as f:
        f.write(json.dumps({"event": "attempt", "card_id": "t_c",
                            "log_offset": len(earlier.encode())}) + "\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ra.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    findings, _rows, _s = ra.audit(runs)
    assert "E18" not in codes(findings), findings


def test_a_card_log_from_an_earlier_run_is_ignored(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    log = home / "t_old.log"
    log.write_text("warning: from the previous run\n")
    old = 1_000_000.0
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ra.os.path, "getmtime", lambda p: old if str(p) == str(log) else 9e18)
    findings, _rows, _s = ra.audit(runs)
    assert "E13" not in codes(findings), findings


def test_a_staged_path_under_runs_is_an_error(tmp_path, monkeypatch):
    """Everything under a board's runs/ stays unstaged — the rule the operator
    stated, enforced mechanically by the auditor."""
    import subprocess as sp
    repo = tmp_path / "repo"
    repo.mkdir()
    sp.run(["git", "init", "-q"], cwd=repo, check=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    runs = fixture(repo, chain_recs=worker_chain())
    rel = os.path.relpath(runs, repo)
    hand_off = repo / rel / "artifacts" / "lane-1" / "plan.md"
    hand_off.parent.mkdir(parents=True, exist_ok=True)
    hand_off.write_text("# the plan\n")
    sp.run(["git", "add", "-f", f"{rel}/artifacts/lane-1/plan.md"], cwd=repo, check=True)
    monkeypatch.setattr(ra, "REPO", str(repo))
    clean_probe(monkeypatch)      # the CLI/pgrep probe only; repo_findings is real
    findings, _rows, _s = ra.audit(runs)
    assert "E14" in codes(findings, "ERROR"), findings


def test_a_cache_left_in_work_is_an_error(tmp_path, monkeypatch):
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    work = tmp_path / "boards" / "b" / "work"
    (work / "__pycache__").mkdir(parents=True, exist_ok=True)
    (work / "__pycache__" / "x.pyc").write_text("x")
    (work / "notes.tmp").write_text("scratch")
    findings, _rows, _s = ra.audit(runs)
    # A NOTE, not a fault: the board deletes nothing, so `work/` litter is reported
    # and left exactly where it is, and the run is still clean.
    assert "E16" in codes(findings, "INFO"), findings
    assert "E16" not in codes(findings, "ERROR"), findings
    assert ra.report(findings, _rows, _s, None) == 0
    assert [f for f in findings if f[0] == "INFO"][0][2].startswith("not a deliverable, left in place")


def test_the_report_measures_overhead_against_time_in_flight(tmp_path, capsys):
    """The fork (TW ∥ C) made the summed agent total exceed the wall, and a negative
    overhead reads as a bug. The report measures against the union and says how much
    of the run had two cards at once."""
    runs = fixture(tmp_path, summary_extra={
        "wall_min": 5.0, "agent_work_min": 4.0, "agent_union_min": 2.5,
        "overlap_min": 1.5})
    findings, rows, stats = ra.audit(runs)
    ra.report(findings, rows, stats, 4.0)
    out = capsys.readouterr().out
    assert "overlap 1.5 min (two cards at once)" in out, out
    assert "overhead 2.5 min" in out, out
    # The ceiling printed here is the PER-CARD one the card rows flag against, and the
    # line used to read `wall 5.0 min ... of a 4m ceiling` — a wall total "of" a ceiling
    # it never bounds. The scope has to be in the words.
    assert "per-card ceiling 4m" in out, out


def test_the_ceiling_parser():
    assert ra.ceiling_minutes("4m") == 4.0
    assert ra.ceiling_minutes("60m") == 60.0
    assert ra.ceiling_minutes("1h30m") == 90.0
    assert ra.ceiling_minutes("90s") == 1.5
    assert ra.ceiling_minutes(None) is None


# ---- per-run directories: the auditor must read either form ----------------

def test_the_board_is_found_from_a_run_directory(tmp_path):
    """`dirname(runs_dir)` was the board while runs/ was flat; a run directory is
    one level deeper. Getting it wrong is SILENT — board.json goes unread, so the
    per-card ceiling and auto-gates both default and the table still looks clean."""
    board = tmp_path / "boards" / "b"
    (board / "runs" / "b-20260912-090000").mkdir(parents=True)
    for probe in (board / "runs", board / "runs" / "b-20260912-090000"):
        assert ra.board_dir_for(str(probe)) == str(board), probe
        assert ra.runs_root(str(probe)) == str(board / "runs"), probe


def test_the_index_check_covers_every_run_not_just_this_one(tmp_path):
    """No run directory is ever deleted, so an older run's staged leftover is still
    in the index and still reaches every later `git diff --cached`."""
    board = tmp_path / "boards" / "b"
    (board / "runs" / "r1").mkdir(parents=True)
    assert ra.runs_root(str(board / "runs" / "r1")) == str(board / "runs")


def test_the_current_run_is_used_when_runs_is_given(tmp_path):
    board = tmp_path / "boards" / "b"
    (board / "runs" / "r1").mkdir(parents=True)
    (board / "runs" / "current").write_text("r1\n")
    assert ra.resolve_run_dir(str(board / "runs")) == str(board / "runs" / "r1")
    # a board from before per-run directories still reads flat
    flat = tmp_path / "boards" / "old" / "runs"
    flat.mkdir(parents=True)
    assert ra.resolve_run_dir(str(flat)) == str(flat)


def test_a_pointer_that_escapes_the_runs_directory_is_no_current_run(tmp_path):
    """run-audit resolves `--runs` through `runs_util`, so the READER's own check
    applies here too: a hand-edited `current` of `../../../x` is a path, not a run name,
    and the audit must not read that directory as this run's evidence (2026-09-24
    review)."""
    board = tmp_path / "boards" / "b"
    runs = board / "runs"
    (runs / "r1").mkdir(parents=True)
    (tmp_path / "x").mkdir()                      # the escaping path EXISTS
    (runs / "current").write_text("../../../x\n")
    assert ra.resolve_run_dir(str(runs)) == str(runs)
    (runs / "current").write_text("r1\n")
    assert ra.resolve_run_dir(str(runs)) == str(runs / "r1")


def test_a_chain_record_with_an_unusable_ts_is_counted_not_a_traceback(tmp_path, monkeypatch):
    """A VALID-JSON chain line with `"ts": "yesterday"` raised ValueError out of
    doc-chain's parse_ts, so `audit()` died with a traceback instead of reporting
    (2026-09-24 review). A record whose ts is not a timestamp is skipped and COUNTED,
    like a torn line — the E3 finding is the audit's answer."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    with open(os.path.join(runs, "chain.jsonl"), "a") as f:
        f.write(json.dumps({"ts": "yesterday", "event": "start", "lane": 1, "code": "C2",
                            "card_id": "t_c2", "title": "C2: implement - lane 1",
                            "inputs": {}, "unresolved": []}) + "\n")
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E3" and "1 unreadable record(s)" in t for _s, c, t in findings), findings


@pytest.mark.parametrize("bad_slot", ["inputs", "unresolved"])
def test_a_wrongly_typed_start_record_is_a_finding_not_a_traceback(tmp_path, monkeypatch,
                                                                   bad_slot):
    """`analyze` needs `inputs` to be a dict (and iterates `unresolved`); a JSON `null`
    or a list there raised AttributeError / TypeError out of `audit()`, so the audit
    died instead of reporting the chain (2026-09-24 review). One tolerance per reader,
    and the card is still judged."""
    clean_probe(monkeypatch)
    recs = worker_chain()
    recs[0][bad_slot] = None        # JSON null: what a half-written hand-edit leaves
    findings, rows, _stats = ra.audit(fixture(tmp_path, chain_recs=recs))
    assert [r["code"] for r in rows] == ["C1"], rows
    assert not [f for f in findings if f[1] == "E3"], findings   # judged, not crashed


def test_a_start_record_whose_inputs_are_a_list_is_not_an_attribute_error(tmp_path,
                                                                         monkeypatch):
    """The other wrong type: `[]` where a dict belongs (`[].items` is the traceback),
    the shape a half-written hand-edit produces (2026-09-24 review)."""
    clean_probe(monkeypatch)
    recs = worker_chain()
    recs[0]["inputs"] = []
    findings, rows, _stats = ra.audit(fixture(tmp_path, chain_recs=recs))
    assert [r["code"] for r in rows] == ["C1"], rows
    assert not [f for f in findings if f[1] == "E3"], findings


def test_a_run_without_kanban_records_is_refused(tmp_path, capsys):
    """This reads a KANBAN run's records. A run directory that has none of them — the
    dropped driver left eleven of them under boards/is-even/runs/, and runs/ is
    gitignored, so they outlive any code — would otherwise be read by the log scan alone
    and reported as a driver that died mid-flight (a phantom E1). Refusing is the only
    honest answer: name the record that is missing, and stop.

    The fixture's name is arbitrary: the guard keys on the FILES and never on the name,
    and the sibling test below is what proves that.
    """
    run_dir = tmp_path / "boards" / "b" / "runs" / "run-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps({"done": [], "held_gate": None}))
    (run_dir / "driver.log").write_text("[10:00:00] lane 1: I1 -> Gi1\n")
    assert ra.main(["--runs", str(run_dir)]) == 2
    err = capsys.readouterr().err
    assert "run-summary.json" in err, err
    assert "bots/audit.py" not in err, err
    assert "bots/run-board.py" not in err, err


def test_the_refusal_is_keyed_on_the_files_not_on_the_name(tmp_path, capsys):
    """Why the guard is keyed on the FILES: a directory holding `state.json` and no
    `run-summary.json` is foreign WHATEVER it is called. A guard re-narrowed to a
    basename predicate would pass every other test in this file — the refusal fixture
    above is named like the runs on disk — and would refuse only runs that happen to be
    named that way. This is the case that goes red when the predicate stops being about
    files.
    """
    run_dir = tmp_path / "boards" / "b" / "runs" / "something-else-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text("{}")
    assert ra.main(["--runs", str(run_dir)]) == 2
    assert "not a kanban run" in capsys.readouterr().err


def test_a_work_directory_that_moved_fails_the_run(tmp_path):
    """A branch switched mid-run moves where a gate's evidence would land and makes
    the HEAD it recorded untrue. The driver can only report it — staging and
    unstaging are the board's only writes — so the auditor is what stops the loop."""
    findings, _rows, _stats = ra.audit(fixture(
        tmp_path, chain_recs=worker_chain(),
        summary_extra={"workdir_drift": [
            "the work directory moved from branch main to feature/x while this run "
            "was live"]}))
    assert [f for f in findings if f[1] == "E17"], findings


def test_a_run_whose_work_directory_held_still_passes(tmp_path):
    findings, _rows, _stats = ra.audit(fixture(
        tmp_path, chain_recs=worker_chain(), summary_extra={"workdir_drift": []}))
    assert not [f for f in findings if f[1] == "E17"], findings


def test_a_worker_revision_with_an_empty_result_is_flagged():
    rows = [{"code": "C1-rev-1", "done": True, "result": ""},
            {"code": "RVa1-r2", "done": True, "result": ""}]
    assert [f[2] for f in ra.result_findings(rows)] == ["C1-rev-1 finished with an empty result"]


def test_a_held_gate_is_judged_against_the_gates_that_are_automatic():
    """`auto-gates: ["Gi"]` — a held Gp is a person doing their job; a held Gi is not."""
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "run_audit", os.path.join(os.path.dirname(__file__), "..", "driver", "run-audit.py"))
    ra = importlib.util.module_from_spec(spec); spec.loader.exec_module(ra)
    log = ("[10:00:00] Gp1: waiting: plan review verdict\n"
           "[10:00:00] Gi1: waiting: no refined idea\n"
           "[10:00:01] ALL GATES COMPLETE — scenario finished\n")
    sev = {t.split(":")[1].strip().split(":")[0]: s
           for s, c, t in ra.driver_findings(log, ["Gi"])[0] if c == "E2"}
    assert sev == {"Gp1": "INFO", "Gi1": "WARNING"}
    both = {s for s, c, _t in ra.driver_findings(log, [])[0] if c == "E2"}
    assert both == {"INFO"}, "nothing automatic: a held gate is always a person"


def test_a_kanban_run_that_halted_is_still_audited(tmp_path, capsys):
    """A halted kanban run has no run-summary.json — the driver writes one only when
    it finishes — and no state.json, so this is a run this tool MUST read: E1 names
    the halt and E4 names the missing summary, exit 1. Refusing it instead (the shape
    of the foreign-run guard one condition too wide) would silence the audit on precisely
    runs an operator wants read. Measured on disk 2026-09-20:
    boards/is-even/runs/run-20260915-121551 -> 12 error(s), exit 1."""
    run_dir = tmp_path / "boards" / "b" / "runs" / "b-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "driver.log").write_text(
        "[10:00:00] lane 1: I1 -> Gi1\n"
        "[10:05:00] BOARD HALTED — driver exiting; board state left for human inspection\n")
    (run_dir / "halt.txt").write_text("halted\n")
    assert ra.main(["--runs", str(run_dir)]) == 1
    out = capsys.readouterr()
    assert "E1" in out.out and "the run halted" in out.out, out
    assert "E4" in out.out, out                      # no run-summary.json, and reported
    assert out.err == "", out                        # nothing was refused, so nothing was said


def _stub_board_cli(monkeypatch, cards):
    """`hermes kanban --board b list --json` answered with `cards`; no live workers."""
    class Cards:
        returncode = 0
        stdout = json.dumps(cards)

    class Procs:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(ra.subprocess, "run",
                        lambda cmd, **kw: Procs() if cmd[:2] == ["pgrep", "-af"] else Cards())


def test_a_card_the_board_did_not_finish_is_an_e12(monkeypatch):
    """E12 is the claim the whole gate rests on — "the board still holds a card this run
    never finished" — and it has never run against a non-empty board: `"E12"` appears 0
    times in `tests/`, and the 30 tests that call `ra.audit()` get `cards = []` from the
    stubbed CLI, so an inverted condition here would let a half-finished run audit clean
    with the whole suite green (code review K8, 2026-09-20)."""
    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "running"}])
    findings = ra.board_findings("b", "unused")
    assert codes(findings, "ERROR") == ["E12"], findings
    assert "did not finish" in findings[0][2], findings


def test_an_escalated_triage_card_is_an_e12_and_a_resting_one_is_not(monkeypatch):
    """`triage` is where an UNASSIGNED idea card rests until a human promotes it, so it
    is a done state; an ASSIGNED card there is the board escalating and must be E12.
    Measured 2026-09-20: the two-card list the review proposed yields ONE E12, not two —
    the unassigned row is dropped on purpose, so the escalated shape is the one that
    pins the second E12."""
    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "running"},
                                  {"id": "t2", "title": "Idea 1", "status": "triage",
                                   "assignee": "coder"}])
    assert codes(ra.board_findings("b", "unused"), "ERROR") == ["E12", "E12"]

    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "done"},
                                  {"id": "t2", "title": "Idea 1", "status": "triage"}])
    assert codes(ra.board_findings("b", "unused"), "ERROR") == []


def test_an_unreadable_lock_says_unreadable_not_none(tmp_path, monkeypatch):
    """`pid none` read as "there is no lock file" when the file was there and named
    nothing readable — a different claim, and the one a human needs to act on (errors
    S14). The run here is mid-flight (no finish banner), which is the only path that
    names the lock at all."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, log=GOOD_LOG[:-1])            # no ALL GATES COMPLETE
    (tmp_path / "boards" / "b" / "runs" / "driver.lock").write_text("")
    findings, _rows, _stats = ra.audit(runs)
    assert any("unreadable" in t for _s, _c, t in findings), findings


def test_a_driver_holding_the_kernel_lock_is_alive_whatever_pid_it_names(tmp_path):
    """The auditor asks the kernel first: a live driver holds a flock on runs/driver.lock
    for its whole life, so "is the driver alive" no longer depends on a pid the OS may
    have reused."""
    import fcntl
    root = tmp_path / "runs"
    root.mkdir()
    lock = root / "driver.lock"
    lock.write_text("999999")                               # names a dead pid
    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert ra._driver_alive(str(root)) == (True, "999999")
    finally:
        os.close(fd)
    assert ra._driver_alive(str(root)) == (False, "999999")
    assert ra._driver_alive(str(tmp_path / "nowhere")) == (False, None)


def test_a_missing_manifest_is_an_error_not_a_clean_run(tmp_path, monkeypatch):
    """Measured 2026-09-23: a run with a 90-minute card under a declared 60m ceiling and
    NO board.json audited "0 error(s), 0 warning(s)", exit 0 — cfg = {} left the ceiling
    None (E6 is guarded on it), emptied auto-gates and made the slug the directory name.
    The auditor's exit code is the board's definition of DONE (review Critical 3)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path)
    os.unlink(os.path.join(os.path.dirname(runs), "board.json"))
    findings, _rows, _stats = ra.audit(runs)
    assert any(s == "ERROR" and c == "E4" and "no board.json" in t
               for s, c, t in findings), findings


def test_a_present_manifest_still_audits_clean(tmp_path, monkeypatch):
    """The other side: the new E4 must not fire when the manifest is there, or every
    shipped run audits red."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    findings, _rows, _stats = ra.audit(runs)
    assert not [t for _s, c, t in findings if "board.json" in t], findings


def test_a_truncated_summary_is_one_e4_not_a_traceback(tmp_path, monkeypatch):
    """write_summary was not atomic, so a driver killed mid-write left a truncated
    run-summary.json and every later audit of that run died with JSONDecodeError
    (review Critical 4). ONE finding — not also "the run wrote no summary"."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path)
    with open(os.path.join(runs, "run-summary.json"), "w") as f:
        f.write('{"wall_min": 13.1, "agent_w')
    findings, _rows, _stats = ra.audit(runs)
    summary_lines = [t for _s, c, t in findings if c == "E4" and "summary" in t]
    assert len(summary_lines) == 1 and "not readable JSON" in summary_lines[0], findings


def test_a_truncated_manifest_is_an_error_not_a_traceback(tmp_path, monkeypatch):
    """The manifest half of the same finding — and the wording names the file's state,
    not "no board.json" (review Critical 4)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path)
    (tmp_path / "boards" / "b" / "board.json").write_text('{"slug": "b", "auto-gates": [')
    findings, _rows, _stats = ra.audit(runs)
    assert any(s == "ERROR" and c == "E4" and "board.json is not readable JSON" in t
               for s, c, t in findings), findings


def test_a_manifest_that_is_not_an_object_is_an_error(tmp_path, monkeypatch):
    """`[]` parses — and every reader calls .get() on it."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path)
    (tmp_path / "boards" / "b" / "board.json").write_text("[]")
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "not a JSON object" in t for _s, c, t in findings), findings


def test_a_malformed_summary_exits_nonzero_through_the_cli(tmp_path, monkeypatch, capsys):
    """Through main(), human report path: its own manifest read must not traceback."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path)
    (tmp_path / "boards" / "b" / "board.json").write_text("{not json")
    open(os.path.join(runs, "run-summary.json"), "w").write("{")
    assert ra.main(["--runs", runs]) == 1


def test_a_torn_chain_line_is_an_e3_finding_not_a_traceback(tmp_path, monkeypatch):
    """The auditor's side of Critical 5: the skipped count is REPORTED."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    with open(os.path.join(runs, "chain.jsonl"), "a") as f:
        f.write('{"ts": "2026-09-11T21:30:00", "event": "start", "code": "C1"')
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E3" and "unreadable" in t for _s, c, t in findings), findings


def test_the_json_contract_is_what_the_caller_reads(tmp_path, monkeypatch, capsys):
    """`--json` is the machine-readable path and had NO test: ra.main was called five
    times in this file and never with the flag (2026-09-23 review, Critical 9). The
    three keys are the contract; `findings` must be what audit() returned, and the exit
    code must follow the findings."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    assert ra.main(["--runs", runs, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert sorted(out) == ["findings", "rows", "stats"], sorted(out)
    assert out["findings"] == [list(f) for f in ra.audit(runs)[0]]


def test_the_json_exit_code_follows_the_findings(tmp_path, monkeypatch, capsys):
    """A WARNING is enough to make the audit non-zero — the rule a key rename or a
    one-sided edit to the exit computation would break while the human report stayed
    green."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain(), restarts=True)
    findings, _rows, _stats = ra.audit(runs)
    assert [s for s, _c, _t in findings if s in ("ERROR", "WARNING")], findings
    assert ra.main(["--runs", runs, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["findings"] == [list(f) for f in findings]


def test_a_card_whose_minutes_are_unknown_is_not_under_its_ceiling(tmp_path, monkeypatch):
    """write_summary records `runs_unreadable` when the runs CLI refused: the card's
    minutes are unknown, so its ceiling was not checked — and the audit says so rather
    than reading the missing number as zero (review Important 15)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain(),
                   cards={"C1: implement - lane 1": {"agent_min": None,
                                                     "runs_unreadable": True}})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E6" and "unknown" in t for _s, c, t in findings), findings


def test_the_real_proc_reader_reads_a_real_proc():
    """The zombie filter that fixed the 2026-09-15 false E8 was monkeypatched away in
    both E8 tests, so its /proc parse never ran (review tests I28)."""
    state = ra._proc_state(os.getpid())
    assert state and state.isalpha(), state            # this process: R or S
    assert ra._proc_state(2 ** 22 + 12345) is None       # above pid_max: cannot exist


def test_no_gate_evidence_in_the_summary_is_an_e4(tmp_path, monkeypatch):
    """E4's "no gate evidence" arm appeared 0 times in tests/ (review tests I29)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, gates={})
    findings, _rows, _stats = ra.audit(runs)
    assert ("ERROR", "E4", "no gate evidence in the summary") in findings, findings


def test_an_idea_gate_without_the_refined_idea_is_an_e4(tmp_path, monkeypatch):
    """The failure direction of the Gi check never fired: 'refined idea present' was in
    tests/ only inside the positive GOOD_GATES fixture (review tests I29)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, gates={**GOOD_GATES, "Gi1": "auto-gate (lane 1): all "
                                                       "sections. NOTHING COMMITTED."})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "Gi1 completed without the refined idea" in t
               for _s, c, t in findings), findings


def test_cards_with_no_agent_minutes_are_an_e10(tmp_path, monkeypatch):
    """E10 appeared 0 times in tests/ (review tests I29)."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, summary_extra={"agent_union_min": 0.0, "agent_work_min": 0.0})
    findings, _rows, _stats = ra.audit(runs)
    assert "E10" in codes(findings, "WARNING"), findings


def test_an_external_workdir_is_not_the_boards_noise(tmp_path):
    """work_noise_findings' guard for a board that builds in ANOTHER project was dead in
    tests: every caller used the board's own work/ (review tests I30)."""
    runs = fixture(tmp_path)
    outside = tmp_path / "elsewhere"
    (outside / "__pycache__").mkdir(parents=True)
    assert ra.work_noise_findings(runs, workdir=str(outside)) == []
    inside = tmp_path / "boards" / "b" / "work"
    (inside / "__pycache__").mkdir(parents=True)
    assert codes(ra.work_noise_findings(runs, workdir=str(inside))) == ["E16"]


def test_a_board_whose_cards_cannot_be_read_says_so(monkeypatch):
    """`except Exception: cards = []` read an unreachable board as "no unfinished
    cards", so E12 could not fire on exactly the board the audit could not see
    (review errors S2)."""
    class R:
        returncode = 1
        stdout = ""
        stderr = "kanban: database is locked"

    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **kw: R())
    findings = ra.board_findings("b", "unused")
    assert any(c == "E12" and "could not be read" in t and "database is locked" in t
               for _s, c, t in findings), findings


def test_a_failing_index_read_is_an_e14_not_a_clean_index(tmp_path, monkeypatch):
    """repo_findings never checked `git diff --cached`'s status, so a failing read
    was a clean index and E14 could not fire (review errors S3)."""
    runs = os.path.join(ra.REPO, "boards", "no-such-board-e14", "runs")
    class R:
        returncode = 128
        stdout = ""
        stderr = "fatal: index file corrupt"

    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **kw: R())
    findings = ra.repo_findings(runs)
    assert any(c == "E14" and "index file corrupt" in t for _s, c, t in findings), findings
