import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
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


_PARKED_SHOW = json.dumps({"events": [{"kind": "blocked",
                                       "payload": {"reason": "initial_status",
                                                   "kind": "needs_input"}}]})


def _kb(calls):
    """A stub that answers `show --json` the way a real board's cards do.

    Every card on a live board carries the block event its filing wrote
    (`create --initial-status blocked`, reason `initial_status`), and the promotion
    loop now READS that history: it releases the board's own parking brake and
    refuses to undo anybody else's stop. A stub that answers "" everywhere models a
    board with no history at all, which exists nowhere.
    """
    def kb(*a, **k):
        calls.append(a)
        if a[:1] == ("show",):
            return _PARKED_SHOW
        return ""
    return kb


def _board_env(monkeypatch, tmp_path, calls, it=False, ut=True):
    monkeypatch.setattr(run, "kb", _kb(calls))
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
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "runs"))
    # A run directory exists on disk for the whole life of a run — the driver now
    # stops when its own directory disappears (nothing in the template removes it, so
    # a missing one means someone else did), and a fixture without it is not a run.
    (tmp_path / "runs").mkdir(exist_ok=True)
    monkeypatch.setattr(run, "board", lambda: _state())
    monkeypatch.setattr(run, "record_timing", lambda st: None)
    monkeypatch.setattr(run, "halt_if_exhausted", lambda st: False)
    monkeypatch.setattr(run, "rework_rounds", lambda st: None)
    # Hermetic: a review card here is `done` with no result, so the verdict fallback
    # asks the runs CLI. Unstubbed, that call reached the REAL `hermes` (or found none),
    # and since a refused call is now UNKNOWN — which holds the cards behind the review
    # (review Important 15) — the outcome depended on the host.
    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: [])
    # The verdict ledger too: unpatched it pointed at the REPO's boards/runs/, and a
    # ledger() that now creates the directory it appends to (review Important 22) would
    # write there — the old one lost those lines silently instead.
    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "runs" / "verdicts.jsonl"))
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration-tests": it, "unit-tests": ut, "auto-gates": [],
                                      "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(run, "IDEAS_DIR", str(tmp_path))
    monkeypatch.setattr(run.STATE, "snap_dir", str(tmp_path / "snapshots"))
    monkeypatch.setattr(run, "SERVE", False)
    run.STATE.opened.clear()
    # tick() also remembers which gate messages it has already logged
    run.STATE.waiting.clear()
    run.STATE.tick_error.update(sig=None, n=0)
    # Driver memory outlives a test unless it is cleared here: the re-promotion
    # allowance, the provider re-queues, the escalate-once set and the halt holder
    # are all per-driver-run by design, and one test leaking them into the next is
    # how an escalation silently stops commenting.
    run.STATE.halted["reason"] = None
    run.STATE.repromoted.clear()
    run.STATE.requeued.clear()
    run.STATE.escalated.clear()


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
        if a[:1] == ("show",):
            return _PARKED_SHOW
        if a and a[0] == "unblock" and a[1] == "id-I":
            # the hand-off the root card is told to read must already be there
            assert os.path.exists(snap), "root released before the lane was prepared"
        return ""

    monkeypatch.setattr(run, "kb", kb)
    run.tick()
    assert [c for c in calls if c[0] == "unblock"] == [("unblock", "id-I")]
    assert os.path.exists(snap)
    run.STATE.opened.clear()


