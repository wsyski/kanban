"""The bot driver's decisions, without a model.

`bots/run-board.py` spends its time in `hermes chat`, but every decision that can
be WRONG is a pure one: which cards a lane has and in what order, whether a gate
is the driver's or a human's, which card a rejection sends work back to, when the
rework budget is spent, and whether a halted run can be continued. `--dry-run`
exercises all of it and starts no bot, so this suite is as fast as the rest.
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

import board_schema
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, filename):
    """`bots/<file>.py` by path — the scripts are commands, not an importable package."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, "bots", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = _load("bots_run_board", "run-board.py")


def board(tmp_path, **options):
    """A one-lane board on disk: the manifest and an idea, nothing else."""
    d = tmp_path / "b"
    d.mkdir()
    cfg = {"slug": "b", "lanes": 1, "unit-tests": True, "integration-tests": False,
           "auto-gates": ["Gi", "Gp", "Gc"], "max-reworks": 2, **options}
    (d / "board.json").write_text(json.dumps(cfg))
    (d / "lane-1.md").write_text(
        "## Idea 1: A thing\n\nBuild `thing.py` with one function.\n\n"
        "### Done means\n\n- it exists.\n")
    return d


def run_driver(board_dir, *args):
    """main() with an argv, the way a person runs it. Returns its exit code."""
    argv = sys.argv
    sys.argv = ["run-board.py", "--board", str(board_dir), "--dry-run", *args]
    try:
        return driver.main()
    except SystemExit as exit_:
        return exit_.code
    finally:
        sys.argv = argv


def current_state(board_dir):
    runs = board_dir / "runs"
    latest = sorted(p for p in os.listdir(runs) if p.startswith("bots-"))[-1]
    (runs / "current-bots").write_text(latest)     # a dry run does not move the pointer
    return json.loads((runs / latest / "state.json").read_text())


# --- the graph, and who holds a gate ------------------------------------------------

def test_a_lane_runs_its_cards_in_the_graphs_own_order(tmp_path, capsys):
    """The chain's order, with the fork as a PAIR.

    TW1 and C1 render out of a thread pool, so which of the two lands first is a
    scheduling race — the driver's own log says "in parallel: TW1, C1 — the lane's fork,
    which this board does not serialise", and the strict order this test used to demand
    failed twice on this machine. What the graph fixes is the SEQUENCE around the pair.
    """
    assert run_driver(board(tmp_path)) == 0
    out = capsys.readouterr().out
    # "HH:MM:SS <card>: rendered …" — the driver's log line, timestamp first
    ran = [line.split()[1].rstrip(":") for line in out.splitlines() if "rendered" in line]
    assert ran[:3] == ["I1", "P1", "RVp1"], ran
    assert sorted(ran[3:5]) == ["C1", "TW1"], ran
    assert ran[5:] == ["RVa1"], ran
    assert "in parallel: TW1, C1" in out


def test_every_gate_the_manifest_names_is_the_drivers(tmp_path, capsys):
    run_driver(board(tmp_path))
    out = capsys.readouterr().out
    for gate in ("Gi1", "Gp1", "Gc1"):
        assert f"{gate}: auto-gate" in out


def test_a_gate_the_manifest_does_not_name_stops_the_run_for_a_person(tmp_path):
    d = board(tmp_path, **{"auto-gates": []})
    assert run_driver(d) == driver.GATE_HELD_EXIT
    state = current_state(d)
    assert state["held_gate"] == "Gi1" and state["done"] == ["I1"]


def test_a_dropped_card_is_not_run_and_its_child_is_reparented(tmp_path):
    """Asserted on the run's own state, not on log wording: a substring that stops
    matching because a log line was reworded would pass for the wrong reason."""
    d = board(tmp_path, **{"unit-tests": False})
    assert run_driver(d) == 0
    assert current_state(d)["done"] == ["I1", "Gi1", "P1", "RVp1", "Gp1",
                                        "C1", "RVa1", "Gc1"]     # no TW1


# --- answering a held gate ----------------------------------------------------------

def test_resume_passes_the_held_gate_and_the_lane_goes_on(tmp_path, capsys):
    d = board(tmp_path, **{"auto-gates": []})
    run_driver(d)
    current_state(d)
    assert run_driver(d, "--resume") == driver.GATE_HELD_EXIT      # stops at the NEXT gate
    out = capsys.readouterr().out
    assert "Gi1: PASS from the human" in out and "Gp1: GATE HELD" in out


