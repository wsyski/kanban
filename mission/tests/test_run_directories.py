"""Per-run directories, and the deletions they retire.

Every run gets `runs/<run-id>/` and nothing ever removes one. That is not a
filing preference: three separate failures were all "the previous run's state was
still there, or was cleared at the wrong moment", and each was handled by deleting
something at the right time —

  * `clear_run_state` at the refile (stale per-card JSONLs, timing, hand-offs),
  * `clear_lane_outputs` at a lane's first card, because a restart or a
    hand-unblocked root skips the refile and a leftover `refined.md` passes the Gi
    gate's STRUCTURE check, so the plan is built on the old idea,
  * `snapshot_run_evidence` rotating what was about to be cleared.

A new directory cannot contain an old run's refined idea, so all three go. The
invariant moves from "we remembered to delete it" to "it was never the same path",
which is why these tests pin the paths rather than the absence of files.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import run


def test_a_lanes_hand_offs_live_under_its_own_run():
    a = file_lanes.lane_paths("/repo", "b", 1, "b-20260912-090000")
    z = file_lanes.lane_paths("/repo", "b", 1, "b-20260912-100000")
    assert a["<REFINED>"] != z["<REFINED>"]
    assert "/runs/b-20260912-090000/" in a["<REFINED>"]
    for key in ("<IDEA>", "<REFINED>", "<PLAN>"):
        assert "/current/" not in a[key], a[key]


def test_a_run_id_is_never_resolved_through_current():
    """`current` is a pointer for humans and tools. If a card body resolved
    through it, a worker orphaned by run N would write into run N+1's directory
    the moment it was repointed — the overwrite this layout prevents (F2) — and
    `git diff --cached -- runs/...` would not match through the alias (E14)."""
    body_paths = list(file_lanes.lane_paths("/repo", "b", 1, "rid").values())
    body_paths.append(file_lanes.run_dir("/repo", "b", "rid"))
    assert all("current" not in p for p in body_paths), body_paths


def test_use_run_moves_every_per_run_path_together(monkeypatch, tmp_path):
    """One call, or a path is left pointing at the previous run. VERDICTS_PATH and
    TIMING_PATH were computed at import next to the others and are easy to miss."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    run.use_run("r1")
    for path in (run.RUN_DIR, run.SNAP_DIR, run.TIMING_PATH, run.CARDS_DIR,
                 run.VERDICTS_PATH):
        assert path.startswith(os.path.join(str(tmp_path), "r1")), path


