"""A re-filing REUSES a run no driver ever started.

`create-board.sh` mints `runs/<run-id>/` and points `runs/current` at it BEFORE it
files the cards, because every card body carries its run's paths. So the directory
exists while the run does not, and nothing retracts a mint: `runs/` is a human's to
prune ("never this script's"), AGENTS.md says run directories are never deleted, and
`reset.sh` keeps `runs/` wholesale. A filing that is retried — or abandoned before
`start-board.sh` ever runs — therefore leaves a directory the board then treats as
its current run.

Measured on `is-even` (2026-09-13): two abandoned mints, `is-even-20260913-235032`
and `is-even-20260913-235701`, no driver ever started in either, the newer one named
by `runs/current` — so the project's own definition of done went red for a run that
never existed:

    ERROR E1: no driver.log — the run never started
    ERROR E4: no run-summary.json — the run wrote no summary

and `run.empty_run_reason` halts a restart on the same state ("its filing failed").
The remedy the design offers is to bury the mint under another one — which is what
"board contents are disposable" means in practice, and is why nobody saw it. So the
filing is what must not mint twice: a run id is evidence of nothing until a driver
writes into it, and the next filing reuses it.
"""
import datetime
import os
import re
import subprocess
import sys
import textwrap
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
import file_lanes

SLUG = "b"
MINTED = "20260912-090000"          # the abandoned mint's stamp, i.e. what current names
LATER = datetime.datetime(2026, 9, 12, 10, 0, 0)     # a filing an hour afterwards

# Every path a driver creates. Any one of them means the run happened: the mint is
# history then, and a filing must leave it alone (nothing here is ever cleared).
DRIVER_EVIDENCE = ("driver.log", "driver.lock", "chain.jsonl", "timing.jsonl",
                   "verdicts.jsonl", "run-summary.json", "halt.txt", "deadman.txt",
                   "cards", "artifacts", "snapshots", "patches", "scratch")


def _repo(tmp_path, run_id=None, entries=(), current=True):
    """A repo holding one board's runs/ dir: `run_id`'s directory (with `entries`
    in it, file or dir), and `current` naming it unless told otherwise."""
    runs = tmp_path / "boards" / SLUG / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    if run_id:
        (runs / run_id).mkdir()
        for name in entries:
            (runs / run_id / name).write_text("x\n")
    if current:
        (runs / "current").write_text((run_id or "") + "\n")
    return str(tmp_path)


def _runs(tmp_path):
    return sorted(os.listdir(tmp_path / "boards" / SLUG / "runs"))


# ---- the decision ---------------------------------------------------------

def test_an_unstarted_mint_is_reused(tmp_path):
    repo = _repo(tmp_path, run_id=f"{SLUG}-{MINTED}")
    assert file_lanes.next_run_key(repo, SLUG, now=LATER) == f"{SLUG}-{MINTED}"


def test_reusing_mints_no_second_directory(tmp_path):
    """The board's runs/ is the record. A filing adds a directory only when it
    starts a run."""
    repo = _repo(tmp_path, run_id=f"{SLUG}-{MINTED}")
    before = _runs(tmp_path)
    file_lanes.next_run_key(repo, SLUG, now=LATER)
    assert _runs(tmp_path) == before


def test_a_filing_that_succeeds_twice_still_holds_one_run(tmp_path):
    """The retry this exists for: the second filing of the same board."""
    repo = _repo(tmp_path)
    first = file_lanes.next_run_key(repo, SLUG, now=datetime.datetime(2026, 9, 12, 9, 0, 0))
    os.makedirs(card_render.run_dir(repo, SLUG, first))          # what create-board.sh does
    (tmp_path / "boards" / SLUG / "runs" / "current").write_text(first + "\n")
    assert file_lanes.next_run_key(repo, SLUG, now=LATER) == first