def test_rework_revises_the_card_that_wrote_what_the_human_read(tmp_path, capsys):
    d = board(tmp_path, **{"auto-gates": []})
    run_driver(d)
    current_state(d)
    assert run_driver(d, "--rework", "the scope is still ambiguous") == driver.GATE_HELD_EXIT
    out = capsys.readouterr().out
    assert "I1-gate-rev-1" in out and "Gi1: GATE HELD" in out
    state = current_state(d)
    assert state["gate_reworks"] == {"Gi1": 1} and state["held_gate"] == "Gi1"


def test_the_revision_carries_the_humans_reason_into_the_card(tmp_path):
    d = board(tmp_path, **{"auto-gates": []})
    run_driver(d)
    current_state(d)
    run_driver(d, "--rework", "say what happens on an empty input")
    runs = d / "runs"
    body = (runs / (runs / "current-bots").read_text() /
            "cards" / "I1-gate-rev-1.prompt.txt").read_text()
    assert "REVISION ROUND" in body and "say what happens on an empty input" in body


def test_the_rework_budget_is_the_boards_and_the_lane_escalates_at_the_cap(tmp_path, capsys):
    d = board(tmp_path, **{"auto-gates": [], "max-reworks": 1})
    run_driver(d)
    current_state(d)
    run_driver(d, "--rework", "one")
    current_state(d)
    assert run_driver(d, "--rework", "two") == 1
    assert "a human's call now" in capsys.readouterr().out


def test_a_gate_answer_is_one_or_the_other_and_a_reason_is_required(tmp_path):
    d = board(tmp_path, **{"auto-gates": []})
    run_driver(d)
    current_state(d)
    assert "one or the other" in str(run_driver(d, "--resume", "--rework", "x"))
    assert "needs a reason" in str(run_driver(d, "--rework", "   "))


# --- continuing a run rather than re-buying it --------------------------------------

def test_resume_refuses_a_run_it_cannot_find(tmp_path):
    d = board(tmp_path)
    assert "no run to continue" in str(run_driver(d, "--resume"))


def test_a_halted_run_is_continued_at_the_card_that_failed(tmp_path, capsys):
    """The cards that finished are not run again — the point of resuming a halt."""
    d = board(tmp_path, **{"auto-gates": []})
    run_driver(d)
    state = current_state(d)
    state["held_gate"] = None                       # a HALT: no gate, work unfinished
    runs = d / "runs"
    (runs / (runs / "current-bots").read_text() / "state.json").write_text(json.dumps(state))
    capsys.readouterr()
    assert run_driver(d, "--resume") == driver.GATE_HELD_EXIT
    out = capsys.readouterr().out
    assert "resuming a halted run" in out and "I1: already done in this run" in out


# --- a card that outruns its ceiling ------------------------------------------------

def test_a_card_over_its_ceiling_is_a_halt_with_a_name(tmp_path, monkeypatch, capsys):
    """The turn is killed, the transcript says so, and the card reports nothing — the
    same halt as any other failed card, which is what `--resume` then continues."""
    import subprocess

    def kill(*a, **k):
        raise subprocess.TimeoutExpired(cmd="hermes", timeout=k.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", kill)
    d = board(tmp_path)
    run = tmp_path / "run"
    (run / "cards").mkdir(parents=True)
    (run / "driver.log").write_text("")
    result = driver.run_card(
        code="C", card_id="C1", body_file="c-body.txt", role="coder", skill=None,
        board="b", cfg={"slug": "b", "max-runtime": "1s"}, lane_cfg={}, lane=1,
        workdir=str(d / "work"), targets=(), run=str(run))
    assert result is None
    assert "C1: NO RESULT (timed out)" in capsys.readouterr().out
    assert "killed: no answer within" in (run / "cards" / "C1.transcript.txt").read_text()


# --- the fork, and what a run costs -------------------------------------------------

def test_the_lanes_fork_runs_its_two_cards_together(tmp_path, capsys):
    """`sequential: false` leaves TW and C both ready at once, and the driver runs
    them as one batch — the overlap the graph declares."""
    run_driver(board(tmp_path, sequential=False))
    assert "in parallel: TW1, C1" in capsys.readouterr().out


def test_a_board_that_serialises_the_fork_never_batches(tmp_path, capsys):
    """`sequential: true` makes C wait for TW in the GRAPH, so readiness never has two
    work cards — the manifest decides the overlap, not this driver."""
    run_driver(board(tmp_path, sequential=True))
    assert "in parallel" not in capsys.readouterr().out


def test_an_option_this_driver_cannot_honour_is_said_out_loud(tmp_path, capsys):
    run_driver(board(tmp_path, **{"goal-cards": ["C"]}))
    out = capsys.readouterr().out
    assert "NOT honoured: goal-cards" in out and "driver/run.py" in out


def test_a_manifest_that_asks_for_nothing_unsupported_says_nothing(tmp_path, capsys):
    run_driver(board(tmp_path))
    assert "NOT honoured" not in capsys.readouterr().out


def test_a_card_is_timed_even_when_it_reports_nothing(tmp_path, monkeypatch):
    """`timing.jsonl` is what makes two runs of one board comparable, so a card that
    failed is timed like any other — that is the run's cost too."""
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        subprocess.TimeoutExpired(cmd="hermes", timeout=1)))
    d = board(tmp_path)
    run = tmp_path / "run"
    (run / "cards").mkdir(parents=True)
    (run / "driver.log").write_text("")
    driver.run_card(code="C", card_id="C1", body_file="c-body.txt", role="coder",
                    skill=None, board="b", cfg={"slug": "b", "max-runtime": "1s"},
                    lane_cfg={}, lane=1, workdir=str(d / "work"), targets=(),
                    run=str(run))
    row = json.loads((run / "timing.jsonl").read_text().strip())
    assert row["card"] == "C1" and row["rc"] is None and row["seconds"] >= 0
    assert "1 card(s)" in driver.run_cost(str(run))


