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


def _board_env(monkeypatch, tmp_path, calls, it=False, ut=True):
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "")
    # open_lane runs git -C WORKDIR; the stub keeps the test hermetic
    monkeypatch.setattr(run, "git", lambda *a: "")
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    # A board-owned work directory: BOARD_DIR is its parent, which is what makes
    # the cache sweep this board's business (an external tree is another
    # project's, and the sweep leaves it alone).
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    # tick() also writes the document chain; without this the suite drops
    # chain.jsonl/halt.txt into the repo's boards/runs (BOARD is "" at import)
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    # A run directory exists on disk for the whole life of a run — the driver now
    # stops when its own directory disappears (nothing in the template removes it, so
    # a missing one means someone else did), and a fixture without it is not a run.
    (tmp_path / "runs").mkdir(exist_ok=True)
    monkeypatch.setattr(run, "board", lambda: _state())
    monkeypatch.setattr(run, "record_timing", lambda st: None)
    monkeypatch.setattr(run, "halt_if_exhausted", lambda st: False)
    monkeypatch.setattr(run, "rework_rounds", lambda st: None)
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration-tests": it, "unit-tests": ut, "auto-gates": False,
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
    written the <IDEA> snapshot its body reads."""
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


def test_a_pruned_tester_narrows_the_review_in_the_drivers_graph(monkeypatch, tmp_path):
    """The driver's own view of the fork. With TW archived (`unit-tests: false`) the
    review must wait on C alone: `parents_done()` reads a missing parent as not-done,
    so a stale TW entry in the graph would stall the review forever."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, ut=False)
    st = _state()
    st.pop(lanes.card_title("TW", 1))          # an archived card is absent from the board
    monkeypatch.setattr(run, "board", lambda: st)
    graph = run.lane_graph(st)
    assert "TW1: unit tests - lane 1" not in [t for t, _p, _k, _l in graph]
    rva = [p for t, p, _k, _l in graph if t.startswith("RVa1:")][0]
    assert rva == ["C1"], rva
    c1 = [p for t, p, _k, _l in graph if t.startswith("C1:")][0]
    assert c1 == ["Gp1"], c1
    run._OPENED.clear()


def test_a_lane_without_unit_tests_unlinks_the_review_from_the_archived_tester(monkeypatch, tmp_path):
    """`unit-tests: false` archives TW, and its filed edge into RVa has to go with it:
    parents_done() reads a missing parent as not-done, so the review would wait forever
    on an archived card. C needs no surgery at all — its parent is the plan gate."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, ut=False)
    run.tick()
    assert ("archive", "id-TW") in calls
    assert ("unlink", "id-TW", "id-RVa") in calls
    assert ("link", "id-Gp", "id-C") not in calls, "there is no TW->C edge to replace"
    run._OPENED.clear()


def test_a_lane_that_prunes_its_idea_cards_releases_its_root_at_once(monkeypatch, tmp_path):
    """`refinement: false` archives I and Gi at lane open, which makes P the lane ROOT
    — but P's DECLARED parent is the idea gate the same open archives. A promotion
    graph built before the prune still lists it, a pruned parent reads as not-done,
    and the root waits a whole tick: 28 s measured on 2026-09-12's blade-workspace run
    (snapshot written 22:21:43, root released 22:22:11), which is also what made the
    run's own snapshot look like a leftover to doc-chain's F3."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration-tests": False, "unit-tests": False,
                                      "auto-gates": False, "refinement": False,
                                      "idea": "## Idea 1: is_even\n"})
    live = _state(root_status="blocked")

    def kb(*a, **k):
        calls.append(a)
        if a and a[0] == "archive":
            for title, card in list(live.items()):
                if card["id"] == a[1]:
                    live.pop(title)          # an archived card is absent from the board
        return ""

    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "board", lambda: dict(live))
    run.tick()
    archived = [c[1] for c in calls if c[0] == "archive"]
    assert archived[:2] == ["id-I", "id-Gi"], calls
    assert [c[1] for c in calls if c[0] == "unblock"] == ["id-P"], \
        "the root waited a tick for a parent its own open archived"
    run._OPENED.clear()


