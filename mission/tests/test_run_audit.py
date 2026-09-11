import datetime
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "run_audit", os.path.join(REPO, "mission", "run-audit.py"))
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

BASE = datetime.datetime(2026, 9, 11, 21, 21, 0)
GOOD_LOG = ["[21:21:04] LANE 1 open: its=True auto_gates=True snapshot=… idea='## Idea 1'",
            "[21:22:34] unblocked Gi1 (parents done)",
            "[21:22:35] GATE Gi1: auto-completed — nothing committed",
            "[21:33:30] artifact kept: boards/b/runs/artifacts/2026/t_x.patch",
            "[21:33:53] ALL GATES COMPLETE — scenario finished"]
GOOD_GATES = {
    "Gi1": "auto-gate (lane 1): refined idea present, all sections, 4 finding(s) with evidence. NOTHING COMMITTED.",
    "Gp1": "auto-gate (lane 1): plan verdict PASS (2 file(s) staged). NOTHING COMMITTED.",
    "Gc1": "auto-gate (lane 1): 2 files staged, verdict PASS. NOTHING COMMITTED.",
}


def at(seconds):
    return (BASE + datetime.timedelta(seconds=seconds)).isoformat()


def fixture(tmp_path, log=None, gates=None, cards=None, restarts=False,
            chain_recs=None, ceiling="4m"):
    """A board directory with one run inside it."""
    board = tmp_path / "boards" / "b"
    runs = board / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (board / "board.json").write_text(json.dumps(
        {"slug": "b", "auto_gates": True, "max_runtime": ceiling} if ceiling
        else {"slug": "b", "auto_gates": True}))
    (runs / "driver.log").write_text("\n".join(log if log is not None else GOOD_LOG) + "\n")
    (runs / "run-summary.json").write_text(json.dumps({
        "wall_min": 13.1, "agent_work_min": 5.6, "restarts_observed": restarts,
        "gates": GOOD_GATES if gates is None else gates,
        "cards": cards if cards is not None else {"C1: implement - lane 1": {"agent_min": 0.63}}}))
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
        json.dumps({"slug": "b", "auto_gates": False, "max_runtime": "4m"}))
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
    findings = ra.board_findings("b", "unused")
    assert "E8" in codes(findings, "WARNING")


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
    monkeypatch.setattr(ra, "_driver_alive", lambda: True)
    monkeypatch.setattr(ra, "board_findings", lambda slug, runs: [])
    findings, rows, _s = ra.audit(fixture(tmp_path, log=GOOD_LOG[:3], chain_recs=worker_chain(result="")))
    assert [c for _s2, c, _t in findings] == ["E1"], findings
    assert "still in flight" in findings[0][2]
    assert rows == []


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
    emitting a warning."""
    clean_probe(monkeypatch)
    runs = fixture(tmp_path, chain_recs=worker_chain())
    home = tmp_path / "home" / "kanban" / "boards" / "b" / "logs"
    home.mkdir(parents=True)
    (home / "t_c.log").write_text(
        "Also need the result field. kanban_complete's `result` param is "
        "deprecated legacy; prefer summary.\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    findings, _rows, _s = ra.audit(runs)
    assert "E13" not in codes(findings), findings


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
    assert "E16" in codes(findings, "ERROR"), findings


def test_the_ceiling_parser():
    assert ra.ceiling_minutes("4m") == 4.0
    assert ra.ceiling_minutes("60m") == 60.0
    assert ra.ceiling_minutes("1h30m") == 90.0
    assert ra.ceiling_minutes("90s") == 1.5
    assert ra.ceiling_minutes(None) is None