# --- the run state a resume depends on ----------------------------------------------

def test_the_run_state_is_written_whole_or_not_at_all(tmp_path):
    """A driver killed mid-write must not leave a truncated file where the resume
    state was: written to a temp name, then moved into place."""
    run = tmp_path / "run"
    run.mkdir()
    driver.write_state(str(run), {"done": ["P1"], "held_gate": None})
    assert json.loads((run / "state.json").read_text())["done"] == ["P1"]
    assert not list(run.glob("*.tmp"))


def test_a_state_file_that_cannot_be_parsed_is_fatal_not_ignored(tmp_path):
    """Treating it as empty would re-run every card the run already paid for."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "state.json").write_text('{"done": ["P1"')          # truncated
    with pytest.raises(SystemExit) as stop:
        driver.read_state(str(run))
    assert "not readable JSON" in str(stop.value)


def test_a_run_with_no_state_file_starts_empty(tmp_path):
    assert driver.read_state(str(tmp_path)) == {"done": [], "held_gate": None}


def test_a_lane_the_board_does_not_have(tmp_path):
    d = board(tmp_path)
    assert "this board has 1 lane(s)" in str(run_driver(d, "--lane", "7"))


# --- the tables the driver keeps by hand --------------------------------------------

def test_every_verdict_card_can_send_its_work_back():
    """`REWORK_TARGET` is hand-maintained beside a graph that is not. A gate or review
    missing from it halts a run with "no card to send work back to" at the worst
    moment — after the cards that earned the rejection have already been paid for."""
    for code in board_schema.GATE_CODES:
        assert code in driver.REWORK_TARGET, f"gate {code} has nowhere to send work back"
    for code in lanes.JUDGE_CODES:
        assert code in driver.REWORK_TARGET, f"review {code} has nowhere to send work back"


def test_every_rework_target_is_a_card_the_graph_actually_has():
    codes = {row[0] for row in lanes.LANE_CARDS}
    for verdict, target in driver.REWORK_TARGET.items():
        assert target in codes, f"{verdict} sends work to {target}, which is not a card"


@pytest.mark.parametrize("text,seconds", [
    ("25m", 1500), ("90s", 90), ("2h", 7200), ("60 m", 3600),
    # the multi-unit form board_schema validates: the bots driver used to return None
    # for it, which disarmed that card's --run-budget and its subprocess timeout
    ("1h30m", 5400), ("45m30s", 2730),
    ("", None), ("later", None)])
def test_the_manifests_own_spelling_of_a_ceiling(text, seconds):
    assert board_schema.duration_seconds(text) == seconds


def test_a_bots_prompt_is_a_mission_body_under_the_adapter(tmp_path):
    """The bot driver renders from `template/card-bodies/`, never from a private copy: the
    prompt a bot is handed has to carry the SAME words the kanban driver would file, with
    the adapter in front. A private copy is silent — the bot still runs, on text nobody is
    maintaining — so this pins the source of the prompt's prose."""
    d = board(tmp_path)
    assert run_driver(d) == 0
    run = sorted(p for p in (d / "runs").iterdir() if p.name.startswith("bots-"))[-1]
    prompts = sorted((run / "cards").glob("*.prompt.txt"))
    assert prompts, "the dry run rendered no prompts"
    adapter = open(driver.ADAPTER).read()
    bodies = {p.name: p.read_text() for p in
              (pathlib.Path(driver.REPO) / "template" / "card-bodies").glob("*.txt")}
    for prompt in prompts:
        text = prompt.read_text()
        card_id = prompt.name.split(".")[0]
        # The adapter's own words sit IN FRONT, with <YOUR-CARD-ID> resolved to this card
        # (render_card substitutes through the whole text, header included).
        head = adapter.splitlines()[0].replace("<YOUR-CARD-ID>", card_id)
        tail = [line for line in adapter.splitlines() if line.strip()][-1]
        assert text.startswith(head), prompt.name
        assert tail in text, prompt.name
        carried = [name for name, body in bodies.items()
                   if sum(1 for line in body.splitlines()
                          if len(line) > 60 and "<" not in line and line in text) >= 2]
        assert carried, f"{prompt.name} carries no text from template/card-bodies/"