def test_a_lane_that_keeps_its_cells_archives_none(monkeypatch, tmp_path):
    """The pruning branches read the RESOLVED options, not the manifest — so a lane that
    ends up with both test levels (the board turned one off, the idea's header turned it
    back on) loses no card, and the review still waits for the tester."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=True, ut=True)
    st = _state()
    for code in ("I", "Gi", "P", "RVp", "Gp"):
        st[lanes.card_title(code, 1)]["status"] = "done"
    monkeypatch.setattr(run, "board", lambda: st)
    run.tick()
    assert not [c for c in calls if c[0] == "archive"], calls
    assert [c[1] for c in calls if c[0] == "unblock"] == ["id-TW", "id-C"]
    run._OPENED.clear()


def test_the_tester_and_the_coder_are_released_together(monkeypatch, tmp_path):
    """The fork: TW and C are both children of the plan gate, so ONE tick releases both
    and they work in parallel. RVa is the review that waits for the pair — releasing it
    here would have it judge a tree half of whose evidence does not exist yet."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    for code in ("I", "Gi", "P", "RVp", "Gp"):
        st[lanes.card_title(code, 1)]["status"] = "done"
    monkeypatch.setattr(run, "board", lambda: st)
    run.tick()
    unblocked = [c[1] for c in calls if c[0] == "unblock"]
    assert unblocked == ["id-TW", "id-C"], unblocked
    run._OPENED.clear()


def test_the_review_waits_for_both_halves_of_the_fork(monkeypatch, tmp_path):
    """One half done is not the implementation stage done: TW finishing first must not
    open the review over a tree the coder is still writing."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    for code in ("I", "Gi", "P", "RVp", "Gp", "TW"):
        st[lanes.card_title(code, 1)]["status"] = "done"
    monkeypatch.setattr(run, "board", lambda: st)
    run.tick()
    assert "id-RVa" not in [c[1] for c in calls if c[0] == "unblock"]
    st[lanes.card_title("C", 1)]["status"] = "done"
    calls.clear()
    run.tick()
    assert "id-RVa" in [c[1] for c in calls if c[0] == "unblock"]
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


def test_the_code_gate_leaves_a_workers_litter_where_it_is(monkeypatch, tmp_path):
    """USER RULE (2026-09-12): the board wipes nothing — `work/` and `runs/` both.

    `clean_work_noise` deleted `__pycache__`/`.pytest_cache`/`*.pyc` from `work/`
    before the code gate: the only deletion in the whole template. The gate hook now
    reads the tree and touches nothing, and the function that used to sweep is a
    tombstone — the audit reports what it finds (E16, a note) and the gate-holder
    decides what to keep.
    """
    import os
    import pytest
    board = tmp_path / "boards" / "b"
    work = board / "work"
    (work / "__pycache__").mkdir(parents=True)
    (work / "__pycache__" / "is_even.cpython-314.pyc").write_text("x")
    (work / ".pytest_cache").mkdir()
    (work / "is_even.py").write_text("def is_even(n): return n % 2 == 0\n")
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "SNAP_DIR", str(tmp_path / "snap"))
    os.makedirs(run.SNAP_DIR, exist_ok=True)
    run.write_workdir_state(1, "gate")            # what the code gate runs now
    assert (work / "is_even.py").exists(), "the deliverable must survive"
    assert (work / "__pycache__" / "is_even.cpython-314.pyc").exists(), "nothing wiped"
    assert (work / ".pytest_cache").exists(), "nothing wiped"
    with pytest.raises(NotImplementedError):
        run.clean_work_noise()                    # the tombstone, not a sweeper


def test_nothing_under_runs_stays_in_the_index(monkeypatch, tmp_path):
    """The sweep runs in the KANBAN repo, where runs/ lives — not in WORKDIR, which
    for an external default-workdir is a different repository where the pathspec means
    nothing. It also covers the whole runs/ tree, because no run directory is ever
    deleted and an earlier run's staged leftover still reaches every later diff."""
    import subprocess
    repo = tmp_path / "kanban"
    runs = repo / "boards" / "b" / "runs"
    (runs / "r-OLD" / "artifacts" / "lane-1").mkdir(parents=True)
    (runs / "r-NOW").mkdir()
    (runs / "r-OLD" / "artifacts" / "lane-1" / "plan.md").write_text("a hand-off\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c",
                    "user.name=t", "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-f",
                    "boards/b/runs/r-OLD/artifacts/lane-1/plan.md"], check=True)
    # an external work directory: its own repo, and not where runs/ lives
    ext = tmp_path / "ext"
    ext.mkdir()
    subprocess.run(["git", "init", "-q", str(ext)], check=True)

    logged = []
    monkeypatch.setattr(run, "REPO", str(repo))
    monkeypatch.setattr(run, "RUNS_ROOT", str(runs))
    monkeypatch.setattr(run, "RUN_DIR", str(runs / "r-NOW"))
    monkeypatch.setattr(run, "WORKDIR", str(ext))
    monkeypatch.setattr(run, "log", lambda m: logged.append(m))

    run.unstage_run_paths()
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached",
                             "--name-only"], capture_output=True, text=True).stdout
    assert "plan.md" not in staged, "an earlier run's staged hand-off must be swept"
    assert logged and "unstaged" in logged[0]
    # the file itself stays: unstaging is not deleting
    assert (runs / "r-OLD" / "artifacts" / "lane-1" / "plan.md").exists()

    logged.clear()
    run.unstage_run_paths()
    assert logged == [], "quiet when the index is already clean"


