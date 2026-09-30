import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "template"))
sys.path.insert(0, os.path.join(REPO, "driver"))
spec = importlib.util.spec_from_file_location("run_card", os.path.join(REPO, "driver", "run-card.py"))
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)
import lanes  # noqa: E402
import run  # noqa: E402

REJECT = ("REJECT: 1) item 5, plan.md:38 — greet.greeting is undefined. OWNER: C "
          "VERIFIED: 1 — structure; 2 — scope")


def make_run(tmp_path, cards, chain, name="run-20260927-000000"):
    board = tmp_path / "greet"
    run_dir = board / "runs" / name
    (run_dir / "cards").mkdir(parents=True)
    (board / "board.json").write_text("{}")
    for c in cards:
        entry = {"status": "done", "assignee": "coder", "body": "b", "result": "", **c}
        (run_dir / "cards" / f"{c['id']}.jsonl").write_text(json.dumps(entry) + "\n")
    (run_dir / "chain.jsonl").write_text("".join(json.dumps(e) + "\n" for e in chain))
    return run_dir


@pytest.fixture(autouse=True)
def fresh_driver(monkeypatch):
    """rc.main() re-points run.py's module globals and fills STATE's per-process guards;
    both are restored here so no later test sees this module's boards."""
    monkeypatch.setattr(run, "STATE", run.RunState())
    for name in ("BOARD", "BOARD_DIR", "BOARD_CFG", "IDEAS_DIR", "RUNS_ROOT",
                 "CURRENT_RUN", "WORKDIR"):
        monkeypatch.setattr(run, name, getattr(run, name))


def test_parse_card_reads_code_lane_and_round():
    assert rc.parse_card("RVp1") == ("RVp", 1, None, None)
    assert rc.parse_card("P2-rev-1") == ("P", 2, 1, None)
    assert rc.parse_card("TW1-rev-3") == ("TW", 1, 3, None)
    assert rc.parse_card("RVp1-r2") == ("RVp", 1, None, 2)
    assert rc.parse_card("RVa1-r3") == ("RVa", 1, None, 3)


@pytest.mark.parametrize("arg,why", [("Gp1", "gates run no worker"), ("X1", "unknown card"),
                                     ("RVp1-rev-1", "no revision rounds"),
                                     ("P1-rev-0", "start at 1"),
                                     ("C1-r2", "re-review rounds are"),
                                     ("RVp1-r1", "re-review rounds are"),
                                     ("RVp1-r0", "re-review rounds are"),
                                     ("Gi1-r2", "gates run no worker"),
                                     ("P1-rev", "expected <CODE><lane>")])
def test_parse_card_refuses(arg, why):
    with pytest.raises(SystemExit, match=why):
        rc.parse_card(arg)


def test_card_title_matches_the_driver():
    assert rc.card_title("RVp", 1, None) == lanes.card_title("RVp", 1)
    assert rc.card_title("P", 1, 2) == "P1-rev-2: plan revision round 2 - lane 1"
    assert rc.card_title("I", 1, 1) == "I1-rev-1: idea refinement round 1 - lane 1"
    assert rc.card_title("C", 2, 1) == "C2-rev-1: implementation revision round 1 - lane 2"


def test_card_title_names_re_reviews_like_the_driver():
    assert rc.card_title("RVp", 1, None, 2) == "RVp1-r2: plan review round 2 - lane 1"
    assert rc.card_title("RVa", 1, None, 2) == "RVa1-r2: implementation re-review round 2 - lane 1"


