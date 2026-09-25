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

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
import file_lanes
import run


def test_a_lanes_hand_offs_live_under_its_own_run():
    a = card_render.lane_paths("/repo", "b", 1, "b-20260912-090000")
    z = card_render.lane_paths("/repo", "b", 1, "b-20260912-100000")
    assert a["<REFINED>"] != z["<REFINED>"]
    assert "/runs/b-20260912-090000/" in a["<REFINED>"]
    for key in ("<IDEA>", "<REFINED>", "<PLAN>"):
        assert "/current/" not in a[key], a[key]


def test_a_run_id_is_never_resolved_through_current():
    """`current` is a pointer for humans and tools. If a card body resolved
    through it, a worker orphaned by run N would write into run N+1's directory
    the moment it was repointed — the overwrite this layout prevents (F2) — and
    `git diff --cached -- runs/...` would not match through the alias (E14)."""
    body_paths = list(card_render.lane_paths("/repo", "b", 1, "rid").values())
    body_paths.append(card_render.run_dir("/repo", "b", "rid"))
    assert all("current" not in p for p in body_paths), body_paths


def test_use_run_moves_every_per_run_path_together(monkeypatch, tmp_path):
    """One call, or a path is left pointing at the previous run. VERDICTS_PATH and
    TIMING_PATH were computed at import next to the others and are easy to miss."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    run.use_run("r1")
    for path in (run.STATE.run_dir, run.STATE.snap_dir, run.STATE.timing_path, run.STATE.cards_dir,
                 run.STATE.verdicts_path):
        assert path.startswith(os.path.join(str(tmp_path), "r1")), path


def test_mint_run_creates_the_directory_and_points_current(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    run.mint_run("r1", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert os.path.isdir(tmp_path / "r1")
    assert (tmp_path / "current").read_text().strip() == "r1"
    assert run._read_current_run() == "r1"


def test_a_vanished_run_directory_stops_the_board(monkeypatch, tmp_path):
    """USER RULE (2026-09-12): the board wipes nothing, in `runs/` or in `work/`.

    So when a run's own directory is gone, something ELSE removed it — a desktop file
    manager trashes the whole folder. Continuing would append this run's evidence into
    a directory recreated behind the human's back and leave `current` pointing at a run
    whose files sit in a trash can, so the driver stops and names the path instead.
    """
    import shutil
    runs, run_dir = tmp_path / "runs", tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(run, "RUNS_ROOT", str(runs))
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run.STATE, "run_dir", str(run_dir))
    monkeypatch.setattr(run.STATE, "halted", {"reason": None})
    run._remember_run_dir(str(run_dir))            # this process saw it on disk
    assert run.run_directory_is_gone() is False
    shutil.move(str(run_dir), str(tmp_path / "trash" / "r1"))   # a file manager, not us
    assert run.tick() is True                      # truthy = the serve loop halts
    assert "disappeared" in run.STATE.halted["reason"], run.STATE.halted
    assert "r1" in run.STATE.halted["reason"]
    # The note lands in runs/ itself: the run's own directory is what is missing.
    assert (runs / "halt.txt").exists()


def test_a_stale_current_pointer_does_not_stop_a_waiting_driver(monkeypatch, tmp_path):
    """`runs/current` can name a run whose folder is already in the trash — the human
    removed it before this process started. That is a stale pointer, not a
    disappearance: the driver waits for an idea, and arming one mints a fresh
    directory. Halting there would refuse to serve a board nobody has touched."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "runs" / "trashed-run"))
    run._remember_run_dir(str(tmp_path / "runs" / "trashed-run"))   # never existed
    assert run.run_directory_is_gone() is False


