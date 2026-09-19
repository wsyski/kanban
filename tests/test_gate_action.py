import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import lanes
import run

GI = lanes.card_title("Gi", 1)
STATE = {GI: {"id": "t_gi", "status": "blocked"}}


def refined(findings_bullet="- F1: python3 present — `python3 --version` → 3.14"):
    parts = []
    for name in lanes.REFINED_SECTIONS:
        parts.append(f"## {name}\n{findings_bullet if name == 'Findings' else '- a line'}\n")
    return "\n".join(parts)


class FakeCard:
    """One gate card's comment thread and the driver's writes to it."""

    def __init__(self):
        self.comments, self.calls = [], []

    def human(self, body, author="desktop"):
        # `show --json` carries no comment id — only author, body, created_at
        self.comments.append({"author": author, "body": body, "created_at": 1789504951})

    def kb(self, *args, capture=True):
        self.calls.append(args)
        if args[0] == "comment":
            author = args[args.index("--author") + 1] if "--author" in args else "user"
            self.human(args[-1], author=author)
        return ""

    def driver_comments(self):
        return [c["body"] for c in self.comments if c["author"] == run.DRIVER_AUTHOR]

    def completed(self):
        return [a for a in self.calls if a[0] == "complete"]


@pytest.fixture
def card(monkeypatch):
    fake = FakeCard()
    monkeypatch.setattr(run, "kb", fake.kb)
    monkeypatch.setattr(run, "card_show", lambda cid: {"comments": list(fake.comments)})
    monkeypatch.setattr(run, "send_notice", lambda *a, **k: None)
    return fake


@pytest.fixture
def refined_file(monkeypatch, tmp_path, card):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto-gates": []})
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.STATE.announced.clear()
    d = tmp_path / "artifacts" / "lane-1"
    d.mkdir(parents=True)
    yield d / "refined.md"
    run.STATE.announced.clear()


def test_idea_gate_holds_until_every_template_section_exists(refined_file):
    refined_file.write_text(refined().replace("## Verification recipe", "## Checks"))
    assert run.gate_action(STATE, GI, "gi", 1) == \
        "waiting: refined idea missing section(s): Verification recipe"


def test_idea_gate_counts_only_findings_bullets(refined_file):
    refined_file.write_text(refined(findings_bullet="none"))
    assert "Findings section is empty" in run.gate_action(STATE, GI, "gi", 1)


def test_idea_gate_opens_on_a_complete_refinement(refined_file):
    refined_file.write_text(refined())
    assert run.gate_action(STATE, GI, "gi", 1) == "gate-held"


def test_md_section_stops_at_the_next_heading():
    text = "## Findings\nnone\n## Success criteria\n- SC1: x\n"
    assert run.md_section(text, "Findings") == "none\n"
    assert run.md_section(text, "Success criteria") == "- SC1: x\n"
    assert run.md_section(text, "Prior art") == ""


def test_a_gate_records_which_repository_and_branch_it_staged_in(monkeypatch, tmp_path):
    """The authorization chain is "the driver stages, the human commits at the
    gate". With an external default-workdir that commit lands in ANOTHER repository
    on whatever branch was checked out, so a gate that does not name it cannot be
    acted on."""
    import subprocess
    wd = tmp_path / "elsewhere"
    wd.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feature/x", str(wd)], check=True)
    (wd / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(wd), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(wd), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "one"], check=True)
    monkeypatch.setattr(run, "WORKDIR", str(wd))
    monkeypatch.setattr(run, "REPO", str(tmp_path / "repo"))
    target = run.commit_target()
    assert str(wd) in target and "EXTERNAL repository" in target
    assert "branch feature/x" in target


def test_a_board_owned_work_directory_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "REPO", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    monkeypatch.setattr(run, "WORKDIR", os.path.join(run.REPO, "driver"))
    assert "this repo" in run.commit_target()


def test_a_work_directory_outside_git_is_named_as_such(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path))
    assert "not a git repository" in run.commit_target()


