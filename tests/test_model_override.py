"""The roles the graph fills, and the model a board may pin its reviews to.

Two rules, one lookup each — `lanes.assignee_for` (which profile works a role) and
`lanes.model_args` (which cards carry the model pin) — so the tests here are about the
rules and about the three places that consume them: the filing path, the rework path,
and the schema that declares the options.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))

import board_schema
import file_lanes
import lanes
import run

PINNED = {"model_override": "deepseek-v4.1-flash", "provider_override": "opencode-go"}
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


# --- the model pin the reviews run on ----------------------------------------

def test_the_review_cards_take_the_model_the_manifest_pins():
    for code in REVIEW_CODES:
        assert lanes.model_args(code, dict(PINNED)) == [
            "--model", "deepseek-v4.1-flash", "--provider", "opencode-go"], code


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


# --- the work model: every card, unless a lane says otherwise ----------------

WORK = {"model": "qwen38-27b", "provider": "llama-swap"}
# The lane's OWN pair, deliberately a different model from the board's: these tests
# exist to show which one wins, and a pair that matched the board's would pass either
# way. Any second key of the rig does; this is the third slot of its roster.
LANE = {"model": "muse-glimmer-30b", "provider": "llama-swap"}


def test_the_work_model_rides_every_card():
    """The board's `model` is what the board runs on: the plan, the tests and the
    implementation alike — not only the cards a verdict hangs on. Omitted, no flag
    is filed at all and every card keeps its profile's own model."""
    for code in ("I", "P", "TW", "C", "TI", "RVp", "RVa", "RVc"):
        assert lanes.model_args(code, dict(WORK)) == \
            ["--model", "qwen38-27b", "--provider", "llama-swap"], code


def test_a_lane_header_model_beats_the_board():
    """`resolve_lane_options` has already folded the idea header over the board, so
    the lane's dict is the only thing to read below the pin."""
    assert lanes.model_args("C", dict(WORK), dict(LANE)) == \
        ["--model", "muse-glimmer-30b", "--provider", "llama-swap"]


def test_the_review_pin_beats_the_lane_and_the_board_model():
    """The verdict is the one card that must not run the author's model, however
    strong the board's own model is."""
    both = {**WORK, **PINNED}
    assert lanes.model_args("RVa", both, dict(LANE)) == [
        "--model", "deepseek-v4.1-flash", "--provider", "opencode-go"]
    # ...and with no pin, the lane's model reaches the reviews too — which is the
    # case board_schema.review_model_notices reports at the door.
    assert lanes.model_args("RVa", dict(WORK), dict(LANE)) == \
        ["--model", "muse-glimmer-30b", "--provider", "llama-swap"]


# --- the schema declares these keys ------------------------------------------

def test_the_model_pin_is_board_level():
    """Which model the judge runs is the BOARD's property, so it has no header door
    — a lane must not be able to quietly buy itself a stronger judge."""
    for key in ("model_override", "provider_override"):
        assert key in board_schema.BOARD_KEYS, key
        assert key not in board_schema.HEADER_KEYS, key


def test_the_work_model_is_per_lane_and_the_pin_is_not():
    """A board that tests models wants a lane per model; a lane buying itself a
    different VERDICT is the thing the pin's board-level rule exists to prevent."""
    for key in ("model", "provider"):
        assert key in board_schema.HEADER_KEYS, key
    for key in ("model_override", "provider_override"):
        assert key not in board_schema.HEADER_KEYS, key


def test_a_provider_without_a_model_is_refused_in_either_scope():
    for scope, kwargs in (("board.json", {"provider": "llama-swap"}),
                          ("lane-1.md", {"provider": "llama-swap"})):
        problems = board_schema.validate(
            {"lanes": 1, **kwargs}, where=scope,
            only=board_schema.PER_LANE if scope.endswith(".md") else None)
        assert any("requires 'model'" in p for p in problems), problems


def test_a_board_model_with_no_pin_is_reported_and_not_refused():
    """A legitimate board (one local model for everything) is a note, not an error:
    the audit's clean gate must survive it, and the operator must still be told the
    verdict no longer comes from a different model."""
    assert board_schema.review_model_notices({"model": "qwen38-27b"}, where="b")
    assert board_schema.review_model_notices(
        {"model": "qwen38-27b", "model_override": "deepseek-v4.1-flash"}, where="b") == []
    assert board_schema.review_model_notices({}, where="b") == []
    assert board_schema.validate({"lanes": 1, "model": "qwen38-27b"}, where="b") == []


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
        {"model_override": "deepseek-v4.1-flash"}, where="lane-1.md",
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
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        assert _arg(a, "--model") == "deepseek-v4.1-flash", a[1]
        assert _arg(a, "--provider") == "opencode-go", a[1]
    for a in fake.created():
        if not a[1].startswith("RV"):
            assert "--model" not in a and "--provider" not in a, a[1]


