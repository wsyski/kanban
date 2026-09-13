"""The roles the graph fills, and the model and depth a board may pin its reviews to.

Three rules, one lookup each — `lanes.assignee_for` (which profile works a role),
`lanes.model_args` (which cards carry the model pin) and `lanes.effort_args` (which
carry the reasoning-effort pin) — so the tests here are about the rules and about the
three places that consume them: the filing path, the rework path, and the schema that
declares the options.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import board_schema
import file_lanes
import lanes
import run

PINNED = {"model_override": "glm-5.3-flash", "provider_override": "opencode-go",
          "reasoning_effort": "high"}
REVIEW_CODES = ("RVp", "RVa", "RVc")


# --- the roles the graph fills -----------------------------------------------

def test_the_retired_roles_are_gone_and_every_card_is_the_coders():
    """`manager`, `tester` and `reviewer` were retired: the plan, the unit and
    integration tests, the implementation and all three reviews are the coder's
    cards now, and its profile is the one you maintain. Every role the graph fills
    has to name a profile that exists — the dispatcher files a card whose assignee
    is not a profile as unspawnable."""
    roles = {r[2] for r in lanes.LANE_CARDS}
    assert roles == {"researcher", "coder", "human-gate"}, sorted(roles)
    assert board_schema.ROLES == roles          # the schema declares the same set
    assert lanes.ROLE_FALLBACK == {}            # nothing left to fall back from
    assert lanes.assignee_for("coder") == "coder"
    assert lanes.assignee_for("researcher") == "researcher"


def test_a_manifest_remap_still_beats_the_role_name():
    assert lanes.assignee_for("coder", {"coder": "senior"}) == "senior"
    assert lanes.assignee_for("researcher", {"researcher": "senior"}) == "senior"


def test_required_profiles_is_the_profiles_that_spawn():
    """create-board.sh's pre-flight asks this rather than carrying a list: every
    role's resolved profile, and NOT the gate's — a gate is completed by a person,
    so no profile has to exist for it."""
    assert lanes.required_profiles() == ["coder", "researcher"]


def test_required_profiles_follows_a_remap():
    req = lanes.required_profiles({"researcher": "senior", "human-gate": "gatekeeper"})
    assert "senior" in req and "researcher" not in req
    assert "gatekeeper" in req      # a REMAPPED gate does name a profile


# --- the model pin, and the depth the reviews run at -------------------------

def test_the_review_cards_take_the_model_the_manifest_pins():
    for code in REVIEW_CODES:
        assert lanes.model_args(code, dict(PINNED)) == [
            "--model", "glm-5.3-flash", "--provider", "opencode-go"], code


def test_only_the_judging_cards_carry_the_judges_model():
    """The pin is a property of the JUDGEMENT, not of the board — and it keys on
    the CARD CODE, because every work card is the coder's now: keyed on a role, the
    judge's model would land on the implementation and the tests too."""
    assert set(lanes.JUDGE_CODES) == set(REVIEW_CODES)
    for code in sorted({c["code"] for c in lanes.lane_cards(1)} - set(lanes.JUDGE_CODES)):
        assert lanes.model_args(code, dict(PINNED)) == [], code


def test_a_board_without_a_model_files_no_model_flag():
    assert lanes.model_args("RVa", {}) == []
    assert lanes.model_args("RVa", None) == []


def test_a_provider_without_a_model_is_not_sent():
    """Mirrors the engine's own rule (provider_override requires model_override):
    a provider names a backend, not a model, so sending it alone would ask the
    worker for a model nobody named."""
    assert lanes.model_args("RVa", {"provider_override": "opencode-go"}) == []


# --- the reasoning effort the reviews run at ---------------------------------

def test_the_review_cards_take_the_reasoning_effort_the_lane_resolves():
    """The coder works a review card AS A REVIEWER, and a board that buys that card
    another model usually wants it to think at another depth: `reasoning_effort` is
    the engine's own name for that depth, and it stays independent of the model."""
    for code in REVIEW_CODES:
        assert lanes.reasoning_effort_args(code, {"reasoning_effort": "high"}) == [
            "--reasoning", "high"], code


def test_only_the_judging_cards_carry_the_reasoning_effort():
    for code in sorted({c["code"] for c in lanes.lane_cards(1)} - set(lanes.JUDGE_CODES)):
        assert lanes.reasoning_effort_args(code, {"reasoning_effort": "high"}) == [], code


