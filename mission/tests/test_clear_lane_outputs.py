import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def _lane(tmp_path, lane, refined="PREVIOUS refined idea", plan="PREVIOUS plan"):
    d = tmp_path / "runs" / "artifacts" / f"lane-{lane}"
    d.mkdir(parents=True, exist_ok=True)
    if refined:
        (d / "refined.md").write_text(refined)
    if plan:
        (d / "plan.md").write_text(plan)
    return d


def _env(monkeypatch, tmp_path, calls):
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(run, "git", lambda *a: calls.append(a) or "")
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "IDEAS_DIR", str(tmp_path))
    monkeypatch.setattr(run, "SNAP_DIR", str(tmp_path / "runs" / "snapshots"))
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path / "boards" / "b"))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "SERVE", False)
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration_tests": False, "auto_gates": True,
                                      "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(run, "_OPENED", set())


def test_the_first_card_clears_this_lanes_previous_outputs(monkeypatch, tmp_path):
    """A human continuing a lane from a dirty state never passes through the
    refile, so the clearance has to happen when the lane's first card starts."""
    d = _lane(tmp_path, 1)
    other = _lane(tmp_path, 2)
    calls = []
    _env(monkeypatch, tmp_path, calls)
    run.open_lane({lanes.card_title("I", 1): {"id": "id-I", "status": "ready"}}, 1)
    assert not (d / "refined.md").exists()
    assert not (d / "plan.md").exists()
    assert (other / "refined.md").exists(), "another lane's hand-off was touched"


def test_the_staged_index_for_the_lane_is_cleared_too(monkeypatch, tmp_path):
    _lane(tmp_path, 1)
    calls = []
    _env(monkeypatch, tmp_path, calls)

    def fake_git(*a):
        calls.append(a)
        return "boards/b/runs/artifacts/lane-1/refined.md\n" if "diff" in a else ""

    monkeypatch.setattr(run, "git", fake_git)
    run.open_lane({lanes.card_title("I", 1): {"id": "id-I", "status": "ready"}}, 1)
    assert any(c[0] == "restore" and "--staged" in c and "--worktree" in c for c in calls), calls


def test_what_this_run_writes_is_not_cleared_again(monkeypatch, tmp_path):
    """A retry inside the run must keep the refined idea this run produced."""
    d = _lane(tmp_path, 1)
    calls = []
    _env(monkeypatch, tmp_path, calls)
    state = {lanes.card_title("I", 1): {"id": "id-I", "status": "ready"}}
    run.open_lane(state, 1)
    (d / "refined.md").write_text("THIS RUN refined idea")
    run.open_lane(state, 1)          # second tick: _OPENED makes it a no-op
    assert (d / "refined.md").read_text() == "THIS RUN refined idea"