def test_filing_puts_the_work_model_on_every_card_and_the_pin_on_the_reviews(monkeypatch, tmp_path):
    """Filing happens before any idea exists, so the manifest's `model` is the only
    model a card can be filed with; a lane's header re-points its own cards when the
    lane opens (run.open_lane). Both are filed as the flag pair --model/--provider."""
    fake = FakeKb()
    monkeypatch.setattr(file_lanes, "kb", fake)
    monkeypatch.setattr(file_lanes, "_board_cfg", lambda d: {**WORK, **PINNED})
    file_lanes.file_board("b", _repo(), str(tmp_path), 1, "k")
    for a in fake.created():
        if a[1].startswith("RV"):
            assert _arg(a, "--model") == "deepseek-v4.1-flash", a[1]
        else:
            assert _arg(a, "--model") == "qwen38-27b", a[1]
            assert _arg(a, "--provider") == "llama-swap", a[1]


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
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "verdicts.jsonl"))
    monkeypatch.setattr(run, "manifest", lambda: {"max-runtime": "7m", "targets": [],
                                                  **cfg})
    return calls


def test_a_re_review_keeps_the_judges_pins(monkeypatch, tmp_path):
    """A rework round is reviewed by a review card, so it must carry the same pins:
    without them a second round would silently fall back to the worker's own model,
    which is the one thing the pin exists to avoid."""
    calls = _capture_rework(monkeypatch, tmp_path, PINNED)
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_revision(state, 1, 1, "1. fix the plan", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    run.file_code_revision(state, 1, 1, "1. fix the code", owner="C")
    created = [c for c in calls if c[0] == "create"]
    for prefix in ("RVp1-r2", "RVa1-r2"):
        rr = next(c for c in created if c[1].startswith(prefix))
        assert _arg(rr, "--model") == "deepseek-v4.1-flash", rr[1]
        assert _arg(rr, "--provider") == "opencode-go", rr[1]
    for prefix in ("P1-rev-1", "C1-rev-1"):
        rev = next(c for c in created if c[1].startswith(prefix))
        assert "--model" not in rev, rev[1]
    # And each is RECORDED as this process's pin, so an option edited between this
    # filing and the card's release still reaches it (repin_before_release): a card
    # the driver filed mid-run is otherwise one it cannot re-point.
    assert {f"t_{calls.index(c) + 1}" for c in created} <= set(run.STATE.pinned)
    run.STATE.pinned.clear()


def test_a_re_review_of_a_board_without_a_pin_sends_no_model(monkeypatch, tmp_path):
    calls = _capture_rework(monkeypatch, tmp_path, {})
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_code_revision(state, 1, 1, "1. fix", owner="C")
    assert not [c for c in calls if "--model" in c]


def test_a_revision_card_inherits_the_lanes_model(monkeypatch, tmp_path):
    """A round's revision card REPEATS the card it revises, so it has to run where
    that card ran: pinned to the profile's model it would quietly change what the
    round tests on. The re-review keeps the pin, and the revision takes the lane's
    model — header first, board second."""
    calls = _capture_rework(monkeypatch, tmp_path, {**WORK, **PINNED})
    monkeypatch.setattr(run, "IDEAS_DIR", str(tmp_path))
    (tmp_path / "lane-1.md").write_text(
        "<!-- model: qwen38-27b -->\n<!-- provider: llama-swap -->\n## One\nbody\n")
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_revision(state, 1, 1, "1. fix the plan", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    run.file_code_revision(state, 1, 1, "1. fix the code", owner="C")
    created = [c for c in calls if c[0] == "create"]
    for prefix in ("P1-rev-1", "C1-rev-1"):
        rev = next(c for c in created if c[1].startswith(prefix))
        assert _arg(rev, "--model") == "qwen38-27b", rev[1]
    for prefix in ("RVp1-r2", "RVa1-r2"):
        rr = next(c for c in created if c[1].startswith(prefix))
        assert _arg(rr, "--model") == "deepseek-v4.1-flash", rr[1]


def test_a_revision_card_filed_with_no_lane_on_disk_takes_the_board_model(monkeypatch, tmp_path):
    calls = _capture_rework(monkeypatch, tmp_path, dict(WORK))
    monkeypatch.setattr(run, "IDEAS_DIR", str(tmp_path))   # no lane file on disk
    state = {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
             for c in ("Gi", "Gp", "Gc")}
    run.file_code_revision(state, 1, 1, "1. fix", owner="C")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("C1-rev-1"))
    assert _arg(rev, "--model") == "qwen38-27b"


# --- create-board.sh's pre-flight asks the graph, not a list ----------------

CREATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "driver",
                      "create-board.sh")