def test_gate_evidence_works_when_the_work_directory_is_another_repo(monkeypatch, tmp_path):
    """git runs -C WORKDIR, and a pathspec outside that repo drops git into
    --no-index mode where --cached is not a valid option at all. Passing the
    kanban-side artifacts path therefore made staged_files() RAISE for an external
    default-workdir — taking the gate's evidence with it, on exactly the two boards
    that use one."""
    import subprocess
    ext = tmp_path / "ext"
    ext.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(ext)], check=True)
    (ext / "built.py").write_text("the lane's work\n")
    subprocess.run(["git", "-C", str(ext), "add", "built.py"], check=True)
    monkeypatch.setattr(run, "WORKDIR", str(ext))
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "kanban" / "runs" / "r1"))
    assert run.staged_files() == ["built.py"]


def test_gate_evidence_still_includes_the_hand_offs_for_a_board_owned_tree(monkeypatch, tmp_path):
    """When the work directory and the hand-offs share a repository, both pathspecs
    are required: gates record the refined idea and the plan too."""
    import inspect
    src = inspect.getsource(run.staged_files)
    assert "pathspecs.append(artifacts)" in src
    assert 'startswith(os.path.abspath(top)' in src


def test_foreign_staged_compares_paths_on_one_basis(monkeypatch, tmp_path):
    """Both sides come from `git -C WORKDIR ... --name-only`, so both are relative to
    that repository's top. An absolute-path branch here was dead code."""
    import inspect
    assert "os.path.isabs" not in inspect.getsource(run.foreign_staged)


def test_the_gate_records_the_tree_it_judged_not_the_one_the_lane_opened_on(monkeypatch, tmp_path):
    """Two readings, two questions: `open` is the input the plan was written against,
    `gate` is what the code gate sees after clean_work_noise() — a worker (or the
    human who owns the directory) may have moved the tree between them, and a gate
    reporting the OPEN reading then judges a tree that no longer exists (live,
    2026-09-12: a plan review recorded the directory empty while the files were on
    disk)."""
    board = tmp_path / "boards" / "b"
    work = board / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run.STATE, "snap_dir", str(tmp_path / "runs" / "r1" / "snapshots"))
    import os
    os.makedirs(run.STATE.snap_dir, exist_ok=True)
    at_open, open_path = run.write_workdir_state(1, "open")
    assert "empty" in at_open
    (work / "built.py").write_text("a worker built this\n")
    at_gate, gate_path = run.write_workdir_state(1, "gate")
    assert "NOT empty" in at_gate
    assert open_path.endswith("lane-1-workdir-at-open.md")
    assert gate_path.endswith("lane-1-workdir-at-gate.md")
    assert "empty" in open(open_path).read()          # the open reading is kept
    assert "NOT empty" in open(gate_path).read()


# ---- answering a gate with a comment (the dashboard's gesture) ----------------