def test_a_rerun_opens_its_own_session_not_the_previous_run(tmp_path):
    """The title is stamped with the RUN: `-c <title> --create-if-missing` creates a session
    when the title is new and RESUMES it when it is not, so a bare `<slug> L<n> <card>` made
    every rerun continue the last one's conversation (all six cards did, 2026-09-19)."""
    a = driver.session_title({"slug": "is-even"}, 1, "C1",
                             str(tmp_path / "runs" / "bots-20260919-181944"))
    b = driver.session_title({"slug": "is-even"}, 1, "C1",
                             str(tmp_path / "runs" / "bots-20260920-090000"))
    assert a != b, "two runs must not share one session"
    assert a.startswith("is-even L1 C1"), a          # still findable by board
    assert "bots-20260919-181944" in a, a


def test_a_card_turn_carries_the_suite_hygiene(monkeypatch, tmp_path):
    """`work/` must not collect caches. Every card body asks for PYTHONDONTWRITEBYTECODE and
    the models do not obey prose — measured: a bot run left `work/__pycache__` and the bots
    audit FAILS on it (B7, where the kanban side only notes it). So the spawn sets it, and
    this pins the spawn's env and its argv."""
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen.update(kw)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    driver.run_turn("coder", "p.txt", workdir=str(tmp_path), title="t",
                    model_args=["-m", "x", "--provider", "p"], skill=None, budget=None,
                    log_to=str(tmp_path / "out.log"))
    assert seen["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "no:cacheprovider" in seen["env"]["PYTEST_ADDOPTS"]
    assert seen["cmd"][:4] == ["hermes", "-p", "coder", "chat"], seen["cmd"]
    assert "--query-file" in seen["cmd"] and "-Q" in seen["cmd"]
    assert seen["timeout"] is None, "no ceiling was given, so the child gets none"


def test_demo_check_answers_the_prerequisites_and_runs_nothing(tmp_path):
    """`bots/demo.sh --check` is the cold-machine path — the only part of it a test can hold,
    since the rest runs a board. It must name each prerequisite and stop before driving."""
    repo = pathlib.Path(driver.REPO)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "hermes"        # `--version` for section 1, one profile per line for 2
    stub.write_text('#!/bin/sh\ncase "$1" in --version) echo "hermes 0.0.0";; '
                    '*) printf "researcher\\ncoder\\ntrader\\n";; esac\n')
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    demo = str(repo / "bots" / "demo.sh")

    r = subprocess.run(["bash", demo, "--board", str(repo / "boards" / "is-even"), "--check"],
                       capture_output=True, text=True, env=env, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-1200:]
    for section in ("1. hermes CLI", "2. profiles", "3. Bot Mode", "4. board is-even"):
        assert section in out, (section, out[-1200:])
    assert "prerequisites only" in out and "ALL CARDS COMPLETE" not in out

    bad = subprocess.run(["bash", demo, "--nope"], capture_output=True, text=True,
                         env=env, timeout=60)
    assert bad.returncode == 2, bad.stdout + bad.stderr
    helped = subprocess.run(["bash", demo, "--help"], capture_output=True, text=True,
                            env=env, timeout=60)
    assert helped.returncode == 0 and "--check" in helped.stdout


def test_both_drivers_take_the_one_lock_this_board_has(tmp_path):
    """`runs/driver.lock` is a BOARD's single driver lock, and the bot driver takes it
    the same way the kanban driver does — both build in the same `work/`, so a live
    holder is refused and a stale holder's lock is taken over. This was the one part of
    the bots driver with no test at all; its release rule (only OUR lock is unlinked) is
    now the shared one."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "driver.lock").write_text("999999")          # in range, owned by nothing
    driver.take_driver_lock(str(runs))
    assert (runs / "driver.lock").read_text() == str(os.getpid())
    with pytest.raises(SystemExit):                      # now it is ours, and we are alive
        driver.take_driver_lock(str(runs))