def test_a_board_nobody_armed_is_not_a_vanished_run(monkeypatch, tmp_path):
    """Before the first idea is armed RUN_DIR *is* RUNS_ROOT — the driver's own
    board-level state. That is a waiting driver, not a disappearance, and it must not
    halt the board."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    assert run.run_directory_is_gone() is False


def test_a_new_run_opens_its_own_timing_segment(monkeypatch, tmp_path):
    """REWRITTEN 2026-09-24 — the old form pinned the removed symbol
    `record_timing._started`; this pins the same property on `STATE.timing_started`, the
    state that replaced it.

    record_timing writes its run-boundary marker once per PROCESS, and a serve-mode
    driver answers many ideas. With the flag left standing, the second run's
    timing.jsonl opened with no boundary at all, so the report's "latest segment"
    split (which is how a file covering several processes is read) had nothing to
    split on."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    monkeypatch.setattr(run.STATE, "timing_started", [True])   # the first run wrote its marker
    run.mint_run("r2", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert run.STATE.timing_started[0] is False


def test_a_refile_does_not_carry_the_previous_runs_timing_cache(monkeypatch, tmp_path):
    """That cache is what makes record_timing log a card only when its status MOVED, and
    a refile reuses the card TITLES (I1, Gi1 …): left standing, the new run's first tick
    found a matching status for every card and logged none of them. It is run state, so
    it lives on STATE and goes with the run (2026-09-20)."""
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    run.STATE.timing_prev["I1: idea - lane 1"] = {"status": "done", "last_run": None}
    run.mint_run("r2", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    run.STATE.reset()                          # adopt_and_refile: mint, then reset
    assert run.STATE.timing_prev == {}


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
    assert run.STATE.run_dir == str(tmp_path / "r2")
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
    assert run.STATE.run_dir == str(tmp_path / "r1")
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
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(os.path.dirname(__file__), "..", d) for d in ("driver", "template")])
    # run.py resolves REPO from its own location, so the board has to live there;
    # the probe reads the module's own idea of the paths instead of guessing.
    return env


def _probe(tmp_path, slug, expr):
    """Import run.py in a FRESH interpreter with REPO pointed at tmp_path, and
    print `expr`. A restart is a new process: patching a live module cannot show
    what import itself decides."""
    import subprocess
    import textwrap
    driver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "driver")
    code = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {driver!r})
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
    assert _probe(tmp_path, "b", "run.STATE.run_dir") == \
        str(board / "runs" / "b-20260912-090000")


def test_a_restart_mints_nothing(tmp_path):
    """The failure this guards: a driver that minted on start would leave every
    already-filed card's hand-off paths pointing at the previous run's directory,
    which nothing would then write to — and the idea gate would wait forever for a
    refined.md that is being written one directory over."""
    board = _board(tmp_path, current="r1", runs=["r1"])
    before = sorted(os.listdir(board / "runs"))
    _probe(tmp_path, "b", "run.STATE.run_dir")
    assert sorted(os.listdir(board / "runs")) == before


def test_a_restart_lands_on_the_paths_already_in_the_card_bodies(tmp_path):
    """The invariant that makes minting load-bearing: what the driver writes and
    what a filed card was told to read have to be the same path."""
    import file_lanes
    _board(tmp_path, current="r1", runs=["r1"])
    in_body = card_render.lane_paths(str(tmp_path), "b", 1, "r1")["<REFINED>"]
    driver = _probe(tmp_path, "b",
                    'os.path.join(run.STATE.run_dir, "artifacts", "lane-1", "refined.md")')
    assert driver == in_body


def test_no_current_means_no_run_yet(tmp_path):
    """A board that has been created but never armed: the driver logs and locks at
    runs/, and the first armed idea mints."""
    board = _board(tmp_path)
    assert _probe(tmp_path, "b", "run.STATE.run_dir") == str(board / "runs")


def test_a_current_naming_a_missing_directory_still_resolves(tmp_path):
    """`runs/` is a human's to prune, so `current` can outlive the run it names.
    Pointing at it anyway is what makes the run recreatable; silently falling back
    to runs/ would scatter one run's files across two layouts."""
    board = _board(tmp_path, current="r-deleted-by-hand")
    assert _probe(tmp_path, "b", "run.STATE.run_dir") == \
        str(board / "runs" / "r-deleted-by-hand")


def test_an_empty_or_blank_current_is_no_run(tmp_path):
    board = _board(tmp_path, current="   ")
    assert _probe(tmp_path, "b", "run.STATE.run_dir") == str(board / "runs")


# ---- the invariant, enforced at runtime rather than by convention ----------

def _lane_state(run_mod, lane, run_id, repo, board):
    import file_lanes
    idea = card_render.lane_paths(repo, board, lane, run_id)["<IDEA>"]
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
    # The refile clears the run's own state in ONE place now (STATE.reset()), so the check
    # moved with it: the refile must call it, and it must clear each of these.
    assert "STATE.reset()" in src, "the refile must clear the run's own state"
    reset = inspect.getsource(r.RunState.reset)
    for name in ("opened", "timed", "drift", "announced", "reported"):
        assert f"self.{name}.clear()" in reset, name
    assert "self.run_finished[0] = False" in reset


