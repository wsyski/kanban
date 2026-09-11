import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def _state(root_status="ready"):
    """One lane, its root already unblocked — the state --once leaves behind."""
    st = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked",
                                   "title": lanes.card_title(c, 1)}
          for c in ("Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc")}
    st[lanes.card_title("I", 1)] = {"id": "id-I", "status": root_status,
                                    "title": lanes.card_title("I", 1)}
    return st


def _board_env(monkeypatch, tmp_path, calls, it=False):
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "")
    # clear_lane_outputs runs git -C WORKDIR; the stub keeps the test hermetic
    monkeypatch.setattr(run, "git", lambda *a: "")
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    # tick() also writes the document chain; without this the suite drops
    # chain.jsonl/halt.txt into the repo's boards/runs (BOARD is "" at import)
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "board", lambda: _state())
    monkeypatch.setattr(run, "record_timing", lambda st: None)
    monkeypatch.setattr(run, "halt_if_exhausted", lambda st: False)
    monkeypatch.setattr(run, "rework_rounds", lambda st: None)
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration_tests": it, "auto_gates": False,
                                      "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(run, "IDEAS_DIR", str(tmp_path))
    monkeypatch.setattr(run, "SNAP_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(run, "SERVE", False)
    run._OPENED.clear()
    # tick() also remembers which gate messages it has already logged
    run._WAITING.clear()


def test_the_lane_is_prepared_before_its_root_is_released(monkeypatch, tmp_path):
    """--once must not release the root from the shell: the dispatcher claims a
    ready card immediately, and the researcher then starts before open_lane has
    written the <IDEA> snapshot its body reads (ERRORS #36)."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="blocked"))
    snap = os.path.join(str(tmp_path), "snapshots", "lane-1.md")

    def kb(*a, **k):
        calls.append(a)
        if a and a[0] == "unblock" and a[1] == "id-I":
            # the hand-off the root card is told to read must already be there
            assert os.path.exists(snap), "root released before the lane was prepared"
        return ""

    monkeypatch.setattr(run, "kb", kb)
    run.tick()
    assert [c for c in calls if c[0] == "unblock"] == [("unblock", "id-I")]
    assert os.path.exists(snap)
    run._OPENED.clear()


def test_tick_opens_a_lane_whose_root_is_already_unblocked(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    assert run.tick() is False
    assert [c[1] for c in calls if c[0] == "archive"] == ["id-TI", "id-RVc"]
    assert ("unlink", "id-RVc", "id-Gc") in calls
    assert ("link", "id-RVa", "id-Gc") in calls
    assert not [c for c in calls if c[0] == "unblock"], "the root was already up"
    run._OPENED.clear()


def test_an_integration_lane_is_opened_without_pruning(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=True)
    assert run.tick() is False
    assert not [c for c in calls if c[0] in ("archive", "unlink")], calls
    run._OPENED.clear()


def test_serve_mode_leaves_an_unarmed_lane_alone(monkeypatch, tmp_path):
    """Prefilled is not running: without an armed idea — and with no snapshot
    saying the lane is already under way — nothing is opened."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "SERVE", True)
    monkeypatch.setattr(run, "_ARMED", False)
    assert run.tick() is False
    assert not [c for c in calls if c[0] in ("archive", "unlink", "link")], calls
    run._OPENED.clear()


def test_a_finished_lane_is_never_reopened(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="done"))
    assert run.tick() is False
    assert not [c for c in calls if c[0] == "archive"], calls
    run._OPENED.clear()


def test_a_held_gate_reports_once_not_once_per_tick(monkeypatch, tmp_path, capsys):
    """A gate can wait minutes for a rework round; the message belongs in the
    log once, not once every tick (six identical lines in two minutes on
    2026-09-11, each one burying the events that mattered)."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="done"))
    monkeypatch.setattr(run, "gate_action",
                        lambda *a: "waiting: final review verdict = 'REJECT: nope'")
    for _ in range(3):
        run.tick()
    out = capsys.readouterr().out
    assert out.count("waiting: final review verdict") == 1, out
    # a DIFFERENT reason is news, and is logged
    monkeypatch.setattr(run, "gate_action", lambda *a: "waiting: something else")
    run.tick()
    assert capsys.readouterr().out.count("waiting: something else") == 1
    run._OPENED.clear()