def test_a_lane_without_a_reasoning_effort_files_no_flag():
    assert lanes.reasoning_effort_args("RVp", {}) == []
    assert lanes.reasoning_effort_args("RVp", None) == []


def test_a_reasoning_effort_without_a_model_is_allowed():
    """`kanban_db.create_task` takes `reasoning_effort` beside `model_override` and
    neither requires the other, so depth may be bought without a model."""
    assert lanes.reasoning_effort_args("RVa", {"reasoning_effort": "low"}) == [
        "--reasoning", "low"]


def test_a_typo_in_the_reasoning_effort_is_refused_where_the_board_is_declared():
    """A typo must not reach the first dispatch: the engine refuses the same values
    at spawn, and a spawn failure is FINAL (one attempt)."""
    problems = board_schema.validate({"lanes": 1, "reasoning_effort": "bananas"}, where="b")
    assert any("expected one of" in p for p in problems), problems


def test_a_manifest_may_pin_a_reasoning_effort():
    assert board_schema.validate({"lanes": 1, "reasoning_effort": "xhigh"}, where="b") == []
    assert board_schema.validate({"lanes": 1, "reasoning_effort": "High"}, where="b") == []


def test_the_reasoning_effort_is_per_lane_and_the_idea_may_override_it():
    """It is a PER-LANE option: one value for the board, an array with one entry per
    lane, or a lane's own `<!-- reasoning_effort: high -->` header — and the header
    wins over the board's value."""
    assert board_schema.validate({"lanes": 2, "reasoning_effort": ["high", "low"]},
                                 where="b") == []
    problems = board_schema.validate({"lanes": 2, "reasoning_effort": ["high"]}, where="b")
    assert any("1 entries for 2 lane(s)" in p for p in problems), problems
    # ... and the header door is open to it, unlike the model pin
    assert board_schema.validate({"reasoning_effort": "high"}, where="lane-1.md",
                                 only=board_schema.PER_LANE) == []
    assert "reasoning_effort" in board_schema.HEADER_KEYS
    # resolved for one lane: the board's entry, then the header on top of it
    board = {"lanes": 2, "reasoning_effort": ["high", "low"]}
    assert lanes.resolve_lane_options(board, {}, 2)["reasoning_effort"] == "low"
    assert lanes.resolve_lane_options({"lanes": 1, "reasoning_effort": "low"},
                                      {"reasoning_effort": "high"},
                                      1)["reasoning_effort"] == "high"


# --- the schema declares these keys ------------------------------------------

def test_the_model_pin_is_board_level_and_the_depth_is_per_lane():
    """Which model the judge runs is the BOARD's property, so it has no header door
    — a lane must not be able to quietly buy itself a stronger judge. How deep it
    thinks is per-lane instead, because a lane may legitimately need more of it."""
    for key in ("model_override", "provider_override"):
        assert key in board_schema.BOARD_KEYS, key
        assert key not in board_schema.HEADER_KEYS, key
    assert "reasoning_effort" in board_schema.BOARD_KEYS
    assert "reasoning_effort" in board_schema.HEADER_KEYS


def test_a_manifest_may_pin_a_model():
    assert board_schema.validate(
        {"lanes": 1, **PINNED}, where="b") == []


def test_a_provider_without_a_model_is_refused_where_the_board_is_declared():
    problems = board_schema.validate({"lanes": 1, "provider_override": "opencode-go"},
                                     where="b")
    assert any("requires 'model_override'" in p for p in problems), problems


def test_the_per_lane_array_form_of_the_pin_is_refused():
    problems = board_schema.validate({"lanes": 2, "model_override": ["a", "b"]},
                                     where="b")
    assert any("one value for the whole board" in p for p in problems), problems


def test_a_header_may_not_carry_the_pin():
    problems = board_schema.validate(
        {"model_override": "glm-5.3-flash"}, where="lane-1.md",
        only=board_schema.PER_LANE)
    assert any("board-level option" in p for p in problems), problems


# --- the filing path ---------------------------------------------------------