def test_a_plan_re_review_follows_the_newest_revision_and_judges_what_came_before(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    run_dir = make_run(tmp_path, [], [])
    monkeypatch.setattr(run.STATE, "run_dir", str(run_dir))
    for cid in ("t_p", "t_p2"):
        (run_dir / "scratch" / cid).mkdir(parents=True)
        (run_dir / "scratch" / cid / "plan.md").write_text(cid)
    prior = [{"id": "t_p", "title": "P1: implementation plan - lane 1", "status": "done"},
             {"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done", "result": REJECT},
             {"id": "t_p2", "title": "P1-rev-1: plan revision round 1 - lane 1", "status": "done"}]
    t = rc.rereview_trigger(prior, "RVp", 1, 2)
    assert t["rev_card"]["id"] == "t_p2" and t["round_no"] == 1
    assert t["judged"] == str(run_dir / "scratch" / "t_p" / "plan.md")


def test_a_re_review_without_its_revision_is_refused():
    prior = [{"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done", "result": REJECT}]
    with pytest.raises(SystemExit, match="no done P1-rev-<n>"):
        rc.rereview_trigger(prior, "RVp", 1, 2)


def test_a_code_re_review_must_be_the_rounds_own_number(monkeypatch):
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    prior = [{"id": "t_c2", "title": "C1-rev-1: implementation revision round 1 - lane 1",
              "status": "done"}]
    with pytest.raises(SystemExit, match="RVa1-r2"):
        rc.rereview_trigger(prior, "RVa", 1, 3)
    assert rc.rereview_trigger(prior, "RVa", 1, 2)["round_no"] == 1


def test_a_code_re_review_is_the_final_review_only_where_the_lane_runs_integration_tests(monkeypatch):
    prior = [{"id": "t_c2", "title": "C1-rev-1: implementation revision round 1 - lane 1",
              "status": "done"}]
    monkeypatch.setattr(run, "lane_options", lambda lane: {"integration-tests": True})
    assert rc.rereview_trigger(prior, "RVa", 1, 2)["final_review"] is True
    monkeypatch.setattr(run, "lane_options", lambda lane: {"integration-tests": False})
    assert rc.rereview_trigger(prior, "RVa", 1, 2)["final_review"] is False


def test_board_layout_accepts_a_renamed_copy(tmp_path):
    run_dir = make_run(tmp_path, [], [], name="run-20260927-000000-try1")
    board_dir, runs_root, name = rc.board_layout(str(run_dir))
    assert board_dir == str(tmp_path / "greet")
    assert name == "run-20260927-000000-try1"


def test_board_layout_refuses_a_dir_that_is_not_a_run(tmp_path):
    with pytest.raises(SystemExit, match="not a run dir"):
        rc.board_layout(str(tmp_path))


def test_done_before_skips_the_cards_own_title(tmp_path):
    cards = [{"id": "t_p", "title": "P1: implementation plan - lane 1"},
             {"id": "t_rv", "title": "RVp1: plan review - lane 1", "result": REJECT}]
    chain = [{"event": "done", "card_id": "t_p", "code": "P1"},
             {"event": "done", "card_id": "t_rv", "code": "RVp1"}]
    run_dir = make_run(tmp_path, cards, chain)
    assert [c["id"] for c in rc.done_before(str(run_dir), cards[1]["title"])] == ["t_p"]


def test_the_operators_own_review_feeds_the_revision_on_the_same_copy(tmp_path):
    """The workflow: RVp1 on a copy (original PASSed, the replay REJECTs), then P1-rev-1
    on that same copy. One RVp1 stub — the newest — and the trigger is the new REJECT."""
    title = "RVp1: plan review - lane 1"
    cards = [{"id": "t_p", "title": "P1: implementation plan - lane 1"},
             {"id": "t_rv", "title": title, "result": "PASS: VERIFIED: 1 — ok"},
             {"id": "t_p2", "title": "P1-rev-1: plan revision round 1 - lane 1"},
             {"id": "t_new", "title": title, "result": REJECT}]
    chain = [{"event": "done", "card_id": "t_p", "code": "P1"},
             {"event": "done", "card_id": "t_rv", "code": "RVp1"},
             {"event": "start", "card_id": "t_p2", "code": "P1-rev-1"},
             {"event": "done", "card_id": "t_p2", "code": "P1-rev-1"},
             {"event": "done", "card_id": "t_new", "code": "RVp1"}]
    run_dir = make_run(tmp_path, cards, chain)
    got = rc.done_before(str(run_dir), "P1-rev-1: plan revision round 1 - lane 1")
    assert [c["id"] for c in got] == ["t_p", "t_new"]


def test_revision_trigger_takes_the_newest_reject(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    prior = [{"id": "t_p", "title": "P1: implementation plan - lane 1", "result": "CHANGED: x",
              "status": "done"},
             {"id": "t_rv", "title": "RVp1: plan review - lane 1", "result": REJECT,
              "status": "done"}]
    t = rc.revision_trigger(prior, "P", 1, 1)
    assert t["card"]["id"] == "t_rv"
    assert t["sender"] == "The plan review"
    assert "greet.greeting" in t["findings"]


def test_an_idea_revision_needs_a_rework_from_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    gi = {"id": "t_gi", "title": lanes.card_title("Gi", 1), "result": "PASS: accepted",
          "status": "done"}
    with pytest.raises(SystemExit, match="a REWORK from Gi1"):
        rc.revision_trigger([gi], "I", 1, 1)
    t = rc.revision_trigger([dict(gi, result="REWORK: name the output file")], "I", 1, 1)
    assert t["findings"] == "name the output file" and t["text"] is None
    assert t["sender"] == "The idea gate"


def test_revision_trigger_refuses_a_run_whose_plan_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    prior = [{"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done",
              "result": "PASS: VERIFIED: 1"}]
    with pytest.raises(SystemExit, match="a REJECT from RVp1"):
        rc.revision_trigger(prior, "P", 1, 1)


@pytest.mark.probe_rule            # the driver's real probe-log check (tests/conftest.py)
def test_revision_trigger_names_an_unprobed_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    prior = [{"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done",
              "result": "PASS: VERIFIED: 1"}]
    with pytest.raises(SystemExit, match="probe retry"):
        rc.revision_trigger(prior, "P", 1, 1)


def test_revision_trigger_refuses_a_summary_only_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: None)
    prior = [{"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done",
              "result": ""}]
    with pytest.raises(SystemExit, match="empty result"):
        rc.revision_trigger(prior, "P", 1, 1)


def test_revision_trigger_needs_the_owner_to_match(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    prior = [{"id": "t_rva", "title": "RVa1: implementation review - lane 1", "status": "done",
              "result": REJECT}]
    with pytest.raises(SystemExit, match="OWNER: TW"):
        rc.revision_trigger(prior, "TW", 1, 1)


def test_revision_trigger_refuses_a_round_past_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    prior = [{"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done",
              "result": REJECT}]
    cap = lanes.max_reworks(None)
    assert rc.revision_trigger(prior, "P", 1, cap)["max_rounds"] == cap
    with pytest.raises(SystemExit, match="escalates"):
        rc.revision_trigger(prior, "P", 1, cap + 1)


def test_check_result_reads_a_review_like_the_driver(tmp_path):
    (tmp_path / "review.md").write_text("full review")
    assert all(rc.check_result("RVp", REJECT, str(tmp_path)).values())
    bad = rc.check_result("RVp", "Looks fine to me.", str(tmp_path))
    assert not bad["verdict_token"]
    unprobed = rc.check_result("RVp", f"REJECT: {run.UNPROBED_MARK} — x", str(tmp_path))
    assert not unprobed["probed"]


def test_check_result_reads_a_worker_line_and_its_handoff(tmp_path):
    assert not rc.check_result("C", "CHANGED: greet.py", str(tmp_path))["handoff"]
    (tmp_path / "patch.diff").write_text("diff")
    assert all(rc.check_result("C", "CHANGED: greet.py", str(tmp_path)).values())
    assert all(rc.check_result("C", "NO CHANGE: already satisfied", str(tmp_path / "x")).values())


class FakeBoard:
    """An in-memory `hermes kanban`: enough of create/complete/attach/link/unblock/list/
    show/attachments for the driver's functions, plus a worker that 'runs' on dispatch."""

    def __init__(self, run_dir, result, handoff):
        self.cards, self.n, self.calls = {}, 0, []
        self.run_dir, self.result, self.handoff = run_dir, result, handoff

    def kb(self, *args, capture=True):
        self.calls.append(args)
        verb = args[0]
        if verb == "create":
            self.n += 1
            cid = f"t_new{self.n}"
            status = "blocked" if "--initial-status" in args else "ready"
            self.cards[cid] = {"id": cid, "title": args[1], "status": status,
                               "assignee": args[args.index("--assignee") + 1],
                               "body": args[args.index("--body") + 1], "result": None,
                               "completed_at": None}
            return json.dumps({"id": cid})
        if verb == "complete":
            if self.cards[args[1]]["status"] == "blocked":
                raise RuntimeError(f"kb {args[:2]}: cannot complete a blocked task")
            self.cards[args[1]].update(status="done", result=args[args.index("--result") + 1],
                                       completed_at=self.n)
        elif verb == "unblock":
            self.cards[args[1]]["status"] = "ready"
        elif verb == "list":
            return json.dumps(list(self.cards.values()))
        elif verb == "show":
            return json.dumps({"events": []})
        return ""

    def hermes(self, *args, env=None, timeout=120):
        self.calls.append(("hermes",) + args)
        if "dispatch" in args:
            for cid, c in self.cards.items():
                if c["status"] == "ready" and c["assignee"] != "human-gate":
                    scratch = os.path.join(self.run_dir, "scratch", cid)
                    os.makedirs(scratch, exist_ok=True)
                    with open(os.path.join(scratch, self.handoff), "w") as fh:
                        fh.write("x")
                    c.update(status="done", result=self.result, completed_at=100)
        return 0, ""


def wire(tmp_path, monkeypatch, result=REJECT, handoff="review.md"):
    cards = [{"id": "t_p", "title": "P1: implementation plan - lane 1", "result": "CHANGED: plan"}]
    chain = [{"event": "done", "card_id": "t_p", "code": "P1"}]
    run_dir = make_run(tmp_path, cards, chain, name="run-20260927-000000-try1")
    (run_dir / "scratch" / "t_p").mkdir(parents=True)
    (run_dir / "scratch" / "t_p" / "plan.md").write_text("# plan")
    fake = FakeBoard(str(run_dir), result, handoff)
    fake.taken, fake.stopped = [], []
    monkeypatch.setattr(run, "kb", fake.kb)
    monkeypatch.setattr(rc, "hermes", fake.hermes)
    monkeypatch.setattr(rc, "stop_worker", fake.stopped.append)
    monkeypatch.setattr(rc.driver_lock, "take",
                        lambda runs_dir, why: fake.taken.append(runs_dir) or ("", ""))
    monkeypatch.setattr(rc, "POLL_S", 0)
    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: [])
    monkeypatch.setattr(run, "staged_files", lambda *a, **k: [])
    return run_dir, fake


def test_a_review_card_runs_and_lands_in_the_run(tmp_path, monkeypatch):
    run_dir, fake = wire(tmp_path, monkeypatch)
    assert rc.main(["--run", str(run_dir), "--card", "RVp1"]) == 0
    assert fake.taken == [str(run_dir.parent)]
    new = next(c for c in fake.cards.values() if c["title"].startswith("RVp1:"))
    stub = next(c for c in fake.cards.values() if c["title"].startswith("P1:"))
    assert stub["assignee"] == "human-gate" and stub["result"] == "CHANGED: plan"
    assert ("attach", stub["id"], str(run_dir / "scratch" / "t_p" / "plan.md")) in fake.calls
    assert ("link", stub["id"], new["id"]) in fake.calls
    ledger = [json.loads(ln) for ln in (run_dir / "verdicts.jsonl").read_text().splitlines()]
    assert {"attempt", "verdict"} <= {e["event"] for e in ledger if e.get("card_id") == new["id"]}
    chain = [json.loads(ln) for ln in (run_dir / "chain.jsonl").read_text().splitlines()]
    assert {"start", "done"} <= {e["event"] for e in chain if e.get("card_id") == new["id"]}
    assert (run_dir / "cards" / f"{new['id']}.jsonl").is_file()
    assert any(c[:3] == ("hermes", "kanban", "boards") and "rm" in c for c in fake.calls)
    assert fake.stopped == [new["id"]]


def test_the_report_is_the_last_stdout_line(tmp_path, monkeypatch, capsys):
    run_dir, _ = wire(tmp_path, monkeypatch)
    rc.main(["--run", str(run_dir), "--card", "RVp1"])
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["verdict"] == "REJECT" and report["card"].startswith("RVp1:")


def test_a_blocked_card_fails_stops_its_worker_and_still_removes_its_board(tmp_path, monkeypatch):
    run_dir, fake = wire(tmp_path, monkeypatch)

    def blocking(*args, env=None, timeout=120):
        fake.calls.append(("hermes",) + args)
        for c in fake.cards.values():
            if c["status"] == "ready" and c["assignee"] != "human-gate":
                c["status"] = "blocked"
        return 0, ""
    monkeypatch.setattr(rc, "hermes", blocking)
    assert rc.main(["--run", str(run_dir), "--card", "RVp1"]) != 0
    assert any("rm" in c for c in fake.calls if c[0] == "hermes")
    new = next(c for c in fake.cards.values() if c["title"].startswith("RVp1:"))
    assert fake.stopped == [new["id"]]
    chain = [json.loads(ln) for ln in (run_dir / "chain.jsonl").read_text().splitlines()]
    assert not any(e["event"] == "done" and e.get("card_id") == new["id"] for e in chain)


def test_an_unreadable_verdict_fails_the_run(tmp_path, monkeypatch):
    run_dir, _ = wire(tmp_path, monkeypatch, result="Looks fine.")
    assert rc.main(["--run", str(run_dir), "--card", "RVp1"]) != 0


@pytest.mark.probe_rule
def test_an_unprobed_plan_pass_fails_the_run(tmp_path, monkeypatch, capsys):
    """The driver reads an RVp PASS without its probe log as REJECT: UNPROBED PASS."""
    run_dir, _ = wire(tmp_path, monkeypatch, result="PASS: VERIFIED: 1 — ok")
    assert rc.main(["--run", str(run_dir), "--card", "RVp1"]) != 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["checks"]["probed"] is False and report["verdict"] == "REJECT"


def test_a_summary_only_verdict_is_read_like_the_driver_reads_it(tmp_path, monkeypatch, capsys):
    run_dir, _ = wire(tmp_path, monkeypatch, result="")
    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: [
        {"outcome": "completed", "summary": REJECT, "started_at": 1, "ended_at": 2}])
    assert rc.main(["--run", str(run_dir), "--card", "RVp1"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"] == "REJECT"


def test_a_live_driver_on_the_board_stops_it_before_anything_is_filed(tmp_path, monkeypatch):
    run_dir, fake = wire(tmp_path, monkeypatch)

    def held(runs_dir, why):
        raise SystemExit(f"driver lock held: {why}")
    monkeypatch.setattr(rc.driver_lock, "take", held)
    with pytest.raises(SystemExit, match="driver lock held"):
        rc.main(["--run", str(run_dir), "--card", "RVp1"])
    assert fake.calls == []


def test_a_re_review_files_under_its_revision_with_only_the_review_pin(tmp_path, monkeypatch):
    run_dir, fake = wire(tmp_path, monkeypatch)
    rev = {"id": "t_c2", "title": "C1-rev-1: implementation revision round 1 - lane 1",
           "status": "done", "assignee": "coder", "body": "b", "result": "CHANGED: greet.py"}
    (run_dir / "cards" / "t_c2.jsonl").write_text(json.dumps(rev) + "\n")
    with open(run_dir / "chain.jsonl", "a") as fh:
        fh.write(json.dumps({"event": "done", "card_id": "t_c2", "code": "C1-rev-1"}) + "\n")
    assert rc.main(["--run", str(run_dir), "--card", "RVa1-r2"]) == 0
    create = next(c for c in fake.calls if c[0] == "create" and c[1].startswith("RVa1-r2:"))
    new = next(i for i, c in fake.cards.items() if c["title"].startswith("RVa1-r2:"))
    stub = next(i for i, c in fake.cards.items() if c["title"].startswith("C1-rev-1:"))
    assert "--parent" not in create and ("link", stub, new) in fake.calls
    assert create[create.index("--skill") + 1] == "kanban-worker" and "--goal" not in create
    assert "RE-REVIEW ROUND 2 of" in create[create.index("--body") + 1]


def test_a_revision_without_a_trigger_files_nothing(tmp_path, monkeypatch):
    run_dir, fake = wire(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="no trigger"):
        rc.main(["--run", str(run_dir), "--card", "P1-rev-1"])
    assert fake.calls == []


def _rework_env(tmp_path, monkeypatch):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    (tmp_path / "scratch" / "t_p").mkdir(parents=True)
    (tmp_path / "scratch" / "t_p" / "plan.md").write_text("# plan")
    filed = []

    def kb(*args, capture=True):
        if args[0] == "create":
            filed.append(args[args.index("--body") + 1])
            return json.dumps({"id": f"t_{len(filed)}"})
        return ""
    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "_round_settings", lambda lane: ("60m", lambda f: "BASE\n"))
    monkeypatch.setattr(run, "record_rework", lambda *a, **k: None)
    return filed


def _state(prior, **parked):
    state = {c["title"]: dict(c, completed_at=i + 1) for i, c in enumerate(prior)}
    for code, cid in parked.items():
        title = lanes.card_title(code, 1)
        state[title] = {"id": cid, "title": title, "status": "blocked"}
    return state


def test_a_revision_body_equals_the_one_the_driver_files(tmp_path, monkeypatch):
    """Same run records, two composers: driver.rework_rounds (production, reading the
    verdict itself) and run-card (revision_trigger + revision_body). Bases are stubbed to
    one string; the tails, the pointer and the re-review paragraph must match."""
    filed = _rework_env(tmp_path, monkeypatch)
    prior = [{"id": "t_p", "title": "P1: implementation plan - lane 1", "status": "done",
              "result": "CHANGED: plan"},
             {"id": "t_rv", "title": "RVp1: plan review - lane 1", "status": "done",
              "result": REJECT}]
    run.rework_rounds(_state(prior, Gp="t_gp"))
    trig = rc.revision_trigger(prior, "P", 1, 1)
    assert trig["judged"] == str(tmp_path / "scratch" / "t_p" / "plan.md")
    assert filed[0] == run.revision_body(
        "BASE\n", "plan", 1, trig["max_rounds"], trig["findings"], trig["sender"],
        trig["text"], run.revision_sources(trig["judged"], trig["card"]["id"]),
        run._full_verdict_pointer(trig["card"]["id"]))
    rr = rc.rereview_trigger(prior + [{"id": "t_rev", "status": "done",
                                       "title": "P1-rev-1: plan revision round 1 - lane 1"}],
                             "RVp", 1, 2)
    assert filed[1] == "BASE\n" + run.rereview_text("plan", rr["round_no"], rr["max_rounds"],
                                                    rr_no=2, judged=rr["judged"])


def test_a_code_revision_body_equals_the_one_the_driver_files(tmp_path, monkeypatch):
    filed = _rework_env(tmp_path, monkeypatch)
    monkeypatch.setattr(run, "snapshot_lane_files", lambda *a, **k: None)
    prior = [{"id": "t_p", "title": "P1: implementation plan - lane 1", "status": "done",
              "result": "CHANGED: plan"},
             {"id": "t_rva", "title": "RVa1: implementation review - lane 1", "status": "done",
              "result": REJECT}]
    run.rework_rounds(_state(prior, Gc="t_gc", RVc="t_rvc"))    # RVc filed: a final review
    trig = rc.revision_trigger(prior, "C", 1, 1)
    assert filed[0] == run.revision_body(
        "BASE\n", "code", 1, trig["max_rounds"], trig["findings"], trig["sender"],
        trig["text"], run.revision_sources(None, trig["card"]["id"]),
        run._full_verdict_pointer(trig["card"]["id"]))
    rr = rc.rereview_trigger(prior + [{"id": "t_rev", "status": "done",
                                       "title": "C1-rev-1: implementation revision round 1 - lane 1"}],
                             "RVa", 1, 2)
    assert filed[1] == "BASE\n" + run.rereview_text("code", rr["round_no"], rr["max_rounds"],
                                                    final_review=rr["final_review"])


def test_wait_for_returns_when_the_card_settles_and_times_out_otherwise(monkeypatch):
    monkeypatch.setattr(rc, "POLL_S", 0)
    monkeypatch.setattr(run, "record_timing", lambda st: None)
    seen = iter([{"T": {"status": "running"}}, {"T": {"status": "done"}}])
    monkeypatch.setattr(rc, "_only", lambda cid: next(seen))
    assert rc.wait_for("t_1", "T", 60)[0] == "done"
    monkeypatch.setattr(rc, "_only", lambda cid: {"T": {"status": "running"}})
    assert rc.wait_for("t_1", "T", -1)[0] == "timed out"
    monkeypatch.setattr(rc, "_only", lambda cid: {})
    assert rc.wait_for("t_1", "T", 60)[0] == "missing"