def test_tick_opens_a_lane_whose_root_is_already_unblocked(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    assert run.tick() is False
    assert [c[1] for c in calls if c[0] == "archive"] == ["id-TI", "id-RVc"]
    assert ("unlink", "id-RVc", "id-Gc") in calls
    assert ("link", "id-RVa", "id-Gc") in calls
    assert not [c for c in calls if c[0] == "unblock"], "the root was already up"
    run.STATE.opened.clear()


def test_opening_a_lane_re_points_its_cards_at_the_lanes_model(monkeypatch, tmp_path):
    """The cards are filed before their idea exists, so a `<!-- model: … -->` header
    can only land when the lane opens -- and it must land before the root is
    released, because a card claimed with the wrong model spends its single attempt
    on it. The review keeps the board's pin, and a gate is left alone: nothing
    spawns it, so a model flag on it buys nothing."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    monkeypatch.setattr(run, "manifest", lambda: {
        "model": "qwen38-27b", "provider": "llama-swap",
        "model_override": "glm-5.3-flash", "provider_override": "opencode-go"})
    monkeypatch.setattr(run, "lane_options", lambda lane: {
        "integration-tests": False, "unit-tests": True, "auto-gates": [],
        "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
    # the lane's HEADER pair — what open_lane re-points with (review Important 8)
    monkeypatch.setattr(run, "lane_model_opts",
                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
    run.tick()
    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
    for cid in ("id-I", "id-P", "id-TW", "id-C"):
        assert sets[cid] == ("muse-glimmer-30b", "--provider", "llama-swap"), cid
    # the review was filed with the pin already, so it is not re-pointed at all...
    assert "id-RVa" not in sets, sets
    # ...and a gate is never re-pointed: nothing spawns it
    for gate in ("id-Gi", "id-Gp", "id-Gc"):
        assert gate not in sets, (gate, sets)
    run.STATE.opened.clear()


def test_a_lane_without_a_pin_re_points_its_review_too(monkeypatch, tmp_path):
    """With no `model_override` the review is just another card: the lane's model
    reaches it, and the driver says so out loud (the door prints the board-level
    form of the same note)."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    monkeypatch.setattr(run, "manifest", lambda: {"model": "qwen38-27b",
                                                  "provider": "llama-swap"})
    monkeypatch.setattr(run, "lane_options", lambda lane: {
        "integration-tests": False, "unit-tests": True, "auto-gates": [],
        "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(run, "lane_model_opts",
                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
    run.tick()
    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
    assert sets["id-RVa"] == ("muse-glimmer-30b", "--provider", "llama-swap"), sets
    run.STATE.opened.clear()


def test_a_lane_that_names_no_model_re_points_nothing(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    run.tick()
    assert not [c for c in calls if c[0] == "set-model"], calls


def test_a_pruned_unit_test_card_narrows_the_review_in_the_drivers_graph(monkeypatch, tmp_path):
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
    run.STATE.opened.clear()


def test_a_lane_without_unit_tests_unlinks_the_review_from_the_archived_card(monkeypatch, tmp_path):
    """`unit-tests: false` archives TW, and its filed edge into RVa has to go with it:
    parents_done() reads a missing parent as not-done, so the review would wait forever
    on an archived card. C needs no surgery at all — its parent is the plan gate."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, ut=False)
    run.tick()
    assert ("archive", "id-TW") in calls
    assert ("unlink", "id-TW", "id-RVa") in calls
    assert ("link", "id-Gp", "id-C") not in calls, "there is no TW->C edge to replace"
    run.STATE.opened.clear()


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
                                      "auto-gates": [], "refinement": False,
                                      "idea": "## Idea 1: is_even\n"})
    live = _state(root_status="blocked")

    def kb(*a, **k):
        calls.append(a)
        if a[:1] == ("show",):
            return _PARKED_SHOW
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
    run.STATE.opened.clear()


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
    run.STATE.opened.clear()


def test_the_unit_test_card_and_the_coder_are_released_together(monkeypatch, tmp_path):
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
    run.STATE.opened.clear()


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
    run.STATE.opened.clear()


def test_an_integration_lane_is_opened_without_pruning(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=True)
    assert run.tick() is False
    assert not [c for c in calls if c[0] in ("archive", "unlink")], calls
    run.STATE.opened.clear()


def test_serve_mode_leaves_an_unarmed_lane_alone(monkeypatch, tmp_path):
    """Prefilled is not running: without an armed idea — and with no snapshot
    saying the lane is already under way — nothing is opened."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "SERVE", True)
    monkeypatch.setattr(run.STATE, "armed", False)
    assert run.tick() is False
    assert not [c for c in calls if c[0] in ("archive", "unlink", "link")], calls
    run.STATE.opened.clear()


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
    monkeypatch.setattr(run.STATE, "snap_dir", str(tmp_path / "snap"))
    os.makedirs(run.STATE.snap_dir, exist_ok=True)
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
    monkeypatch.setattr(run.STATE, "run_dir", str(runs / "r-NOW"))
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
    run.STATE.halted["reason"] = None
    assert run.tick() is True
    assert "Triage" in (run.STATE.halted["reason"] or "")
    assert [c for c in calls if c[0] == "comment"], calls


def test_an_unassigned_idea_in_triage_is_not_a_halt(monkeypatch, tmp_path):
    """Serve mode sits with the idea card in Triage until a human promotes it —
    that is the design, and it must never halt the board."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    st["Idea 1: is_even"] = {"id": "id-idea", "status": "triage", "title": "Idea 1: is_even"}
    monkeypatch.setattr(run, "board", lambda: st)
    run.STATE.halted["reason"] = None
    assert run.tick() is False
    assert run.STATE.halted["reason"] is None


def test_a_finished_lane_is_never_reopened(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="done"))
    assert run.tick() is False
    assert not [c for c in calls if c[0] == "archive"], calls
    run.STATE.opened.clear()


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
    run.STATE.opened.clear()


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
    monkeypatch.setattr(run.STATE, "snap_dir", str(snaps))

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
    run.STATE.opened.clear()
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
    monkeypatch.setattr(run.STATE, "snap_dir", str(tmp_path / "snapshots"))
    reading = tmp_path / "snapshots" / "lane-1-workdir-at-open.md"
    seen = []

    def kb(*a, **k):
        calls.append(a)
        if a[:1] == ("show",):
            return _PARKED_SHOW
        if a and a[0] == "unblock" and a[1] == "id-I":
            seen.append(reading.exists())
        return ""

    monkeypatch.setattr(run, "kb", kb)
    run.tick()
    assert seen and all(seen), "root released before its work-directory reading existed"


def test_the_reading_says_when_it_was_taken_and_that_it_is_a_snapshot(monkeypatch, tmp_path):
    """Within a lane the tree changes — the C card builds, the TW card adds files — so
    the review card reads the same file the researcher did. It is correct for planning
    and wrong as a description of the tree now, and it has to say so itself: the
    filename carries `-at-open` and the file carries its timestamp."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    snaps = tmp_path / "snapshots"
    (tmp_path / "work").mkdir()
    monkeypatch.setattr(run.STATE, "snap_dir", str(snaps))
    run.open_lane(_state(), 1)
    text = (snaps / "lane-1-workdir-at-open.md").read_text()
    assert "SNAPSHOT, not a live view" in text
    assert "git status" in text, "it must say how to get the current state"
    assert "Taken 20" in text, "and when it was taken"


def test_a_card_the_lane_archives_reads_as_archived_in_its_state(monkeypatch, tmp_path):
    """open_lane archives TI and RVc on a lane without integration tests; later steps
    of the same open read the same state, so the archive must show there too."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state()
    run.open_lane(st, 1)
    assert st[lanes.card_title("RVc", 1)]["status"] == "archived"
    assert st[lanes.card_title("TI", 1)]["status"] == "archived"


def test_a_lane_the_driver_refuses_is_neither_pruned_nor_released(monkeypatch, tmp_path):
    """A root filed against another run must not start: its worker would write where
    nothing reads. The refusal comes before any archive, link or snapshot."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="blocked"))
    monkeypatch.setattr(run, "lane_paths_agree", lambda state, lane: False)
    assert run.tick() is True
    assert [c for c in calls if c[0] in ("unblock", "archive", "link", "unlink")] == [], calls
    assert not os.path.exists(os.path.join(str(tmp_path), "snapshots", "lane-1.md"))
    # Refused once, then halted: the refusal repeated every tick and never stopped.
    assert "different run" in run.STATE.halted["reason"]
    assert [c[2] for c in calls if c[0] == "comment"] == [
        c[2] for c in calls if c[0] == "comment" and c[2].startswith("ESCALATION")], calls
    assert [c for c in calls if c[0] == "comment"], calls


def test_a_restarted_driver_rejoins_a_lane_it_already_opened(monkeypatch, tmp_path):
    """`_OPENED` is per process. A restart must not re-open a lane whose opening is
    already on this run's record: that would rewrite the snapshots a running card
    reads and post the lane comment twice."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "BOARD", "b")
    (tmp_path / "runs" / "chain.jsonl").write_text('{"event": "lane_open", "lane": 1}\n')
    assert run.open_lane(_state(), 1) == "open"
    assert calls == [], calls
    assert not os.path.exists(os.path.join(str(tmp_path), "snapshots", "lane-1.md"))


def test_an_escalation_stops_the_driver_on_the_next_tick(monkeypatch, tmp_path):
    """escalate() records the halt but runs inside a tick that goes on; the next tick
    must report it, or the driver drives on past a lane that cannot advance."""
    halt_check = run.halt_if_exhausted
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "halt_if_exhausted", halt_check)
    monkeypatch.setattr(run, "_exhaustion_event", lambda card_id, events=None: None)
    monkeypatch.setattr(run.STATE, "halted", {"reason": None})
    monkeypatch.setattr(run.STATE, "escalated", set())
    run.escalate("id-Gp", "Gp1", "plan rounds exhausted")
    assert run.tick() is True


def test_a_refile_that_fails_midway_leaves_no_state_from_the_previous_run(monkeypatch, tmp_path):
    """mint_run switches the run before the cards are filed. If filing then raises,
    the previous run's opened lanes must already be forgotten, or the next tick treats
    the new run's lane as open and releases its root without a snapshot."""
    import file_lanes
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "armed_ideas", lambda st: [(1, "## Idea 1: x\n", "t_idea")])
    monkeypatch.setattr(run, "validate_armed", lambda armed: True)
    monkeypatch.setattr(card_render, "read_board", lambda d: {"lanes": 1})
    monkeypatch.setattr(run, "board", lambda: {})
    monkeypatch.setattr(run, "mint_run", lambda key, armed: None)

    def fail(*a, **k):
        raise RuntimeError("hermes kanban create failed")

    monkeypatch.setattr(file_lanes, "file_board", fail)
    run.STATE.opened.add(1)
    run.STATE.timed.add(1)
    try:
        run.adopt_and_refile({})
    except RuntimeError:
        pass
    assert not run.STATE.opened and not run.STATE.timed


def test_a_refile_that_fails_after_minting_halts_naming_the_empty_run(monkeypatch, tmp_path):
    """`current` already names the new run when filing raises, and the armed Triage
    card is already archived — so the halt cannot say "re-arm the idea": there is no
    card left to arm. It names the reset sequence, and lands in the new run."""
    import file_lanes
    import pytest
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "runs" / "current"))
    for name in ("snap_dir", "timing_path", "cards_dir", "verdicts_path"):
        monkeypatch.setattr(run.STATE, name, getattr(run.STATE, name))   # mint_run moves them
    monkeypatch.setattr(run.STATE, "run_dir_seen", {"path": None})
    monkeypatch.setattr(run, "armed_ideas", lambda st: [(1, "## Idea 1: x\n", "t_idea")])
    monkeypatch.setattr(run, "validate_armed", lambda armed: True)
    monkeypatch.setattr(card_render, "read_board", lambda d: {"lanes": 1})
    monkeypatch.setattr(run, "board", lambda: {})

    def fail(*a, **k):
        raise RuntimeError("hermes kanban create failed")

    monkeypatch.setattr(file_lanes, "file_board", fail)
    with pytest.raises(RuntimeError):
        run.adopt_and_refile({})
    key = run._read_current_run()
    reason = run.STATE.halted["reason"]
    # The arm mint uses the minted-run idiom every producer shares, not a
    # board-named id — pin it against the one place that shape lives.
    assert file_lanes.RUN_ID_RE.fullmatch(key) and key in reason
    assert "hermes kanban create failed" in reason
    assert "reset.sh" in reason and "create-board.sh" in reason
    assert "re-arm" not in reason
    halt = tmp_path / "runs" / key / "halt.txt"
    assert "hermes kanban create failed" in halt.read_text()