def test_drift_from_an_earlier_run_is_not_written_into_a_later_summary(monkeypatch, tmp_path):
    import run as r
    r.STATE.drift.clear()
    r.STATE.drift.add("the work directory moved from branch main to feature/x")
    assert sorted(r.STATE.drift)
    r.STATE.drift.clear()                # what the refile does
    assert sorted(r.STATE.drift) == []


def test_gate_announcements_are_keyed_by_a_title_that_repeats(monkeypatch, tmp_path):
    """Why _ANNOUNCED has to be cleared rather than left to grow: the key is not
    unique across runs."""
    import lanes as L
    assert L.card_title("Gc", 1) == L.card_title("Gc", 1)


def test_patches_land_in_the_runs_own_directory(monkeypatch, tmp_path):
    """REPLACED 2026-09-24 — this test used to assert two strings in
    inspect.getsource(r.preserve_artifacts), which passes whether the copier works,
    copies nothing, or reads the wrong directory (2026-09-23 review, Critical 8). It
    now DRIVES the function: one card, one attachment, one file where it belongs — in
    runs/<run-id>/patches/, beside artifacts/ and with no second timestamp — and a
    second call that must not overwrite what the first one kept.

    The source is hermes_kanban_dir(), not a hardcoded ~/.hermes: on a host whose
    HERMES_HOME is elsewhere the literal path copied nothing and the run still reported
    complete (review Important 23)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-20260924-000000"))
    os.makedirs(r.STATE.run_dir)
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
    attachments = tmp_path / "kanban" / "boards" / "b" / "attachments" / "t_c"
    attachments.mkdir(parents=True)
    (attachments / "t_c.patch").write_text("diff --git a/x b/x\n")
    r.preserve_artifacts()
    patches = os.path.join(r.STATE.run_dir, "patches")
    assert sorted(os.listdir(patches)) == ["t_c.patch"]
    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
    # idempotent: a later, different copy of the same patch must not replace what was kept
    (attachments / "t_c.patch").write_text("diff --git a/other b/other\n")
    r.preserve_artifacts()
    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"


def test_a_run_with_no_attachments_says_so(monkeypatch, tmp_path):
    """The silent-empty case: a glob that matched nothing returned having logged
    nothing, so a run whose patches were never collected read exactly like one that had
    none (review Important 23)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
    lines = []
    monkeypatch.setattr(r, "log", lines.append)
    r.preserve_artifacts()
    assert any("no provenance patches" in m for m in lines), lines


def test_the_timing_report_is_written_again_when_the_run_finishes(monkeypatch, tmp_path):
    """The gate copy stops two minutes short: it shows the code gate itself as `blocked`,
    which is true when it is written and misleading afterwards."""
    import inspect
    import run as r
    assert "write_timing_report(lane, final=True)" in inspect.getsource(r.finish_run)
    written = []
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "log", lambda m: None)
    import subprocess
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "report", "stderr": ""})())
    r.STATE.timed.clear()
    r.write_timing_report(1)
    r.write_timing_report(1)                      # the gate holds for ticks; one copy only
    assert open(tmp_path / "timing-report-lane-1.txt").read() == "report"
    r.write_timing_report(1, final=True)          # the run's own end rewrites it
    assert 1 in r.STATE.timed
    r.STATE.timed.clear()