class FakeKb:
    """Records hermes CLI calls and hands back synthetic card ids."""

    def __init__(self):
        self.calls = []
        self.n = 0

    def __call__(self, board, *args):
        self.calls.append(args)
        if args[0] == "create":
            self.n += 1
            return json.dumps({"id": f"t_{self.n}"})
        return ""

    def created(self):
        return [a for a in self.calls if a[0] == "create"]


def _repo():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _arg(call, flag):
    return call[call.index(flag) + 1]


def test_filing_puts_the_pin_on_the_review_cards_only(monkeypatch, tmp_path):
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    monkeypatch.setattr(file_lanes, "_board_cfg", lambda d: dict(PINNED))
    file_lanes.file_board("b", _repo(), str(tmp_path), 1, "k")
    reviews = [a for a in fake.created() if a[1].startswith("RV")]
    assert len(reviews) == 3, [a[1] for a in reviews]        # RVp, RVa, RVc
    for a in reviews:
        assert _arg(a, "--model") == "glm-5.3-flash", a[1]
        assert _arg(a, "--provider") == "opencode-go", a[1]
        assert _arg(a, "--reasoning") == "high", a[1]
    for a in fake.created():
        if not a[1].startswith("RV"):
            assert "--model" not in a and "--provider" not in a, a[1]
            assert "--reasoning" not in a, a[1]


def test_filing_gives_each_lane_its_own_reasoning_effort(monkeypatch, tmp_path):
    """`reasoning_effort` is PER-LANE, so the filed review cards carry their own
    lane's value: a board may want its second lane reviewed at another depth."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    monkeypatch.setattr(file_lanes, "_board_cfg",
                        lambda d: {"lanes": 2, "reasoning_effort": ["high", "low"]})
    file_lanes.file_board("b", _repo(), str(tmp_path), 2, "k")
    for lane, level in ((1, "high"), (2, "low")):
        for code in REVIEW_CODES:
            a = next(c for c in fake.created() if c[1].startswith(f"{code}{lane}:"))
            assert _arg(a, "--reasoning") == level, a[1]
    for a in fake.created():                       # and nowhere else
        if not a[1].startswith("RV"):
            assert "--reasoning" not in a, a[1]


def test_filing_without_a_pinned_model_sends_no_flag(monkeypatch, tmp_path):
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    monkeypatch.setattr(file_lanes, "_board_cfg", lambda d: {})
    file_lanes.file_board("b", _repo(), str(tmp_path), 1, "k")
    assert not [a for a in fake.created() if "--model" in a]


# --- the rework path ---------------------------------------------------------

def _capture_rework(monkeypatch, tmp_path, cfg):
    calls = []

    def fake(*a, **kw):
        calls.append(a)
        return json.dumps({"id": f"t_{len(calls)}"})

    monkeypatch.setattr(run, "kb", fake)
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "VERDICTS_PATH", str(tmp_path / "verdicts.jsonl"))
    monkeypatch.setattr(run, "manifest", lambda: {"max-runtime": "7m", "targets": [],
                                                  **cfg})
    return calls


def test_a_re_review_keeps_the_judges_pins(monkeypatch, tmp_path):
    """A rework round is reviewed by a review card, so it must carry the same pins:
    without them a second round would silently fall back to the worker's own model
    and depth, which is the one thing the pins exist to avoid."""
    calls = _capture_rework(monkeypatch, tmp_path, PINNED)
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_revision(state, 1, 1, "1. fix the plan", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    run.file_code_revision(state, 1, 1, "1. fix the code", owner="C")
    created = [c for c in calls if c[0] == "create"]
    for prefix in ("RVp1-r2", "RVa1-r2"):
        rr = next(c for c in created if c[1].startswith(prefix))
        assert _arg(rr, "--model") == "glm-5.3-flash", rr[1]
        assert _arg(rr, "--provider") == "opencode-go", rr[1]
        assert _arg(rr, "--reasoning") == "high", rr[1]
    for prefix in ("P1-rev-1", "C1-rev-1"):
        rev = next(c for c in created if c[1].startswith(prefix))
        assert "--model" not in rev and "--reasoning" not in rev, rev[1]


def test_a_re_review_of_a_board_without_a_pin_sends_no_model(monkeypatch, tmp_path):
    calls = _capture_rework(monkeypatch, tmp_path, {})
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_code_revision(state, 1, 1, "1. fix", owner="C")
    assert not [c for c in calls if "--model" in c]


# --- the lane's effort reaches the cards that judge --------------------------

def _capture_effort(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a) or "")
    monkeypatch.setattr(run, "log", lambda *a, **k: None)
    return calls


def test_the_lanes_reasoning_effort_reaches_its_review_cards(monkeypatch):
    """The header override is only known at lane open, so the resolved value is pushed
    onto the cards that judge — and onto nothing else."""
    calls = _capture_effort(monkeypatch)
    state = {lanes.card_title(code, 1): {"id": f"t_{code}", "status": "blocked"}
             for code in ("RVp", "RVa", "RVc", "C", "P", "I")}
    run.apply_lane_reasoning_effort(state, 1, {"reasoning_effort": "high"})
    assert [c[0] for c in calls] == ["set-reasoning-effort"] * 3, calls
    assert {c[1] for c in calls} == {"t_RVp", "t_RVa", "t_RVc"}, calls
    assert {c[2] for c in calls} == {"high"}, calls


def test_an_archived_review_card_is_skipped(monkeypatch):
    """A lane without integration tests archives RVc at open, and the engine refuses
    to set an effort on an archived card — so the push skips it rather than failing
    the lane."""
    calls = _capture_effort(monkeypatch)
    state = {lanes.card_title("RVa", 1): {"id": "t_rva", "status": "blocked"},
             lanes.card_title("RVc", 1): {"id": "t_rvc", "status": "archived"}}
    run.apply_lane_reasoning_effort(state, 1, {"reasoning_effort": "low"})
    assert [c[1] for c in calls] == ["t_rva"], calls


def test_a_lane_without_a_reasoning_effort_sets_nothing(monkeypatch):
    calls = _capture_effort(monkeypatch)
    run.apply_lane_reasoning_effort({}, 1, {})
    run.apply_lane_reasoning_effort({}, 1, {"reasoning_effort": None})
    assert calls == []


# --- create-board.sh's pre-flight asks the graph, not a list ----------------

CREATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "create-board.sh")


def _stub_hermes(tmp_path, profiles):
    """A `hermes` that answers `profile list` and refuses everything else, so the
    test stops at the pre-flight instead of touching a real profile or board."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    rows = "".join(f"  {p} deepseek stopped\\n" for p in profiles)
    stub = d / "hermes"
    stub.write_text("#!/usr/bin/env bash\n"
                    'if [ "$1" = "profile" ] && [ "$2" = "list" ]; then\n'
                    f"  printf '%s' '{rows}'\n"
                    "  exit 0\n"
                    "fi\n"
                    'echo "stub hermes: unhandled $*" >&2\n'
                    "exit 9\n")
    stub.chmod(0o755)
    return d


