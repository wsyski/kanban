"""The manifest dict has ONE meaning, whether or not the board still has its board.json.

The old fallback was a four-key dict that said `integration-tests: False` against the
option table, create-board.sh's own --help and its profile pre-flight (2026-09-23
review, Important 6 and the comment finding I40). "No manifest" now means exactly what
"a manifest that names nothing" means: the option table's defaults.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import board_schema
import lanes
import run

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _board(tmp_path, monkeypatch, manifest=None):
    board_dir = tmp_path / "boards" / "b"
    board_dir.mkdir(parents=True, exist_ok=True)
    cfg = board_dir / "board.json"
    if manifest is None:
        if cfg.exists():
            cfg.unlink()
    else:
        cfg.write_text(json.dumps(manifest))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "BOARD_DIR", str(board_dir))
    monkeypatch.setattr(run, "IDEAS_DIR", str(board_dir))
    return board_dir


def test_no_manifest_means_the_same_board_as_an_empty_one(tmp_path, monkeypatch):
    """The property that matters: a consumer cannot tell which one it got."""
    _board(tmp_path, monkeypatch)
    absent = run.manifest()
    _board(tmp_path, monkeypatch, {})
    assert absent == run.manifest() == {"slug": "b"}


def test_a_board_without_its_manifest_keeps_its_integration_cards(tmp_path, monkeypatch):
    """The fallback's `integration-tests: False` silently dropped every lane's
    integration cards on a board whose manifest was gone — against the option table
    (True) and the --help that promises "unit and integration tests on"."""
    _board(tmp_path, monkeypatch)
    resolved = lanes.resolve_lane_options(run.manifest(), {}, 1)
    assert resolved["integration-tests"] is True
    assert resolved["integration-tests"] == board_schema.OPTIONS["integration-tests"][1]


def test_the_manifest_create_board_writes_does_not_contradict_its_help():
    """The heredoc wrote `"integration-tests": false` while the same script's --help
    says a --slug board gets "refinement, unit and integration tests on" and its profile
    pre-flight already demanded the integration profiles. Omitting the key IS the
    option table's default."""
    src = open(os.path.join(REPO, "driver", "create-board.sh")).read()
    heredoc = [l for l in src.splitlines() if "printf '{" in l]
    assert heredoc, "the manifest printf moved — read create-board.sh"
    assert all("integration-tests" not in l for l in heredoc), heredoc


def test_the_resolved_lane_options_are_the_per_lane_keys_plus_the_idea(tmp_path, monkeypatch):
    """`lane_options`' shape, pinned: every PER_LANE key plus the idea's own body under
    "idea" — and `refinement` is ALWAYS present, which is what makes a
    `.get("refinement", True)` on it dead code."""
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    (board_dir / "lane-1.md").write_text(
        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n"
        "### Done means\n\nit works\n")
    opts = run.lane_options(1)
    assert set(opts) == set(board_schema.PER_LANE) | {"idea"}, sorted(opts)
    assert opts["refinement"] is True
    assert opts["integration-tests"] is False        # the header won
    assert "it works" in opts["idea"]


def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
    """The None state, pinned: no file at all. (A file that EXISTS and is blank is the
    next task's — the two states must stop sharing one value.)"""
    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    assert run.lane_options(1) is None
    assert run.lane_refinement(1) is True


def test_a_manifest_the_option_table_refuses_stops_the_driver(tmp_path, monkeypatch):
    """`max-runtime: "banana"` reached the engine: the auditor's parser reads it as no
    ceiling. Every manifest read but validate_armed's was raw (review Important 9)."""
    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1, "max-runtime": "banana"})
    with pytest.raises(SystemExit) as excinfo:
        run.require_manifest_valid()
    assert "max-runtime" in str(excinfo.value), str(excinfo.value)


def test_every_shipped_manifest_passes_the_drivers_own_gate(monkeypatch):
    """The other side, and the one that matters most: this gate must not halt a board
    that ships (all seven, measured 2026-09-24)."""
    boards = os.path.join(REPO, "boards")
    slugs = [s for s in sorted(os.listdir(boards))
             if os.path.exists(os.path.join(boards, s, "board.json"))]
    assert len(slugs) >= 7, slugs
    for slug in slugs:
        monkeypatch.setattr(run, "BOARD", slug)
        monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
        run.require_manifest_valid()                   # must not raise


def test_a_blank_idea_file_is_not_the_same_as_no_idea_file(tmp_path, monkeypatch):
    """read_idea returns None for "no file" AND for "empty file", and the driver read
    that one value as "no idea yet" in the completion scan and as "defaults apply" in
    lane_refinement. A file somebody emptied is neither (review types I6/T-6)."""
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
    (board_dir / "lane-1.md").write_text("   \n\n")
    with pytest.raises(run.IdeaFileBlank) as excinfo:
        run.lane_options(1)
    assert "lane-1.md" in str(excinfo.value)
    assert run.lane_options(2) is None               # a lane with no file is still None