@pytest.mark.parametrize("name", DRIVER_EVIDENCE)
def test_a_run_a_driver_started_is_never_reused(tmp_path, name):
    """One path is enough: these are written by the driver and by nothing else, so
    a filing that finds any of them is looking at a run, not at an abandoned mint."""
    repo = _repo(tmp_path, run_id=f"{SLUG}-{MINTED}", entries=[name])
    key = file_lanes.next_run_key(repo, SLUG, now=LATER)
    assert key == f"{SLUG}-{LATER:%Y%m%d-%H%M%S}", key
    assert key != f"{SLUG}-{MINTED}"
    assert key not in _runs(tmp_path)        # the decision is a name, not a directory


def test_a_run_the_driver_started_stays_where_it_is(tmp_path):
    """Deliberately the same assertion as minting a second run leaves the first
    alone: a filing must never write into a directory that holds evidence."""
    repo = _repo(tmp_path, run_id=f"{SLUG}-{MINTED}", entries=["driver.log", "chain.jsonl"])
    file_lanes.next_run_key(repo, SLUG, now=LATER)
    assert _runs(tmp_path) == [f"{SLUG}-{MINTED}", "current"]
    assert (tmp_path / "boards" / SLUG / "runs" / f"{SLUG}-{MINTED}" / "chain.jsonl").exists()


def test_a_current_naming_a_missing_directory_is_not_a_mint(tmp_path):
    """The human pruned it, or the run is merely stale: there is no directory to
    reuse, and pointing the new filing at a directory that does not exist would
    recreate the very confusion (`current` naming a run nothing wrote) this
    prevents. `run.use_run` already resolves such a pointer; filing mints fresh."""
    repo = _repo(tmp_path, run_id="", current=True)
    (tmp_path / "boards" / SLUG / "runs" / "current").write_text(f"{SLUG}-{MINTED}\n")
    assert file_lanes.next_run_key(repo, SLUG, now=LATER) == f"{SLUG}-{LATER:%Y%m%d-%H%M%S}"


@pytest.mark.parametrize("current", [None, "", "   "])
def test_no_run_named_means_a_fresh_key(tmp_path, current):
    repo = _repo(tmp_path)
    if current is not None:
        (tmp_path / "boards" / SLUG / "runs" / "current").write_text(current + "\n")
    assert file_lanes.next_run_key(repo, SLUG, now=LATER) == f"{SLUG}-{LATER:%Y%m%d-%H%M%S}"


def test_a_board_that_has_never_been_created_has_no_runs_dir(tmp_path):
    """`--board boards/<slug>` on a fresh clone: nothing to reuse, and the
    decision must not create anything on its own."""
    assert file_lanes.next_run_key(str(tmp_path), SLUG, now=LATER) == \
        f"{SLUG}-{LATER:%Y%m%d-%H%M%S}"


def test_the_fresh_key_is_the_documented_shape(tmp_path):
    """`<slug>-<YYYYmmdd-HHMMSS>`, the shape every run id in runs/ already has."""
    key = file_lanes.next_run_key(_repo(tmp_path), SLUG, now=LATER)
    assert key == f"{SLUG}-{LATER:%Y%m%d-%H%M%S}"
    assert re.fullmatch(rf"{SLUG}-\d{{8}}-\d{{6}}", key)


def test_the_default_clock_is_now(tmp_path):
    """The script passes no clock, so the shape above must hold for the real one."""
    key = file_lanes.next_run_key(_repo(tmp_path), SLUG)
    stamp = datetime.datetime.strptime(key[len(SLUG) + 1:], "%Y%m%d-%H%M%S")
    assert abs((datetime.datetime.now() - stamp).total_seconds()) < 60


# ---- the wiring: create-board.sh files through this decision ---------------

CREATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "driver", "create-board.sh")


def test_create_board_mints_through_the_decision():
    """Pinned where it broke: the mint used to compute its own timestamp inline, so
    the decision could not be reused, tested, or seen. Reading the script's text is
    the only way a shell heredoc's logic is reachable from the suite."""
    src = open(CREATE).read()
    assert "file_lanes.next_run_key(" in src
    assert "strftime" not in src.split("run_dir = card_render.run_dir")[0]
    # And the reuse is announced: a filing that quietly drops its own fresh run id
    # reads exactly like one that minted (the driver log is the only other place a
    # run id appears).
    assert "reusing" in src


