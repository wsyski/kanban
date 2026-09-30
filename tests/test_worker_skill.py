"""The engine's worker skill (`template/skills/kanban-worker/SKILL.md`).

The kanban rules used to sit in each profile's SOUL, loaded into every session of the
profile — desktop, cron, telegram — for rules only a card session needs. They are a
skill now, filed with every card a profile works (`--skill`), so they reach the worker's
system prompt, the one part of a session a context compaction keeps. A profile's copy
that is missing or differs from the repo's stops the filing: every card would otherwise
run without the rules, or on old ones.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "template"))
sys.path.insert(0, os.path.join(REPO, "driver"))
import file_lanes
import lanes
import run

SKILL = os.path.join(REPO, "template", "skills", lanes.WORKER_SKILL, "SKILL.md")


def _install(root, *profiles, text=None):
    for p in profiles:
        dst = os.path.join(root, "profiles", p, "skills", lanes.WORKER_SKILL, "SKILL.md")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if text is None:
            shutil.copy(SKILL, dst)
        else:
            with open(dst, "w") as f:
                f.write(text)


# ---- the skill and the souls ------------------------------------------------

def test_the_skill_is_named_for_its_directory_and_hidden_from_the_index():
    """Hermes preloads a forced skill by name; the manual-command gate keeps it out of
    the skill index every other session of the profile sees."""
    text = open(SKILL).read()
    assert text.startswith("---\nname: kanban-worker\n"), text[:80]
    assert "__manual_command_only__" in text.split("\n---\n", 1)[0]


def test_the_skill_carries_the_rules_the_souls_gave_up():
    text = open(SKILL).read()
    assert "`kanban_show`" in text and "compaction" in text     # re-read the card
    assert "Hermes kanban coding-team template" in text           # the engine's AGENTS.md
    assert "never certify your own card" in text
    assert "Never deploy" in text


def test_no_soul_carries_kanban_rules_any_more():
    """Everything above the hub-owned block is the repo's; the block may mention kanban."""
    for r in ("coder", "researcher", "trader"):
        text = open(os.path.join(REPO, "template", "roles", r, "SOUL.md")).read()
        own = text.split("<!-- skill-sync:response-style:start -->")[0]
        assert "## Kanban Cards" not in own, r
        assert "card" not in own.lower(), r


# ---- filing -----------------------------------------------------------------

class _Kb:
    def __init__(self):
        self.created = []

    def __call__(self, board, *args):
        if args[0] == "create":
            self.created.append(args)
            return json.dumps({"id": f"t_{len(self.created)}"})
        return ""


def _skill(args):
    return args[args.index("--skill") + 1] if "--skill" in args else None


def test_every_card_a_profile_works_is_filed_with_the_skill_and_no_gate_is(monkeypatch, tmp_path):
    fake = _Kb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    file_lanes.file_board("b", REPO, str(tmp_path), 1, "k")
    assert fake.created
    for args in fake.created:
        assignee = args[args.index("--assignee") + 1]
        want = None if assignee == "human-gate" else lanes.WORKER_SKILL
        assert _skill(args) == want, args[1]
        assert args.count("--skill") <= 1, args[1]


def test_a_gate_remapped_onto_a_profile_gets_the_skill():
    assert lanes.skill_args("human-gate") == []
    assert lanes.skill_args("gatekeeper") == ["--skill", lanes.WORKER_SKILL]


def test_a_rework_round_carries_the_skill(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    (tmp_path / "board.json").write_text('{"slug": "b", "lanes": 1}')
    args = run._create_args("P1-rev-1: x", "body", "coder", "key", "7m", ["--goal"])
    assert _skill(args) == lanes.WORKER_SKILL and args[-1] == "--goal"
    gate = run._create_args("Gi1-r2: x", "body", "human-gate", "key", "7m", [])
    assert "--skill" not in gate


# ---- the check --------------------------------------------------------------

@pytest.mark.skill_rule
def test_the_check_names_a_missing_and_a_stale_copy(tmp_path):
    root = str(tmp_path / "hermes")
    _install(root, "coder")
    _install(root, "researcher", text="an old copy\n")
    found = lanes.worker_skill_problems(REPO, {}, root)
    assert len(found) == 1 and "profile researcher" in found[0], found
    assert "not the repo copy" in found[0] and "install -D" in found[0]
    shutil.rmtree(os.path.join(root, "profiles", "coder", "skills"))
    found = lanes.worker_skill_problems(REPO, {}, root)
    assert any("profile coder" in p and "missing" in p for p in found), found


@pytest.mark.skill_rule
def test_the_check_asks_only_for_the_profiles_the_board_spawns(tmp_path):
    root = str(tmp_path / "hermes")
    _install(root, "coder")
    assert lanes.worker_skill_problems(REPO, {"refinement": False}, root) == []
    assert lanes.worker_skill_problems(REPO, {"assignees": {"researcher": "coder"}}, root) == []


@pytest.mark.skill_rule
def test_the_check_reads_the_default_profile_at_the_root(tmp_path):
    root = tmp_path / "hermes"
    dst = root / "skills" / lanes.WORKER_SKILL / "SKILL.md"
    dst.parent.mkdir(parents=True)
    shutil.copy(SKILL, dst)
    _install(str(root), "researcher")
    assert lanes.worker_skill_problems(REPO, {"assignees": {"coder": "default"}}, str(root)) == []


@pytest.mark.skill_rule
def test_the_driver_refuses_to_file_and_says_so_on_the_card(monkeypatch, tmp_path):
    board = tmp_path / "boards" / "b"
    board.mkdir(parents=True)
    (board / "board.json").write_text('{"slug": "b", "lanes": 1}')
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    _install(str(tmp_path / "hermes"), "coder")
    comments = []
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "driver_comment", lambda cid, body: comments.append(body))
    run.STATE.reported.clear()
    good = "## Idea\n\nbody\n\n### Done means\n\n- it works\n"
    assert run.validate_armed([(1, good, "c1")]) is False
    assert comments and "profile researcher" in comments[0] and "missing" in comments[0]
    _install(str(tmp_path / "hermes"), "researcher")
    assert run.validate_armed([(1, good, "c1")]) is True


@pytest.mark.skill_rule
def test_create_board_refuses_a_profile_without_the_skill(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "hermes"
    stub.write_text("#!/bin/sh\n"
                    'if [ "$1" = profile ]; then printf "  coder x\\n  researcher x\\n"; fi\n'
                    "exit 0\n")
    stub.chmod(0o755)
    board = tmp_path / "board"
    board.mkdir()
    (board / "board.json").write_text('{"name": "B", "lanes": 1, "auto-gates": []}')
    root = tmp_path / "hermes"
    _install(str(root), "coder")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", HERMES_HOME=str(root))
    r = subprocess.run([os.path.join(REPO, "driver", "create-board.sh"), "--board", str(board)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "profile researcher: the kanban-worker skill is missing" in r.stderr, r.stderr


def test_the_card_log_records_the_skills_a_card_was_filed_with(monkeypatch):
    """The card log is the card's input as filed; the worker skill is part of it."""
    monkeypatch.setattr(run.runs_util, "board_runs", lambda board, cid: [])
    monkeypatch.setattr(run, "kb", lambda *a, **k: "")
    entry = run._card_log_entry({"id": "t_1", "title": "C1: implement - lane 1",
                                 "assignee": "coder", "skills": [lanes.WORKER_SKILL]})
    assert entry["skills"] == [lanes.WORKER_SKILL]
    json.dumps(entry)