def _current_run(monkeypatch, tmp_path, run_id="b-20260913-134352"):
    runs = tmp_path / "runs"
    (runs / run_id).mkdir(parents=True, exist_ok=True)
    (runs / "current").write_text(run_id + "\n")
    monkeypatch.setattr(run, "RUNS_ROOT", str(runs))
    monkeypatch.setattr(run, "CURRENT_RUN", str(runs / "current"))
    monkeypatch.setattr(run.STATE, "run_dir", str(runs / run_id))
    return run_id


def test_a_restart_onto_a_run_with_no_cards_halts_instead_of_idling(monkeypatch, tmp_path):
    """A restart after a failed refile rejoins the empty run: no lane card to drive, no
    Triage card to arm, and tick() returned False for ever."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    run_id = _current_run(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "board", lambda: {})
    assert run.tick() is True
    assert run_id in run.STATE.halted["reason"]
    assert "reset.sh" in run.STATE.halted["reason"]


def test_a_board_waiting_for_its_first_idea_is_not_an_empty_run(monkeypatch, tmp_path):
    """create-board.sh mints a run and files the parked lanes plus a Triage card per
    idea: a board between create-board and arming holds both, and must not halt."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    _current_run(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="blocked"))
    run.tick()
    assert run.STATE.halted["reason"] is None
    idea = {"Idea 1: is_even": {"id": "t_idea", "status": "triage", "title": "Idea 1: is_even",
                                "body": "RAW IDEA for lane 1 — human input"}}
    monkeypatch.setattr(run, "board", lambda: idea)
    assert run.tick() is False
    assert run.STATE.halted["reason"] is None