def test_a_ready_gate_says_on_the_card_what_the_human_does(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    run.gate_action(STATE, GI, "gi", 1)
    [ready] = card.driver_comments()
    assert ready.startswith(run.GATE_READY_MARK)
    assert "PASS" in ready and "REWORK:" in ready and "finding(s)" in ready
    assert not card.completed()


def test_a_pass_comment_completes_the_gate_with_that_verdict(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    card.human("pass: read it, looks right")
    run.gate_action(STATE, GI, "gi", 1)
    [done] = card.completed()
    result = done[done.index("--result") + 1]
    assert result.startswith("PASS: read it, looks right")
    assert ("unblock", "t_gi") in card.calls


def test_accept_is_read_as_pass(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    card.human("ACCEPT")
    run.gate_action(STATE, GI, "gi", 1)
    [done] = card.completed()
    assert done[done.index("--result") + 1].startswith("PASS: accepted")


def test_a_rework_comment_at_the_idea_gate_becomes_the_rework_result(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    card.human("REWORK: the idea needs Java 17, not 21")
    run.gate_action(STATE, GI, "gi", 1)
    [done] = card.completed()
    result = done[done.index("--result") + 1]
    assert run.is_rework(result)
    assert run.rework_answers(result) == "the idea needs Java 17, not 21"


def test_a_rework_without_a_reason_is_not_applied_and_the_card_says_why(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    card.human("REWORK")
    run.gate_action(STATE, GI, "gi", 1)
    run.gate_action(STATE, GI, "gi", 1)
    assert not card.completed()
    replies = [c for c in card.driver_comments() if c.startswith("NOT APPLIED")]
    assert len(replies) == 1 and "reason" in replies[0]


def test_ordinary_notes_and_the_drivers_own_comments_never_open_a_gate(refined_file, card):
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    card.human("I will look at this tomorrow, passing it to Anna")
    card.human("Pass it to the reviewer")
    card.human("accept whatever RVa said")
    card.human("PASS", author=run.DRIVER_AUTHOR)
    run.gate_action(STATE, GI, "gi", 1)
    assert not card.completed()


def test_a_verdict_written_before_the_gate_was_ready_is_answered_not_applied(refined_file, card):
    refined_file.write_text(refined().replace("## Verification recipe", "## Checks"))
    card.human("PASS")
    assert run.gate_action(STATE, GI, "gi", 1).startswith("waiting:")
    run.gate_action(STATE, GI, "gi", 1)
    [reply] = card.driver_comments()
    assert reply.startswith("NOT APPLIED") and "waiting" in reply
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    run.gate_action(STATE, GI, "gi", 1)
    assert not card.completed(), "an early PASS must be written again once the gate is ready"


GP = lanes.card_title("Gp", 1)
GC = lanes.card_title("Gc", 1)


@pytest.fixture
def held(monkeypatch, card):
    """A plan and a code gate whose newest review passed, with a round recorder."""
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto-gates": [], "max-reworks": 2})
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "staged_files", lambda: [])
    monkeypatch.setattr(run, "write_timing_report", lambda lane: None)
    monkeypatch.setattr(run, "preserve_artifacts", lambda: None)
    monkeypatch.setattr(run, "commit_target", lambda: "here")
    monkeypatch.setattr(run.STATE, "snap_dir", "/tmp")
    state = {
        GP: {"id": "t_gp", "status": "blocked"},
        GC: {"id": "t_gc", "status": "blocked"},
        "RVp1: plan review - lane 1": {"id": "t_rvp", "status": "done", "result": "PASS: ok"},
        "RVa1: implementation review - lane 1": {"id": "t_rva", "status": "done", "result": "PASS: ok"},
    }
    monkeypatch.setattr(run, "latest_verdict_card", lambda st, lane, prefix, final_code=None: (
        st["RVp1: plan review - lane 1"] if prefix == "RVp" else st["RVa1: implementation review - lane 1"],
        "PASS: ok"))
    filed = []
    monkeypatch.setattr(run, "file_revision", lambda *a, **k: filed.append(("plan", a, k)))
    monkeypatch.setattr(run, "file_code_revision", lambda *a, **k: filed.append(("code", a, k)))
    run.STATE.announced.clear()
    yield state, filed
    run.STATE.announced.clear()


def test_rework_at_the_plan_gate_files_a_plan_round_with_the_persons_words(held, card):
    state, filed = held
    run.gate_action(state, GP, "gp", 1)
    card.human("REWORK: split step 3 into two tasks")
    run.gate_action(state, GP, "gp", 1)
    assert not card.completed(), "the gate stays held while the round runs"
    [(what, args, kw)] = filed
    assert what == "plan" and args[2] == 1 and args[3] == "split step 3 into two tasks"
    assert kw["base"] == "P" and kw["gate_code"] == "Gp" and "gate-holder" in kw["sender"]
    [applied] = [c for c in card.driver_comments() if c.startswith("REWORK APPLIED")]
    assert "(comment #2)" in applied
    # a second pass over the same thread files nothing more
    run.gate_action(state, GP, "gp", 1)
    assert len(filed) == 1


def test_rework_at_the_code_gate_files_a_code_round_for_the_named_owner(held, card):
    state, filed = held
    run.gate_action(state, GC, "gc", 1)
    card.human("REWORK: OWNER: TW the parser test asserts nothing")
    run.gate_action(state, GC, "gc", 1)
    [(what, args, kw)] = filed
    assert what == "code" and kw["owner"] == "TW" and "parser test" in args[3]


def test_rework_past_the_cap_is_refused_on_the_card(held, card):
    state, filed = held
    state["P1-rev-1: plan revision round 1 - lane 1"] = {"id": "r1", "status": "done"}
    state["P1-rev-2: plan revision round 2 - lane 1"] = {"id": "r2", "status": "done"}
    run.gate_action(state, GP, "gp", 1)
    card.human("REWORK: again")
    run.gate_action(state, GP, "gp", 1)
    assert not filed
    [reply] = [c for c in card.driver_comments() if c.startswith("NOT APPLIED")]
    assert "2" in reply and "PASS" in reply


def test_a_new_review_round_brings_a_new_gate_ready(held, card, monkeypatch):
    """After the round, the old GATE READY and the REWORK under it must not count."""
    state, filed = held
    run.gate_action(state, GP, "gp", 1)
    card.human("REWORK: split step 3")
    run.gate_action(state, GP, "gp", 1)
    state["RVp1-r2: plan review round 2 - lane 1"] = {"id": "t_rvp2", "status": "done",
                                                     "result": "PASS: fixed"}
    monkeypatch.setattr(run, "latest_verdict_card", lambda st, lane, prefix, final_code=None: (
        st["RVp1-r2: plan review round 2 - lane 1"], "PASS: fixed"))
    run.gate_action(state, GP, "gp", 1)
    readies = [c for c in card.driver_comments() if c.startswith(run.GATE_READY_MARK)]
    assert len(readies) == 2 and "RVp1-r2" in readies[1]
    assert len(filed) == 1 and not card.completed()
    card.human("PASS")
    run.gate_action(state, GP, "gp", 1)
    assert len(card.completed()) == 1


def test_auto_gates_ignore_comments_and_complete_on_evidence(monkeypatch, refined_file, card):
    monkeypatch.setattr(run, "auto_gates", lambda: ["Gi", "Gp", "Gc"])
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    [done] = card.completed()
    assert "auto-gate" in done[done.index("--result") + 1]


def test_a_waiting_gate_answers_only_what_came_after_the_drivers_last_word(held, card, monkeypatch):
    state, filed = held
    run.gate_action(state, GP, "gp", 1)
    card.human("PASS")                          # superseded by the REWORK below
    card.human("REWORK: split step 3")
    run.gate_action(state, GP, "gp", 1)
    monkeypatch.setattr(run, "latest_verdict_card", lambda *a, **k: (None, "unreadable"))
    run.gate_action(state, GP, "gp", 1)
    assert not [c for c in card.driver_comments() if c.startswith("NOT APPLIED")]
    card.human("PASS")
    run.gate_action(state, GP, "gp", 1)
    [reply] = [c for c in card.driver_comments() if c.startswith("NOT APPLIED")]
    assert "(comment #5)" in reply and not card.completed()


def test_only_the_listed_gate_is_completed_by_the_driver(monkeypatch, refined_file, card):
    """`"auto-gates": ["Gi"]` — the driver opens the idea gate on its evidence and the
    plan and code gates still wait for a person."""
    monkeypatch.setattr(run, "auto_gates", lambda: ["Gi"])
    refined_file.write_text(refined())
    run.gate_action(STATE, GI, "gi", 1)
    [done] = card.completed()
    assert "auto-gate" in done[done.index("--result") + 1]
    assert not [c for c in card.driver_comments() if c.startswith(run.GATE_READY_MARK)], \
        "an auto gate asks nobody"


def test_a_gate_not_in_the_list_still_asks_a_person(monkeypatch, held, card):
    state, _filed = held
    monkeypatch.setattr(run, "auto_gates", lambda: ["Gi"])
    run.gate_action(state, GP, "gp", 1)
    assert not card.completed()
    assert [c for c in card.driver_comments() if c.startswith(run.GATE_READY_MARK)]