def _stub_hermes(tmp_path, profiles, skills=("writing-plans", "test-driven-development",
                                             "ocr-review")):
    """A `hermes` that answers `profile list` and `skills list` and refuses everything
    else, so the test stops at the pre-flight instead of touching a real profile or board.

    `skills` is what every profile reports as ENABLED. It is answered by the stub rather
    than left to the host because the pre-flight's second signal is the filesystem, and a
    host that happens to hold a skill would decide the test."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    rows = "".join(f"  {p} deepseek stopped\\n" for p in profiles)
    # The real CLI renders a rich table and TRUNCATES a name that outgrows the column,
    # so the stub renders the same cells — and the caller may pass an already-truncated
    # name to exercise the prefix match. `printf '%b'` because the row separators are
    # escapes: `%s` would print a literal backslash-n and the table would be one line.
    skill_rows = ("\u250f Name \u2513\\n"
                  + "".join(f"\u2502 {s} \u2502 local \u2502 enabled \u2502\\n"
                            for s in skills))
    stub = d / "hermes"
    stub.write_text("#!/usr/bin/env bash\n"
                    'if [ "$1" = "profile" ] && [ "$2" = "list" ]; then\n'
                    f"  printf '%s' '{rows}'\n"
                    "  exit 0\n"
                    "fi\n"
                    'case " $* " in *" skills list"*)\n'
                    f"  printf '%b' '{skill_rows}'\n"
                    "  exit 0 ;;\n"
                    "esac\n"
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
    cfg.setdefault("auto-gates", [])   # no default-workdir: the board's own work/
    (d / "board.json").write_text(json.dumps(cfg))
    return d


def _run_create(tmp_path, board_dir, profiles, skills=None):
    env = dict(os.environ)
    stub = (_stub_hermes(tmp_path, profiles) if skills is None
            else _stub_hermes(tmp_path, profiles, skills))
    env["PATH"] = str(stub) + os.pathsep + env["PATH"]
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


def test_the_pre_flight_notes_a_review_profile_without_ocr_review(tmp_path):
    """The review cards ask for `ocr-review` by name, so a profile that cannot see it runs
    them without it and nothing else says so."""
    code, out = _run_create(tmp_path, _board_dir(tmp_path), ["coder", "researcher"],
                            skills=("writing-plans",))
    assert "profile coder has no enabled skill 'ocr-review'" in out, out
    assert "/skill-sync" in out, out
    assert "not available" not in out, out      # a note, never the refusal


def test_the_pre_flight_is_quiet_when_the_review_profile_has_ocr_review(tmp_path):
    code, out = _run_create(tmp_path, _board_dir(tmp_path), ["coder", "researcher"])
    assert "no enabled skill" not in out, out


def test_a_released_card_is_pointed_at_the_board_it_reads_now(monkeypatch):
    """A board option edited while a lane waits has to reach the next CARD, not only the
    next run: a card is claimed on the model it holds, so a route the operator has since
    replaced would otherwise take the lane's next attempt too (measured 2026-09-26 —
    OpenCode Go timed out mid-lane and the parked review needed `set-model` by hand).
    Only a pin THIS process wrote is re-pointed: a run rejoined mid-lane keeps its pins,
    and a `set-model` a person made is not undone by a release.
    """
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a))
    monkeypatch.setattr(run, "log", lambda *a: None)
    monkeypatch.setattr(run, "card_model_args",
                        lambda code, lane: ["--model", "swift15-27b", "--provider", "llama-swap"])
    card = {"id": "rv1", "title": "RVp1: plan review - lane 1", "assignee": "coder"}
    try:
        # Never pinned by this process: a rejoined run, or a person's own `set-model`.
        run.repin_before_release(card, 1, "promotion")
        assert calls == []

        # Pinned at lane open on the route that has since died -> re-pointed, once.
        run.STATE.pinned["rv1"] = ("--model", "deepseek-v4.1-flash", "--provider", "opencode-go")
        run.repin_before_release(card, 1, "promotion")
        assert calls == [("set-model", "rv1", "swift15-27b", "--provider", "llama-swap")]
        assert run.STATE.pinned["rv1"] == ("--model", "swift15-27b", "--provider", "llama-swap")
        run.repin_before_release(card, 1, "promotion")     # already current
        assert len(calls) == 1

        # A gate runs no worker, so a flag on it buys nothing.
        run.STATE.pinned["gp1"] = ("--model", "deepseek-v4.1-flash")
        run.repin_before_release({"id": "gp1", "title": "Gp1: plan gate - lane 1",
                                  "assignee": "human-gate"}, 1, "promotion")
        assert len(calls) == 1

        # A board that names nothing any more clears the pin rather than leaving it.
        monkeypatch.setattr(run, "card_model_args", lambda code, lane: [])
        run.repin_before_release(card, 1, "promotion")
        assert calls[-1] == ("set-model", "rv1", "none")
        assert run.STATE.pinned["rv1"] == ()
    finally:
        run.STATE.pinned.pop("rv1", None)
        run.STATE.pinned.pop("gp1", None)