def test_mint_run_creates_the_directory_and_points_current(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    run.mint_run("r1", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert os.path.isdir(tmp_path / "r1")
    assert (tmp_path / "current").read_text().strip() == "r1"
    assert run._read_current_run() == "r1"


def test_a_new_run_opens_its_own_timing_segment(monkeypatch, tmp_path):
    """record_timing writes its run-boundary marker once per PROCESS, and a serve-mode
    driver answers many ideas. With the flag left standing, the second run's
    timing.jsonl opened with no boundary at all, so the report's "latest segment"
    split (which is how a file covering several processes is read) had nothing to
    split on."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    run.record_timing._started = True          # the first run already wrote its marker
    run.mint_run("r2", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert not hasattr(run.record_timing, "_started")


def test_minting_a_second_run_leaves_the_first_alone(monkeypatch, tmp_path):
    """The whole point: last run's evidence survives the next arm, so `run, audit,
    fix, run again` can compare. Before this, the next run deleted the numbers the
    auditor had just reported on."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    run.mint_run("r1", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    (tmp_path / "r1" / "chain.jsonl").write_text('{"kind":"run"}\n')
    (tmp_path / "r1" / "driver.log").write_text("[00:00:00] LANE 1 open\n")
    run.mint_run("r2", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert (tmp_path / "r1" / "chain.jsonl").exists()
    assert (tmp_path / "r1" / "driver.log").exists()
    assert run.RUN_DIR == str(tmp_path / "r2")
    # r2 holds only what r2 itself wrote (its own driver.log, from the mint) —
    # never r1's chain: these are fresh paths, not cleared ones.
    assert os.listdir(tmp_path / "r2") == ["driver.log"]
    assert "r1" not in (tmp_path / "r2" / "driver.log").read_text()


def test_the_driver_retired_every_clearing_function():
    """Named, so a future re-introduction has to argue with this test."""
    for gone in ("clear_run_state", "snapshot_run_evidence", "clear_lane_outputs"):
        assert not hasattr(run, gone), gone


def test_the_lock_is_the_boards_not_the_runs(monkeypatch, tmp_path):
    """One driver per board answers many ideas, so its lock cannot live in a
    directory minted per run."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.use_run("r1")
    run.acquire_lock()
    assert (tmp_path / "driver.lock").exists()
    assert not (tmp_path / "r1" / "driver.lock").exists()


def test_a_restart_rejoins_the_run_it_finds(monkeypatch, tmp_path):
    """The #31 guarantee now rests on minting being per ARMED IDEA, not per driver
    start: a restart that minted would leave the already-filed cards pointing at
    the previous run's hand-off paths. Import-time resolution reads runs/current
    and mints nothing."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    (tmp_path / "r1").mkdir()
    (tmp_path / "current").write_text("r1\n")
    run.use_run(run._read_current_run())               # what import does
    assert run.RUN_DIR == str(tmp_path / "r1")
    assert sorted(os.listdir(tmp_path)) == ["current", "r1"]   # no second run


def test_minting_requires_an_armed_idea(monkeypatch, tmp_path):
    """"One run per armed idea" was a convention pinned by reading the source, which
    a second call added inside the refile would have satisfied. It is now a
    precondition: a caller with no armed idea has no run to mint, so a mint on driver
    start or restart cannot compile past this."""
    import pytest
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    monkeypatch.setattr(run, "log", lambda m: None)
    with pytest.raises(ValueError, match="no armed idea"):
        run.mint_run("r1", [])
    assert not os.path.exists(tmp_path / "r1"), "nothing is created by a refused mint"
    assert not os.path.exists(tmp_path / "current")


def test_minting_the_current_run_again_is_refused(monkeypatch, tmp_path):
    """Two sets of cards filed into one run's directory is the old flat layout with
    extra steps, and the second set would overwrite the first's hand-offs."""
    import pytest
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    monkeypatch.setattr(run, "log", lambda m: None)
    armed = [(1, "## Idea\n\n### Done means\n- x\n", "c1")]
    run.mint_run("r1", armed)
    with pytest.raises(ValueError, match="already the current run"):
        run.mint_run("r1", armed)


def test_the_refile_is_still_the_only_caller():
    """Weaker than the precondition above and kept as a statement of intent: the
    precondition is what holds if this ever stops being true."""
    import inspect
    callers = [ln.strip() for ln in inspect.getsource(run).splitlines()
               if "mint_run(" in ln and "def mint_run" not in ln]
    assert len(callers) == 1, callers
    assert callers[0].startswith("mint_run(key, armed)"), callers


# ---- a restart is a new PROCESS, so prove it at import ---------------------

def _driver_env(board_root, slug="b"):
    env = dict(os.environ, BOARD=slug)
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    env["PYTHONPATH"] = os.path.join(os.path.dirname(__file__), "..")
    # run.py resolves REPO from its own location, so the board has to live there;
    # the probe reads the module's own idea of the paths instead of guessing.
    return env


def _probe(tmp_path, slug, expr):
    """Import run.py in a FRESH interpreter with REPO pointed at tmp_path, and
    print `expr`. A restart is a new process: patching a live module cannot show
    what import itself decides."""
    import subprocess
    import textwrap
    mission = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {mission!r})
        os.environ["BOARD"] = {slug!r}
        import run
        run.REPO = {str(tmp_path)!r}
        run.BOARD_DIR = os.path.join(run.REPO, "boards", {slug!r})
        run.RUNS_ROOT = os.path.join(run.BOARD_DIR, "runs")
        run.CURRENT_RUN = os.path.join(run.RUNS_ROOT, "current")
        run.use_run(run._read_current_run())
        print({expr})
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=_driver_env(tmp_path, slug))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _board(tmp_path, current=None, runs=()):
    board = tmp_path / "boards" / "b"
    (board / "runs").mkdir(parents=True)
    for rid in runs:
        (board / "runs" / rid).mkdir()
    if current is not None:
        (board / "runs" / "current").write_text(current + "\n")
    return board


def test_a_fresh_process_rejoins_the_run_current_names(tmp_path):
    board = _board(tmp_path, current="b-20260912-090000", runs=["b-20260912-090000"])
    assert _probe(tmp_path, "b", "run.RUN_DIR") == \
        str(board / "runs" / "b-20260912-090000")


def test_a_restart_mints_nothing(tmp_path):
    """The failure this guards: a driver that minted on start would leave every
    already-filed card's hand-off paths pointing at the previous run's directory,
    which nothing would then write to — and the idea gate would wait forever for a
    refined.md that is being written one directory over."""
    board = _board(tmp_path, current="r1", runs=["r1"])
    before = sorted(os.listdir(board / "runs"))
    _probe(tmp_path, "b", "run.RUN_DIR")
    assert sorted(os.listdir(board / "runs")) == before


def test_a_restart_lands_on_the_paths_already_in_the_card_bodies(tmp_path):
    """The invariant that makes minting load-bearing: what the driver writes and
    what a filed card was told to read have to be the same path."""
    import file_lanes
    _board(tmp_path, current="r1", runs=["r1"])
    in_body = file_lanes.lane_paths(str(tmp_path), "b", 1, "r1")["<REFINED>"]
    driver = _probe(tmp_path, "b",
                    'os.path.join(run.RUN_DIR, "artifacts", "lane-1", "refined.md")')
    assert driver == in_body


def test_no_current_means_no_run_yet(tmp_path):
    """A board that has been created but never armed: the driver logs and locks at
    runs/, and the first armed idea mints."""
    board = _board(tmp_path)
    assert _probe(tmp_path, "b", "run.RUN_DIR") == str(board / "runs")


def test_a_current_naming_a_missing_directory_still_resolves(tmp_path):
    """`runs/` is a human's to prune, so `current` can outlive the run it names.
    Pointing at it anyway is what makes the run recreatable; silently falling back
    to runs/ would scatter one run's files across two layouts."""
    board = _board(tmp_path, current="r-deleted-by-hand")
    assert _probe(tmp_path, "b", "run.RUN_DIR") == \
        str(board / "runs" / "r-deleted-by-hand")


def test_an_empty_or_blank_current_is_no_run(tmp_path):
    board = _board(tmp_path, current="   ")
    assert _probe(tmp_path, "b", "run.RUN_DIR") == str(board / "runs")


# ---- the invariant, enforced at runtime rather than by convention ----------

def _lane_state(run_mod, lane, run_id, repo, board):
    import file_lanes
    idea = file_lanes.lane_paths(repo, board, lane, run_id)["<IDEA>"]
    title = __import__("lanes").card_title("I", lane)
    return {title: {"id": f"id-I{lane}", "status": "ready", "title": title,
                    "body": f"INPUT: the raw idea at {idea}"}}


def test_a_lane_filed_against_another_run_is_not_opened(monkeypatch, tmp_path):
    """The guarantee that a lane cannot inherit a stale hand-off is only as good as
    the agreement between what the cards were told and where the driver writes. A run
    minted on a restart instead of at the refile breaks it silently: every hand-off
    goes where nothing reads it."""
    import run as r
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "CURRENT_RUN", str(tmp_path / "current"))
    (tmp_path / "current").write_text("r-NOW\n")
    logged = []
    monkeypatch.setattr(r, "log", lambda m: logged.append(m))

    filed_elsewhere = _lane_state(r, 1, "r-EARLIER", str(tmp_path), "b")
    assert r.lane_paths_agree(filed_elsewhere, 1) is False
    assert any("filed against a different run" in m for m in logged)

    filed_here = _lane_state(r, 1, "r-NOW", str(tmp_path), "b")
    assert r.lane_paths_agree(filed_here, 1) is True


def test_a_card_with_no_body_is_not_treated_as_drift(monkeypatch, tmp_path):
    import run as r
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "CURRENT_RUN", str(tmp_path / "current"))
    (tmp_path / "current").write_text("r1\n")
    import lanes as L
    title = L.card_title("I", 1)
    assert r.lane_paths_agree({title: {"id": "x", "title": title, "body": None}}, 1)
    assert r.lane_paths_agree({}, 1)


def test_open_lane_refuses_rather_than_writing_to_the_wrong_run(monkeypatch, tmp_path):
    """It returns 'mismatch' and writes nothing: the alternative is a lane whose
    researcher writes a refined idea the gate will never find."""
    import run as r
    import inspect
    src = inspect.getsource(r.open_lane)
    assert src.index("lane_paths_agree") < src.index("record_workdir_facts")
    assert 'return "mismatch"' in src


# ---- per-run module state must not outlive its run ------------------------

def test_a_refile_clears_the_state_that_belongs_to_one_run(monkeypatch, tmp_path):
    """A serve-mode driver answers many ideas from one process. `_DRIFT` carried the
    previous run's findings into the next run's summary — failing it on E17 for
    something that happened before it existed — and `_ANNOUNCED` is keyed by card
    TITLE, which repeats identically across runs, so a second run's human gate would
    never announce itself."""
    import inspect
    import run as r
    src = inspect.getsource(r.adopt_and_refile)
    for name in ("_DRIFT.clear()", "_ANNOUNCED.clear()", "_REPORTED.clear()",
                 "_OPENED.clear()", "_TIMED.clear()"):
        assert name in src, name


def test_drift_from_an_earlier_run_is_not_written_into_a_later_summary(monkeypatch, tmp_path):
    import run as r
    r._DRIFT.clear()
    r._DRIFT.add("the work directory moved from branch main to feature/x")
    assert sorted(r._DRIFT)
    r._DRIFT.clear()                     # what the refile does
    assert sorted(r._DRIFT) == []


def test_gate_announcements_are_keyed_by_a_title_that_repeats(monkeypatch, tmp_path):
    """Why _ANNOUNCED has to be cleared rather than left to grow: the key is not
    unique across runs."""
    import lanes as L
    assert L.card_title("Gc", 1) == L.card_title("Gc", 1)


def test_patches_land_in_the_runs_own_directory_without_a_second_timestamp():
    """The run directory already names the run; a timestamp inside it invited reading
    the inner name as a different run. And beside artifacts/, not inside — artifacts/
    holds the lane hand-offs the document chain stats, and a patch is not one."""
    import inspect
    import run as r
    src = inspect.getsource(r.preserve_artifacts)
    assert 'os.path.join(RUN_DIR, "patches")' in src
    assert "strftime" not in src