def _gate_waiting(monkeypatch, tmp_path, calls, clock, msgs):
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "board", lambda: _state(root_status="done"))
    monkeypatch.setattr(run.time, "time", lambda: clock[0])
    monkeypatch.setattr(run, "gate_action", lambda *a: msgs[0])


def test_a_gate_waiting_ten_minutes_on_the_same_reason_halts(monkeypatch, tmp_path):
    """minimal-development ...-135050: `Gc1: waiting: final review verdict` logged
    once, its parents done, and the run killed by hand. A verdict the gate cannot read
    will not become readable by waiting."""
    calls, clock = [], [1000.0]
    _gate_waiting(monkeypatch, tmp_path, calls, clock,
                  ["waiting: final review verdict = ''"])
    assert run.tick() is False
    clock[0] += run.GATE_WAIT_S - 1
    assert run.tick() is False
    assert run.STATE.halted["reason"] is None
    clock[0] += 1
    assert run.tick() is True
    assert "Gi1" in run.STATE.halted["reason"]
    assert "verdict unreadable" not in run.STATE.halted["reason"]   # Gi waits on no verdict
    assert [c for c in calls if c[0] == "comment" and c[1] == "id-Gi"
            and c[2].startswith("ESCALATION")], calls
    run.STATE.opened.clear()