def test_the_summary_is_never_visible_half_written(monkeypatch, tmp_path):
    """os.replace is atomic: the file holds the old content or the new, never half.
    Not cosmetic — run-audit.py json.loads this file, so one torn write made every
    later audit of that run die (review Critical 4)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
    monkeypatch.setattr(r, "commit_target", lambda: "main")
    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})

    def boom(obj, f, **kw):
        f.write('{"wall_min": 13.1, "agent_w')
        raise RuntimeError("killed mid-write")

    monkeypatch.setattr(r.json, "dump", boom)
    with pytest.raises(RuntimeError):
        r.write_summary({})
    assert not os.path.exists(os.path.join(str(tmp_path), "run-summary.json"))


def test_the_summary_marks_minutes_it_could_not_read(monkeypatch, tmp_path):
    """A refused runs CLI recorded agent_min 0.0 as fact in a file written once
    (review Important 15)."""
    import json as _json
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
    monkeypatch.setattr(r, "commit_target", lambda: "main")
    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
    monkeypatch.setattr(r.runs_util, "board_runs", lambda b, cid: None)
    r.write_summary({"C1: implement - lane 1": {"id": "t_c", "status": "done"}})
    with open(os.path.join(str(tmp_path), "run-summary.json")) as f:
        row = _json.load(f)["cards"]["C1: implement - lane 1"]
    assert row["runs_unreadable"] is True and row["agent_min"] is None, row


# ---- the per-card log, the once-per-condition lines, and the temp writers ---

def test_a_transition_is_recorded_when_the_runs_cli_refuses(monkeypatch, tmp_path):
    """Task 17 gave the card log `runs: null` for a refused runs CLI, and record_timing
    skipped card_log entirely on the same condition: three ticks with board_runs -> None
    put nothing in runs/cards/<id>.jsonl at all, so the card's only record of the
    transition was the timing cache — and that cache advances on the refused tick anyway,
    so the card was never logged, then or later."""
    import json as _json
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r.STATE, "cards_dir", str(tmp_path / "cards"))
    monkeypatch.setattr(r.STATE, "timing_path", str(tmp_path / "timing.jsonl"))
    monkeypatch.setattr(r.STATE, "timing_started", [True])
    monkeypatch.setattr(r.STATE, "timing_prev", {})
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "kb", lambda *a, **k: "")
    monkeypatch.setattr(r.runs_util, "board_runs", lambda board, cid: None)
    state = {"C1: implement - lane 1": {"id": "t_c", "status": "done"}}
    for _ in range(3):
        r.record_timing(state)
    path = tmp_path / "cards" / "t_c.jsonl"
    assert path.exists(), "the card's transition was recorded nowhere"
    recs = [_json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(recs) == 1, recs
    assert recs[0]["id"] == "t_c" and recs[0]["status"] == "done", recs
    assert recs[0]["runs"] is None, recs
    # the cache moved on, so the card is not logged again until its status moves
    assert r.STATE.timing_prev["C1: implement - lane 1"]["status"] == "done"


def test_a_held_code_gate_says_the_missing_patches_note_once_per_lane(monkeypatch, tmp_path):
    """_gate_action calls preserve_artifacts on every tick a gate waits on a person, and
    the note was unconditional: one identical line per tick per lane for as long as the
    human takes, and it matches no error vocabulary, so nothing bounded it either."""
    import lanes as L
    import run as r
    GC1, GC2 = L.card_title("Gc", 1), L.card_title("Gc", 2)
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-1"))
    monkeypatch.setattr(r.STATE, "announced", set())
    monkeypatch.setattr(r.STATE, "snap_dir", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "lane_options", lambda lane: {"auto-gates": [], "max-reworks": 2})
    monkeypatch.setattr(r, "latest_verdict_card",
                        lambda state, lane, prefix, final_code=None: ({"id": "t_rva"}, "PASS: ok"))
    monkeypatch.setattr(r, "staged_files", lambda: [])
    monkeypatch.setattr(r, "write_timing_report", lambda lane, final=False: None)
    monkeypatch.setattr(r, "commit_target", lambda: "here")
    monkeypatch.setattr(r, "apply_comment_verdict", lambda *a, **k: None)
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
    lines = []
    monkeypatch.setattr(r, "log", lines.append)
    state = {GC1: {"id": "t_gc1", "status": "blocked"},
             GC2: {"id": "t_gc2", "status": "blocked"}}
    for _ in range(3):                       # the gate holds: three ticks of lane 1
        r._gate_action(state, GC1, "gc", 1)
    assert len([m for m in lines if "no provenance patches" in m]) == 1, lines
    r._gate_action(state, GC2, "gc", 2)      # lane 2's own code gate is its own line
    assert len([m for m in lines if "no provenance patches" in m]) == 2, lines


def test_a_sustained_index_read_failure_is_said_once_and_is_no_e2_chain(monkeypatch, tmp_path):
    """The index read is retried every tick and the line matches the auditor's error
    vocabulary, so a sustained failure wrote a WARNING per tick and each one became
    ('ERROR', 'E2', 'log line: WARNING: cannot read the index …'). Said once per
    condition, with the file's own `(non-fatal)` marker for a line the driver carries
    on from — the marker E2 already reads."""
    import importlib.util
    import subprocess
    import run as r
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "RUNS_ROOT", str(tmp_path / "boards" / "b" / "runs"))
    monkeypatch.setattr(r.STATE, "index_read_failed", set())
    lines = []
    monkeypatch.setattr(r, "log", lines.append)

    class R:
        returncode = 1
        stdout = ""
        stderr = "fatal: not a git repository"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    for _ in range(3):
        r.unstage_run_paths()
    found = [m for m in lines if "cannot read the index" in m]
    assert len(found) == 1, found
    # the same shape run-audit reads out of the per-run driver.log
    log_text = "\n".join(f"[21:21:0{i}] {m}" for i, m in enumerate(lines))
    spec = importlib.util.spec_from_file_location(
        "run_audit_e2", os.path.join(os.path.dirname(__file__), "..", "driver", "run-audit.py"))
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    e2 = [f for f in ra.driver_findings(log_text, auto_gates=())[0]
          if "cannot read the index" in f[2]]
    assert e2 == [], e2


def test_the_writers_do_not_follow_a_symlink_planted_at_the_temp_path(monkeypatch, tmp_path):
    """Every atomic writer built its temp name from its target (`<target>.tmp`) and opened
    it with a plain open("w"): a symlink planted at that name — by a worker in the work
    directory, or a person — is followed and the file it points at truncated with
    driver-chosen content. mkstemp opens with O_EXCL in the SAME directory, so the planted
    name is never used and os.replace still swaps atomically."""
    import json as _json
    import run as r
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n")
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(r, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(r, "commit_target", lambda: "main")
    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
    monkeypatch.setattr(r, "workdir_facts", lambda: {"repo": None, "workdir": str(tmp_path)})
    monkeypatch.setattr(r.card_render, "workdir_state", lambda workdir, board: "empty")
    monkeypatch.setattr(r.runs_util, "board_runs", lambda board, cid: None)
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-1"))
    monkeypatch.setattr(r.STATE, "snap_dir", str(tmp_path / "snapshots"))
    os.makedirs(r.STATE.run_dir)
    os.makedirs(r.STATE.snap_dir)

    (tmp_path / "snapshots" / "lane-1-workdir-at-open.md.tmp").symlink_to(victim)
    r.write_workdir_state(1, "open")
    snapshot = (tmp_path / "snapshots" / "lane-1-workdir-at-open.md").read_text()
    assert "empty" in snapshot and "Work directory as lane 1" in snapshot

    (tmp_path / "run-1" / "workdir.json.tmp").symlink_to(victim)
    r.record_workdir_facts()
    facts = _json.load(open(tmp_path / "run-1" / "workdir.json"))
    assert facts["workdir"] == str(tmp_path), facts

    (tmp_path / "run-1" / "run-summary.json.tmp").symlink_to(victim)
    r.write_summary({"C1: implement - lane 1": {"id": "t_c", "status": "done"}})
    summary = _json.load(open(tmp_path / "run-1" / "run-summary.json"))
    assert "C1: implement - lane 1" in summary["cards"], summary

    assert victim.read_text() == "keep me\n", "a planted temp symlink was followed"
    # nothing strays: mkstemp's temp (one random segment) is gone after the swap, and
    # the planted names are still exactly what they were — symlinks nobody wrote through
    assert not list((tmp_path / "run-1").glob("*.json.*.tmp")), \
        os.listdir(tmp_path / "run-1")
    for planted in ("run-summary.json.tmp", "workdir.json.tmp"):
        assert (tmp_path / "run-1" / planted).is_symlink(), planted


def test_the_idea_snapshot_does_not_follow_a_planted_temp_symlink(monkeypatch, tmp_path):
    """Same writer shape, one directory up: the idea snapshot is what every card of the
    lane reads by path, and it is written into runs/<run-id>/snapshots/."""
    import run as r
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n")
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(r, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(r, "manifest", lambda: {})
    monkeypatch.setattr(r, "workdir_facts", lambda: {"repo": None, "workdir": str(tmp_path)})
    monkeypatch.setattr(r.card_render, "workdir_state", lambda workdir, board: "empty")
    monkeypatch.setattr(r.lanes, "lane_cards", lambda lane, **kw: [])
    monkeypatch.setattr(r, "lane_paths_agree", lambda state, lane: True)
    monkeypatch.setattr(r, "lane_opened_on_record", lambda lane: False)
    monkeypatch.setattr(r, "lane_options", lambda lane: {
        "integration-tests": True, "unit-tests": True, "refinement": True,
        "idea": "## Idea 1: is_even\n"})
    monkeypatch.setattr(r, "driver_comment", lambda cid, body: None)
    monkeypatch.setattr(r, "record_lane_open", lambda lane: None)
    monkeypatch.setattr(r.STATE, "opened", set())
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-1"))
    monkeypatch.setattr(r.STATE, "snap_dir", str(tmp_path / "snapshots"))
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "lane-1.md.tmp").symlink_to(victim)

    idea_title = __import__("lanes").card_title("I", 1)
    assert r.open_lane({idea_title: {"id": "id-I1", "status": "ready"}}, 1) == "open"
    assert (tmp_path / "snapshots" / "lane-1.md").read_text() == "## Idea 1: is_even\n"
    assert not list((tmp_path / "snapshots").glob("lane-1.md.*.tmp")), \
        os.listdir(tmp_path / "snapshots")
    assert victim.read_text() == "keep me\n", "a planted temp symlink was followed"


def test_a_failed_atomic_write_leaves_no_temp_behind(monkeypatch, tmp_path):
    """The tear the old writers risked was `open(<target>.tmp)` + os.replace: a crash
    between them left a stray file in the run's own directory, and one planted at that
    name was something else's file. A mkstemp temp that cannot be swapped is removed."""
    import run as r
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "REPO", str(tmp_path))
    monkeypatch.setattr(r, "commit_target", lambda: "main")
    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-1"))
    os.makedirs(r.STATE.run_dir)

    def boom(obj, f, **kw):
        f.write('{"wall_min": 13.1, "agent_w')
        raise RuntimeError("killed mid-write")

    monkeypatch.setattr(r.json, "dump", boom)
    with pytest.raises(RuntimeError):
        r.write_summary({})
    assert os.listdir(r.STATE.run_dir) == [], os.listdir(r.STATE.run_dir)