def test_an_assigned_card_escalated_to_triage_halts_the_driver(monkeypatch, tmp_path):
    """A worker that cannot complete its card returns it to Triage for a human.
    Polling forever hides that; the board halts and says so instead."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    st[lanes.card_title("I", 1)].update(status="triage", assignee="researcher")
    monkeypatch.setattr(run, "board", lambda: st)
    run._HALTED["reason"] = None
    assert run.tick() is True
    assert "Triage" in (run._HALTED["reason"] or "")
    assert [c for c in calls if c[0] == "comment"], calls


def test_an_unassigned_idea_in_triage_is_not_a_halt(monkeypatch, tmp_path):
    """Serve mode sits with the idea card in Triage until a human promotes it —
    that is the design, and it must never halt the board."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    st["Idea 1: is_even"] = {"id": "id-idea", "status": "triage", "title": "Idea 1: is_even"}
    monkeypatch.setattr(run, "board", lambda: st)
    run._HALTED["reason"] = None
    assert run.tick() is False
    assert run._HALTED["reason"] is None


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


def test_each_lane_reads_the_tree_as_IT_found_it(monkeypatch, tmp_path):
    """The defect this fixes: every lane's cards are filed in one moment, so a
    work-directory reading rendered into the body at filing time tells lane 2 what
    the tree looked like BEFORE lane 1 built anything in it. Writing it when the
    lane opens is the same guarantee the idea snapshot already has."""
    import file_lanes
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    snaps = tmp_path / "snapshots"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(run, "SNAP_DIR", str(snaps))

    def lane_state(lane):
        st = {lanes.card_title(c, lane): {"id": f"id-{c}{lane}", "status": "blocked",
                                         "title": lanes.card_title(c, lane)}
              for c in ("Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc")}
        st[lanes.card_title("I", lane)] = {"id": f"id-I{lane}", "status": "ready",
                                          "title": lanes.card_title("I", lane)}
        return st

    run.open_lane(lane_state(1), 1)
    lane1 = (snaps / "lane-1-workdir-at-open.md").read_text()
    assert "empty" in lane1

    (work / "built-by-lane-1.py").write_text("the first lane's product\n")
    run._OPENED.clear()
    run.open_lane(lane_state(2), 2)
    lane2 = (snaps / "lane-2-workdir-at-open.md").read_text()

    assert "NOT empty" in lane2, "lane 2 must see what lane 1 built"
    assert "empty" in lane1 and "NOT empty" not in lane1, "lane 1's reading is unchanged"


def test_the_reading_is_written_before_the_root_is_released(monkeypatch, tmp_path):
    """Same ordering the idea snapshot has: the root card's body points at this
    file, so a worker claimed the instant the root goes ready must not find it
    missing or half-written."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="blocked"))
    (tmp_path / "work").mkdir()
    monkeypatch.setattr(run, "SNAP_DIR", str(tmp_path / "snapshots"))
    reading = tmp_path / "snapshots" / "lane-1-workdir-at-open.md"
    seen = []

    def kb(*a, **k):
        calls.append(a)
        if a and a[0] == "unblock" and a[1] == "id-I":
            seen.append(reading.exists())
        return ""

    monkeypatch.setattr(run, "kb", kb)
    run.tick()
    assert seen and all(seen), "root released before its work-directory reading existed"


def test_the_reading_says_when_it_was_taken_and_that_it_is_a_snapshot(monkeypatch, tmp_path):
    """Within a lane the tree changes — the coder builds, the tester adds files — so
    the reviewer reads the same file the researcher did. It is correct for planning
    and wrong as a description of the tree now, and it has to say so itself: the
    filename carries `-at-open` and the file carries its timestamp."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    snaps = tmp_path / "snapshots"
    (tmp_path / "work").mkdir()
    monkeypatch.setattr(run, "SNAP_DIR", str(snaps))
    run.open_lane(_state(), 1)
    text = (snaps / "lane-1-workdir-at-open.md").read_text()
    assert "SNAPSHOT, not a live view" in text
    assert "git status" in text, "it must say how to get the current state"
    assert "Taken 20" in text, "and when it was taken"