def test_a_gate_wait_halt_does_not_spend_the_gates_rework_escalation(monkeypatch, tmp_path):
    """escalate() comments once per key, rebuilt from the ledger on restart. The wait
    halt shares the gate's code with "rework rounds exhausted", so under one key a
    genuine exhaustion after the restart would halt without its comment or record."""
    calls, clock = [], [1000.0]
    _gate_waiting(monkeypatch, tmp_path, calls, clock,
                  ["waiting: final review verdict = ''"])
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "runs" / "verdicts.jsonl"))
    run.tick()
    clock[0] += run.GATE_WAIT_S
    assert run.tick() is True
    run.STATE.escalated.clear()
    run.STATE.halted["reason"] = None
    run.rejoin_chain()
    calls.clear()
    run.escalate("id-Gi", "Gi1", "idea rework rounds exhausted")
    assert [c for c in calls if c[0] == "comment" and "rounds exhausted" in c[2]], calls
    run.STATE.opened.clear()


def test_only_a_verdict_gate_calls_its_wait_an_unreadable_verdict():
    """Keyed on the gate, not the message: a refined.md path can contain "verdict"."""
    gi = run.gate_wait_reason("Gi1: idea gate", "waiting: no refined idea at "
                              "/b/runs/verdict-study/artifacts/lane-1/refined.md", "gi")
    gc = run.gate_wait_reason("Gc1: code gate", "waiting: final review verdict = ''", "gc")
    assert "verdict unreadable" not in gi
    assert "verdict unreadable" in gc