def _prepare_summary_write(monkeypatch, tmp_path):
    """The fakes write_summary needs to reach its one _write_atomic call."""
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "commit_target", lambda: "main")
    monkeypatch.setattr(run, "expected_workdir_facts", lambda: {})
    monkeypatch.setattr(run, "board_lane_count", lambda state: 0)
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "run-1"))
    os.makedirs(run.STATE.run_dir)
    return tmp_path / "run-1" / "run-summary.json"


def test_an_atomic_write_never_toggles_the_process_umask(monkeypatch, tmp_path):
    """`_write_atomic` used to set the process umask to 0 and restore it around EVERY
    write, to learn `0666 & ~umask`. Nothing in run.py is threaded, but a FORK inside
    that window inherited umask 0 — every file the child created lost its group and
    other bits (2026-09-25 fix-pass verification). The umask is read ONCE now, at
    import (`run._UMASK`), where the process is single-threaded."""
    path = _prepare_summary_write(monkeypatch, tmp_path)

    def boom(*_a, **_k):
        raise AssertionError("a write toggled the process umask")

    monkeypatch.setattr(run.os, "umask", boom)
    run.write_summary({})
    assert path.exists()


def test_an_atomic_write_has_the_mode_open_would_have_given_it(monkeypatch, tmp_path):
    """The mode rule the helper's own docstring states, enforced rather than asserted:
    mkstemp's 0600 is NOT what `open(path, "w")` would have left. Every target is board
    state a human reads and a group may share."""
    path = _prepare_summary_write(monkeypatch, tmp_path)
    run.write_summary({})
    umask = os.umask(0)
    os.umask(umask)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o666 & ~umask, oct(mode)
    assert run._WRITE_MODE == 0o666 & ~umask, oct(run._WRITE_MODE)
    # the two atomic writers read the same rule once each; a drift is a test failure
    assert file_lanes.WRITE_MODE == run._WRITE_MODE, \
        (oct(file_lanes.WRITE_MODE), oct(run._WRITE_MODE))


def test_no_prose_names_a_symbol_or_a_test_that_does_not_exist():
    """Four sentences that were false about the code beside them, pinned so the false
    form cannot come back: an E16 that "enforces" the deletion rule (E16 is an INFO note
    over work/ litter and INFO never fails a run, so nothing enforces it), a _READ_ERROR
    that does not exist (the record is STATE.read_error), a test name that does not exist,
    and a `full.update(c)` a comment said was "discarded by the re-merge" when it
    persisted in state[t]."""
    import inspect
    import run as r
    src = inspect.getsource(r)
    assert "_READ_ERROR" not in src
    assert "test_nothing_in_the_template_deletes_work_or_runs" not in src
    assert "enforced by run-audit" not in inspect.getsource(r._tick)
    assert "tests/test_run_directories.py" in inspect.getsource(r._tick)
    assert "was then discarded by the re-merge" not in src
    assert "STATE.read_error" in inspect.getsource(r.card_record)
    assert "test_the_driver_retired_every_clearing_function" in \
        inspect.getsource(r.clean_work_noise)