def _board_dir(tmp_path, **cfg):
    d = tmp_path / "board"
    d.mkdir(exist_ok=True)
    cfg.setdefault("name", "B")
    cfg.setdefault("lanes", 1)
    cfg.setdefault("integration-tests", False)
    cfg.setdefault("auto-gates", False)   # no default-workdir: the board's own work/
    (d / "board.json").write_text(json.dumps(cfg))
    return d


def _run_create(tmp_path, board_dir, profiles):
    env = dict(os.environ)
    env["PATH"] = str(_stub_hermes(tmp_path, profiles)) + os.pathsep + env["PATH"]
    env["HERMES_HOME"] = str(tmp_path / ".hermes")
    r = subprocess.run([CREATE, "--board", str(board_dir)],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def test_the_pre_flight_accepts_a_board_whose_roles_resolve_to_real_profiles(tmp_path):
    """Every work card is the coder's, so a manifest that names no assignees needs
    two profiles rather than six. That is the case the hand-written pre-flight list
    got wrong: it refused EVERY board on a host where the retired profiles are gone,
    however the manifest remapped."""
    code, out = _run_create(tmp_path, _board_dir(tmp_path),
                            ["coder", "researcher"])
    assert "== pre-flight ==" in out, out
    assert "not available" not in out, out


def test_the_pre_flight_refuses_a_remap_to_a_profile_that_is_not_there(tmp_path):
    """Which is the check it kept: a board that names a profile must have it."""
    code, out = _run_create(tmp_path, _board_dir(tmp_path, assignees={"researcher": "senior"}),
                            ["coder", "researcher"])
    assert code == 1, (code, out)
    assert "profile senior not available" in out, out
