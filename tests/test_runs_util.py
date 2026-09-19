import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import runs_util

BANNER = ("⚠ A previous `hermes update` pulled new code but did not restart running gateways.\n"
          "  Gateways may still be serving pre-update modules (mixed sys.modules).\n"
          "  Run `hermes update` or `hermes gateway restart`.\n")


def test_two_cards_at_once_count_their_overlap_once():
    """The lane FORKS (TW ∥ C), so 2 minutes beside 2 minutes is 2.5 minutes of work in
    flight, not 4 — while the sum stays what a per-card ceiling is measured against."""
    assert runs_util.union_min([(0, 120), (30, 150)]) == 2.5       # 1000→1150s = 2.5m
    assert runs_util.union_min([(0, 60), (60, 120)]) == 2.0        # touching, no gap
    assert runs_util.union_min([(0, 600), (60, 120)]) == 10.0      # one nested in another
    assert runs_util.union_min([(300, 120), (0, 60)]) == 1.0       # unsorted, junk skipped
    assert runs_util.union_min([]) == 0.0
    assert runs_util.union_min([(None, 60), (0, None), (5, 5)]) == 0.0


def test_cli_error_drops_the_update_banner_and_keeps_the_real_error():
    err = BANNER + "kanban: board 'minimal-development' does not exist.\n"
    assert runs_util.cli_error(err) == "kanban: board 'minimal-development' does not exist."


def test_cli_error_keeps_the_tail_of_a_long_error():
    assert runs_util.cli_error("x" * 500 + "END", limit=10) == "xxxxxxxEND"


def test_cli_error_tolerates_no_stderr():
    assert runs_util.cli_error(None) == ""


def test_board_runs_hands_the_cli_a_clean_env(monkeypatch):
    """The timing report reads every card's runs through here; a leaked marker
    made it print 0.0 min for a 9.1-minute run."""
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env")
        class R:
            returncode = 0
            stdout = '[{"outcome": "completed", "started_at": 10, "ended_at": 70}]'
            stderr = ""
        return R()

    monkeypatch.setenv("HERMES_DELEGATED_CHILD_CONTEXT", "1")
    monkeypatch.setattr(runs_util.subprocess, "run", fake_run)
    assert runs_util.board_runs("b", "t1")[0]["outcome"] == "completed"
    assert "HERMES_DELEGATED_CHILD_CONTEXT" not in seen["env"]
    assert seen["argv"][:3] == ["hermes", "kanban", "--board"]


def test_board_runs_warns_instead_of_reporting_an_empty_card(monkeypatch, capsys):
    def fake_run(argv, **kw):
        class R:
            returncode = 1
            stdout = ""
            stderr = "kanban: board 'b' does not exist"
        return R()

    runs_util._WARNED.clear()
    monkeypatch.setattr(runs_util.subprocess, "run", fake_run)
    assert runs_util.board_runs("b", "t1") == []
    assert "WARNING" in capsys.readouterr().err
    runs_util._WARNED.clear()


def test_cli_env_drops_the_delegated_child_marker(monkeypatch):
    """A leaked child marker makes the kanban CLI refuse every mutation, so the
    driver must never hand it to a hermes subprocess. Everything else survives."""
    monkeypatch.setenv("HERMES_DELEGATED_CHILD_CONTEXT", "1")
    env = runs_util.cli_env()
    assert "HERMES_DELEGATED_CHILD_CONTEXT" not in env
    assert "PATH" in env


def test_a_timed_out_attempt_counts_as_worked_time():
    """The ceiling exists to surface a card that burned its budget, and a timed-out
    attempt IS that event — so the summaries and the timing report, which sum only
    CLOSED_OUTCOMES, cannot drop it; dropped, its minutes reappear as "overhead" and
    the auditor calls the run clean."""
    assert "timed_out" in runs_util.CLOSED_OUTCOMES
    assert runs_util.elapsed_min({"started_at": 1_700_000_000, "ended_at": 1_700_000_600}) == 10
    assert runs_util.elapsed_min({"started_at": 10}) == 0.0