def test_a_gate_whose_waiting_reason_changes_restarts_its_clock(monkeypatch, tmp_path):
    calls, clock, msgs = [], [1000.0], ["waiting: refined idea missing section(s): Findings"]
    _gate_waiting(monkeypatch, tmp_path, calls, clock, msgs)
    run.tick()
    clock[0] += run.GATE_WAIT_S - 60
    msgs[0] = "waiting: refined idea Findings section is empty — no environment facts"
    run.tick()
    clock[0] += 120
    assert run.tick() is False
    assert run.STATE.halted["reason"] is None
    clock[0] += run.GATE_WAIT_S
    assert run.tick() is True
    assert "Findings section is empty" in run.STATE.halted["reason"]
    run.STATE.opened.clear()


def test_a_lane_card_someone_else_archived_halts_naming_it(monkeypatch, tmp_path):
    """`list --json` leaves archived cards out, so an archived parent reads as not
    done and its children wait with nothing in the log. open_lane archives only the
    lane's optional cards; any other card missing is somebody else's doing."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state(root_status="done")
    del st[lanes.card_title("RVp", 1)]
    monkeypatch.setattr(run, "board", lambda: st)
    assert run.tick() is True
    assert "RVp1" in run.STATE.halted["reason"]
    assert [c for c in calls if c[0] == "comment" and c[2].startswith("ESCALATION")], calls
    run.STATE.opened.clear()


def test_the_cards_a_lane_prunes_itself_are_not_missing(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "lane_options",
                        lambda lane: {"integration-tests": False, "unit-tests": False,
                                      "refinement": False, "auto-gates": [],
                                      "idea": "## Idea 1: is_even\n"})
    st = _state(root_status="done")
    for code in ("I", "Gi", "TW", "TI", "RVc"):
        del st[lanes.card_title(code, 1)]
    assert run.missing_lane_card(st) == (None, None)


def test_the_deadman_survives_a_failed_list_and_notifies_once_per_stuck_set(monkeypatch):
    """The deadman ran outside the loop's try: one failed `list` ended a serve driver.
    And it notified on every 20 s tick for the same two stuck cards."""
    notified, logged = [], []
    monkeypatch.setattr(run, "log", logged.append)
    monkeypatch.setattr(run, "notify_deadman", lambda st: notified.append(sorted(st)))
    monkeypatch.setattr(run.STATE, "deadman_stuck", [frozenset()])

    def failing_board():
        raise RuntimeError("kanban list failed")

    monkeypatch.setattr(run, "board", failing_board)
    run.deadman_check()                                   # must not raise
    stuck = {t: {"id": t, "status": "blocked"} for t in ("a", "b")}
    monkeypatch.setattr(run, "board", lambda: stuck)
    monkeypatch.setattr(run, "block_origin", lambda c: "judge_budget")
    monkeypatch.setattr(run, "is_parked", lambda c: False)
    run.deadman_check()
    run.deadman_check()
    assert len(notified) == 1, notified


def test_a_rejoin_still_refuses_a_lane_filed_against_another_run(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    monkeypatch.setattr(run, "BOARD", "b")
    (tmp_path / "runs" / "chain.jsonl").write_text('{"event": "lane_open", "lane": 1}\n')
    monkeypatch.setattr(run, "lane_paths_agree", lambda state, lane: False)
    assert run.open_lane(_state(), 1) == "mismatch"


def test_an_empty_result_on_a_revision_card_is_noted(monkeypatch):
    logged = []
    monkeypatch.setattr(run, "log", logged.append)
    monkeypatch.setattr(run.STATE, "empty_result_noted", set())
    run.note_empty_results({"C1-rev-1: code revision round 1 - lane 1":
                            {"id": "t_rev", "status": "done", "result": ""}})
    assert logged and "C1-rev-1" in logged[0], logged


def test_a_deadman_that_cannot_write_its_note_does_not_end_the_driver(monkeypatch, tmp_path):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "gone"))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "block_origin", lambda c: "judge_budget")
    monkeypatch.setattr(run, "is_parked", lambda c: False)
    run.notify_deadman({"a": {"id": "a", "status": "blocked"}})      # must not raise


def test_a_halt_stops_the_loop_before_it_can_refile(monkeypatch):
    """A halt recorded mid-tick must end the driver before an armed idea is adopted,
    or the new run is minted and then abandoned by the exit that follows."""
    import inspect
    src = inspect.getsource(run.main)
    assert src.index('if STATE.halted["reason"]:') < src.index("adopt_and_refile(")


def test_a_halt_with_nothing_stuck_sends_no_deadman(monkeypatch, tmp_path):
    """The halt path calls the deadman too; with no card waiting on a human it must
    stay quiet rather than announce '0 cards awaiting human input'."""
    logged = []
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "log", logged.append)
    monkeypatch.setattr(run, "block_origin", lambda c: "other")
    monkeypatch.setattr(run, "is_parked", lambda c: False)
    run.notify_deadman({"a": {"id": "a", "status": "blocked"}})
    assert logged == [] and not (tmp_path / "deadman.txt").exists()


def test_a_live_rework_round_is_held_by_the_graph_not_by_a_dependency_block(monkeypatch, tmp_path):
    """`block --kind dependency` routes to `todo` (kanban_db._route_block) and
    recompute_ready promotes it straight back once the parents are done, so it never
    held anything; and it is refused on a `todo` card. The graph holds the round: Gp
    waits for the plan round, TW waits for Gp, P waits for the idea gate's verdict."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    st = _state(root_status="done")
    for code in ("Gi", "RVp"):
        st[lanes.card_title(code, 1)]["status"] = "done"
    st["P1-rev-1: plan revision - lane 1"] = {"id": "id-rev", "status": "running",
                                              "title": "P1-rev-1: plan revision - lane 1"}
    st[lanes.card_title("TW", 1)]["status"] = "ready"
    monkeypatch.setattr(run, "board", lambda: st)
    run.tick()
    assert not [c for c in calls if c[:1] == ("block",)], calls
    graph = {t: parents for t, parents, _k, _l in run.lane_graph(st)}
    assert "P1-rev-1" in graph[lanes.card_title("Gp", 1)]
    assert graph[lanes.card_title("TW", 1)] == ["Gp1"]
    # the idea loop: P is held by the gate's REWORK while the re-gate is unfinished
    st[lanes.card_title("Gi", 1)].update(result="REWORK: name the input type", completed_at=10)
    st["I1-rev-1: refine idea revision - lane 1"] = {
        "id": "id-irev", "status": "done", "completed_at": 20,
        "title": "I1-rev-1: refine idea revision - lane 1"}
    st["Gi1-r2: accept idea - lane 1"] = {"id": "id-gi2", "status": "blocked",
                                          "title": "Gi1-r2: accept idea - lane 1"}
    assert run.held_by_verdict(st, "p", 1) is True