def test_an_emptied_idea_file_halts_the_completion_scan(tmp_path, monkeypatch):
    """The scan broke on `lane_options(...) is None` and returned "not finished" for
    ever, so an emptied lane-1.md left the board unable to finish with nothing in the
    log saying why. It halts now, naming the file."""
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "send_notice", lambda *a, **k: None)
    state = {"P1: implementation plan - lane 1": {}, "P2: implementation plan - lane 2": {}}
    (board_dir / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
    assert run.last_lane_with_idea(state) == 1          # lane 2 has no file: the chain stops
    assert not run.STATE.halted["reason"]
    (board_dir / "lane-1.md").write_text("")
    assert run.last_lane_with_idea(state) == 0
    assert "lane-1.md" in run.STATE.halted["reason"], run.STATE.halted


def test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider(monkeypatch):
    """The rule lane_model_opts' docstring states, through the driver's one helper: a
    lane that names only a model is not handed the board's provider (review Important 8)."""
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "provider": "cloud-provider",
                                                  "model": "board-model"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
    assert run.card_model_args("C", 1) == ["--model", "qwen38-27b"]
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    assert run.card_model_args("C", 1) == ["--model", "board-model",
                                           "--provider", "cloud-provider"]


def test_the_drivers_model_flags_resolve_a_per_lane_board_array_by_the_lane(monkeypatch):
    """The driver's lane-scoped model call is `card_model_args`, and the card it is
    asked about belongs to ONE lane. `model`/`provider` are per-lane options and
    board_schema accepts the array form ("one backend, a model per lane" —
    test_board_schema pins it, create-board.sh's help calls it "a list with exactly one
    value per lane"), so the driver resolves the list by that lane the way filing does
    (`lanes.lane_value`, `file_lanes.file_board`). The raw list reached `_model_pair`
    and then `subprocess`, which raises `TypeError: expected str ... not list`."""
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 2, "model": ["m1", "m2"],
                                                 "provider": ["p1", "p2"]})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    assert run.card_model_args("C", 1) == ["--model", "m1", "--provider", "p1"]
    assert run.card_model_args("C", 2) == ["--model", "m2", "--provider", "p2"]
    # ...and the card's own model reader — the one the halt names out loud — is a str
    assert run.card_model("C", 2) == "m2"
    # the lane's header still wins over the board's array, as it does over a scalar
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "hdr"})
    assert run.card_model_args("C", 2) == ["--model", "hdr"]
    # the review pin is board-level: an array work model does not disturb it
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 2, "model": ["m1", "m2"],
                                                 "provider": ["p1", "p2"],
                                                 "model_override": "rev",
                                                 "provider_override": "rvp"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    assert run.card_model_args("RVa", 2) == ["--model", "rev", "--provider", "rvp"]


def test_a_board_model_array_with_no_entry_for_the_lane_is_refused_naming_it(monkeypatch):
    """A list with no entry for the lane cannot be honoured, and inventing one (or
    filing a model-less card) is worse than refusing — the same call `file_lanes` makes
    at filing. board_schema refuses the shape at the door (`one entry per lane`), so a
    caller that gets here has skipped the door; it gets `lanes.lane_value`'s named
    error, not a list in the flag pair."""
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "model": ["m1"]})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    with pytest.raises(ValueError, match="lane 2"):
        run.card_model_args("C", 2)
    # a scalar is never indexed, so lane 2 of a one-lane board is not a fault
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "model": "m1"})
    assert run.card_model_args("C", 2) == ["--model", "m1"]


def test_a_scalar_board_pair_is_byte_identical_for_every_lane(monkeypatch):
    """The property the fix must not break: anything that is not a list comes back
    unchanged, so a scalar board's flags are the same tokens in the same order on every
    lane — the very list `lanes.model_args` builds from the raw manifest (the filing
    side pins the same property, test_file_lanes)."""
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 3, "model": "m1",
                                                 "provider": "p1"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    want = lanes.model_args("C", run.manifest())
    assert want == ["--model", "m1", "--provider", "p1"]
    assert [run.card_model_args("C", lane) for lane in (1, 2, 3)] == [want] * 3
    assert [run.card_model("C", lane) for lane in (1, 2, 3)] == ["m1"] * 3
    # a board that names nothing is still no flag at all, on every lane
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 3})
    assert [run.card_model_args("C", lane) for lane in (1, 2, 3)] == [[], [], []]