# ---- and end to end, with a stubbed engine --------------------------------

def _stub_hermes(tmp_path):
    """A `hermes` that answers what create-board.sh asks and nothing else."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    stub = d / "hermes"
    stub.write_text(textwrap.dedent(r"""
        #!/usr/bin/env bash
        if [ "$1" = "profile" ] && [ "$2" = "list" ]; then
          printf '  coder deepseek stopped\n  researcher deepseek stopped\n  trader deepseek stopped\n'
          exit 0
        fi
        if [ "$1" = "kanban" ]; then
          for a in "$@"; do
            if [ "$a" = "create" ] && [ "$2" != "boards" ]; then
              printf '{"id": "t_%s"}\n' "$$"
              exit 0
            fi
          done
          exit 0
        fi
        echo "stub hermes: unhandled $*" >&2
        exit 9
        """).lstrip())
    stub.chmod(0o755)
    return d


def _probe_repo(tmp_path):
    """A throwaway repo laid out like this one — `driver/` and `template/` under the repo
    root, so the script resolves REPO from its own path — holding a copy of
    create-board.sh in driver/ and symlinks to the rest of both layers, plus one board to
    file and a dispatch lock a live process holds (the pre-flight requires a held one)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = tmp_path / "repo"
    for layer in ("driver", "template"):
        (repo / layer).mkdir(parents=True)
        for entry in os.listdir(os.path.join(here, layer)):
            if entry in ("__pycache__", "tests", os.path.basename(CREATE)):
                continue
            os.symlink(os.path.join(here, layer, entry), repo / layer / entry)
    (repo / "boards" / SLUG).mkdir(parents=True)
    script = repo / "driver" / os.path.basename(CREATE)
    script.write_text(open(CREATE).read())
    script.chmod(0o755)
    # The shipped board, filed under this probe's slug: it is the manifest and idea
    # the real filing is known to validate against.
    sample = os.path.join(here, "boards", "is-even")
    (repo / "boards" / SLUG / "board.json").write_text(
        open(os.path.join(sample, "board.json")).read()
        .replace('"is-even"', f'"{SLUG}"'))
    (repo / "boards" / SLUG / "lane-1.md").write_text(
        open(os.path.join(sample, "lane-1.md")).read())
    home = tmp_path / "hermes-home"
    lock = home / "kanban" / ".dispatcher.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    holder = subprocess.Popen(["bash", "-c", f"exec 3<{lock}; sleep 120"])
    return repo, script, home, holder


def test_two_filings_leave_one_run_directory(tmp_path):
    """The whole fix, through the real script: the second filing reuses the mint the
    first one left, instead of adding a second run that no driver will ever start."""
    if not os.path.exists("/usr/bin/lsof"):
        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
    repo, script, home, holder = _probe_repo(tmp_path)
    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
               HERMES_HOME=str(home))
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    runs = repo / "boards" / SLUG / "runs"
    try:
        first = subprocess.run([str(script), "--board", f"boards/{SLUG}"],
                               capture_output=True, text=True, env=env, cwd=str(repo))
        assert first.returncode == 0, first.stderr[-2000:]
        assert len([d for d in runs.iterdir()]) == 2, sorted(os.listdir(runs))
        # A second run of the same second would pass this test whatever the code
        # did, because the two timestamps would be equal anyway.
        time.sleep(1.05)
        second = subprocess.run([str(script), "--board", f"boards/{SLUG}"],
                                capture_output=True, text=True, env=env, cwd=str(repo))
        assert second.returncode == 0, second.stderr[-2000:]
        assert "reusing" in second.stdout, second.stdout
    finally:
        holder.kill()
    dirs = sorted(d.name for d in runs.iterdir() if d.is_dir())
    assert len(dirs) == 1, dirs
    assert (runs / "current").read_text().strip() == dirs[0]