def test_a_restart_onto_a_partly_filed_run_halts_instead_of_idling(monkeypatch, tmp_path):
    """Filing died after I1 and Gi1: a lane is counted by its P card, so no lane is ever
    opened or checked, and the lane cards that do exist kept the empty-run halt away."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    run_id = _current_run(monkeypatch, tmp_path)
    st = {t: c for t, c in _state(root_status="blocked").items()
          if t.split(":")[0] in ("I1", "Gi1")}
    monkeypatch.setattr(run, "board", lambda: st)
    assert run.tick() is True
    assert run_id in run.STATE.halted["reason"] and "reset.sh" in run.STATE.halted["reason"]


def test_an_idea_titled_like_a_card_is_not_a_partly_filed_run(monkeypatch, tmp_path):
    calls = []
    _board_env(monkeypatch, tmp_path, calls)
    _current_run(monkeypatch, tmp_path)
    idea = {"Idea2: screener": {"id": "t_idea", "status": "triage", "title": "Idea2: screener"}}
    assert run.empty_run_reason(idea) is None


def test_auto_gates_is_read_from_the_manifest_not_the_lane_options(monkeypatch):
    """It stopped being per-lane on 2026-09-16, and every read that still went through
    `lane_options` raised `KeyError: 'auto-gates'` until the board halted."""
    import inspect
    import run as r
    for fn in (r.open_lane, r._gate_action, r.gate_action, r.write_summary):
        src = inspect.getsource(fn)
        assert "opts['auto-gates']" not in src and 'opts.get("auto-gates")' not in src, fn.__name__
    monkeypatch.setattr(r, "manifest", lambda: {"auto-gates": ["Gi"]})
    assert r.auto_gates() == ["Gi"]
    monkeypatch.setattr(r, "manifest", lambda: {})
    assert r.auto_gates() == []


def test_opening_a_lane_never_pairs_its_model_with_the_boards_provider(monkeypatch, tmp_path):
    """open_lane re-pointed with the RESOLVED options, which fill a missing provider
    from the board: a lane naming only a local model on a board whose provider is a
    cloud one was re-pointed at that cloud backend (review Important 8)."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    monkeypatch.setattr(run, "manifest", lambda: {"model": "board-model",
                                                  "provider": "cloud-provider"})
    monkeypatch.setattr(run, "lane_options", lambda lane: {
        "integration-tests": False, "unit-tests": True, "auto-gates": [],
        "model": "qwen38-27b", "provider": "cloud-provider", "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
    run.tick()
    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
    assert sets["id-C"] == ("qwen38-27b",), sets
    run.STATE.opened.clear()


def test_a_per_lane_model_array_does_not_re_point_a_card_that_already_carries_it(
        monkeypatch, tmp_path):
    """open_lane's guard compares the lane's pair against the BOARD's — and the board's
    answer is the LANE's entry of a per-lane array. Read raw, the comparison handed a
    LIST to `_model_pair` on both sides (`--model <list>`), which no scalar pair can
    ever equal: every card of every lane was sent to `set-model` although filing (which
    indexes the same array, `file_lanes.file_board`) had already put it on that lane's
    model. `set-model <id> <list>` is exactly what `subprocess` refuses."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 2, "model": ["m1", "m2"],
                                                  "provider": ["p1", "p2"]})
    # the lane's header names the same pair the board's array gives it: already right
    monkeypatch.setattr(run, "lane_model_opts",
                        lambda lane: {"model": f"m{lane}", "provider": f"p{lane}"})
    run.tick()
    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
    assert sets == {}, sets
    run.STATE.opened.clear()


def test_a_per_lane_model_array_still_re_points_a_lane_whose_header_differs(
        monkeypatch, tmp_path):
    """The other half of the same guard: a header that names its OWN model must still
    be re-pointed — resolving the array must not turn the comparison into a skip that
    never fires."""
    calls = []
    _board_env(monkeypatch, tmp_path, calls, it=False)
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 2, "model": ["m1", "m2"],
                                                  "provider": ["p1", "p2"]})
    monkeypatch.setattr(run, "lane_model_opts",
                        lambda lane: {"model": "header-model"})
    run.tick()
    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
    for cid in ("id-I", "id-P", "id-TW", "id-C", "id-RVa"):
        assert sets[cid] == ("header-model",), (cid, sets)
    for a in [c for c in calls if c[0] == "set-model"]:
        assert all(isinstance(t, str) for t in a[1:]), a
    run.STATE.opened.clear()
