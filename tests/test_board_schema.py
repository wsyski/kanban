"""`board_schema.validate` — the manifest pre-flight.

A key allowlist says a manifest names known options; it cannot say the manifest
describes a board that can exist. These pin the three faults that passed every
check the template had (found by reading, 2026-09-12): a per-lane list of
strings resolving to a truthy `"yes"`, a string `"false"` that `bool()` reads as
True on the switch whose wrong value wedges every card, and a duration the
auditor's parser scores as zero minutes.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import board_schema

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "template", "board_schema.py")


def problems(where="m", only=None, **cfg):
    return board_schema.validate(cfg, where=where, only=only)


def test_a_minimal_manifest_is_valid():
    assert problems(slug="b") == []


def test_a_manifest_may_carry_the_editors_schema_reference():
    """`$schema` is a JSON meta-key, not a board option: it is how an editor finds
    the generated schema, and refusing it would make the reference unusable."""
    assert board_schema.validate(
        {"lanes": 1, "$schema": "../../template/board.schema.json"}, where="b") == []


def test_a_typo_next_to_it_is_still_refused():
    assert board_schema.validate({"lanes": 1, "$schema": "x", "max_retry": 1},
                                 where="b")


def test_the_generated_schema_is_current():
    """DERIVED from the option table, so a stale file describes options that moved
    and an editor would validate against yesterday's set. Same contract as the
    generated flow diagram: regenerate with `--write-schema`."""
    assert board_schema.schema_is_current(), \
        "stale template/board.schema.json — run template/board_schema.py --write-schema"


def test_the_generated_schema_describes_the_same_options():
    """A relationship between two pieces of data, never a snapshot: every option is
    in it, nothing else is, the per-lane ones take a list, and the one-attempt ones
    are const 1."""
    props = board_schema.json_schema()["properties"]
    assert set(props) == set(board_schema.BOARD_KEYS) | {"$schema"}
    for key in board_schema.PER_LANE:
        assert "oneOf" in props[key], key
    for key in board_schema.ONE_ATTEMPT:
        assert props[key]["const"] == 1, key
    for role in sorted(board_schema.ROLES):
        assert role in props["assignees"]["propertyNames"]["enum"], role


def test_every_shipped_manifest_points_at_the_schema():
    import glob, json
    boards = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "boards")
    for path in sorted(glob.glob(os.path.join(boards, "*", "board.json"))):
        assert json.load(open(path)).get("$schema") == \
            "../../template/board.schema.json", path


def test_the_header_set_is_the_per_lane_set():
    """Not a second list. A per-lane option gets its header for free, and cannot
    be added to one side only — which is how the two sets drifted before."""
    assert board_schema.HEADER_KEYS is board_schema.PER_LANE
    assert board_schema.PER_LANE < board_schema.BOARD_KEYS
    assert board_schema.PER_LANE == {"refinement", "max-reworks", "unit-tests",
                                     "integration-tests",
                                     "model", "provider"}


def test_a_per_lane_list_of_strings_is_rejected():
    """`["yes", "no"]` is the right length and resolves to a truthy string, so
    both lanes would get integration cards whatever the author meant."""
    found = problems(slug="b", lanes=2, **{"integration-tests": ["yes", "no"]})
    assert len(found) == 2 and all("expected true or false" in p for p in found)


def test_a_stringly_false_boolean_is_rejected():
    assert problems(slug="b", refinement="false") == \
        ["m: 'refinement' expected true or false, got 'false'"]


def test_a_duration_the_auditor_reads_as_zero_is_rejected():
    assert problems(slug="b", **{"max-runtime": "banana"})
    assert problems(slug="b", **{"max-runtime": "10m"}) == []
    assert problems(slug="b", **{"max-runtime": "1h30m"}) == []


def test_a_board_level_option_may_not_be_a_list():
    found = problems(slug="b", sequential=[True])
    assert len(found) == 1 and "not a list" in found[0]


def test_a_per_lane_list_must_have_one_entry_per_lane():
    found = problems(slug="b", lanes=3, **{"unit-tests": [True, False]})
    assert len(found) == 1 and "2 entries for 3 lane(s)" in found[0]


def test_lanes_must_be_a_count_and_a_bool_is_not_one():
    assert problems(slug="b", lanes=True)
    assert problems(slug="b", lanes=0)


def test_every_problem_is_reported_not_just_the_first():
    """A manifest is hand-edited; a validator that stops at the first fault turns
    one mistake into one round trip each."""
    found = problems(slug="b", lanes=2, nope=1,
                     goal="false", **{"max-runtime": "banana"})
    assert len(found) == 3, found


def test_a_renamed_option_names_its_replacement():
    """A rename is not a typo, so punctuation-blindness cannot find it."""
    assert "did you mean 'name'" in problems(slug="b", title="T")[0]
    assert "did you mean 'goal-cards'" in problems(slug="b", goal_mode=False)[0]
    assert "did you mean 'goal-cards'" in problems(slug="b", goal=True)[0], \
        "the retired switch names its replacement"
    assert "did you mean 'default-workdir'" in problems(slug="b", workdir="/tmp")[0]
    assert "did you mean 'max-runtime'" in problems(slug="b", max_runtime="4m")[0]


def test_pass_through_options_carry_hermes_own_spelling():
    """An option that reaches Hermes is named after the flag it becomes: a name we
    invent for a parameter Hermes already named is a name nobody can grep for."""
    for key, flag in board_schema.PASS_THROUGH.items():
        assert flag == "--" + key, (key, flag)


def test_the_script_refuses_a_bad_manifest_with_a_nonzero_exit(tmp_path):
    """The scripts gate on the exit status, so it has to be the contract."""
    bad = tmp_path / "board.json"
    bad.write_text(json.dumps({"slug": "b", "max_runtime": "4m"}))
    r = subprocess.run([sys.executable, SCRIPT, str(bad)],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "max-runtime" in (r.stdout + r.stderr)

    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"slug": "b", "max-runtime": "4m"}))
    assert subprocess.run([sys.executable, SCRIPT, str(good)]).returncode == 0


def test_malformed_json_is_a_manifest_problem_not_a_traceback(tmp_path):
    p = tmp_path / "board.json"
    p.write_text("{ nope")
    r = subprocess.run([sys.executable, SCRIPT, str(p)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "Traceback" not in r.stderr
    assert "not valid JSON" in r.stderr


def test_the_schema_prints_every_option():
    text = board_schema.schema_text()
    for key in board_schema.BOARD_KEYS:
        assert key in text


# ---- idea headers: the same table, the other file -------------------------

def idea(text):
    """Headers only — the body rules have their own tests below."""
    return board_schema.validate_headers(text, where="lane-1.md")


def test_a_good_header_set_is_valid():
    assert idea("<!-- unit-tests: false -->\n<!-- unit-tests: true -->\n# Idea\n") == []


def test_a_comment_that_is_not_a_header_is_left_alone():
    """An HTML comment without a `key: value` shape is prose, and prose it stays."""
    assert idea("<!-- just a note -->\n<!-- TODO -->\n") == []


def test_headers_are_validated_through_the_manifest_path():
    """The bridge is JSON, because that is what the manifest is written in — so a
    header's value reaches the same judgement the same option gets in board.json."""
    assert board_schema.headers_to_cfg({"refinement": "true", "unit-tests": "false"}) \
        == {"refinement": True, "unit-tests": False}
    assert board_schema.headers_to_cfg({"max-runtime": "10m"}) == {"max-runtime": "10m"}


def test_the_silently_swallowed_underscore_is_caught():
    """`lanes._HEADER_RE`'s key class is [A-Za-z0-9-], so this line does not match,
    is not an error, and becomes body prose — the option is ignored and nothing
    says so. It is also invisible in any rendered view."""
    found = idea("<!-- unit_tests: true -->\n")
    assert len(found) == 1
    assert "write 'unit-tests'" in found[0] and "silently ignored" in found[0]


def test_trailing_text_after_a_header_is_caught():
    found = idea("<!-- unit-tests: true --> keep\n")
    assert len(found) == 1 and "whole line" in found[0]


def test_a_bad_header_value_is_caught_at_the_header_not_later():
    """`parse_idea` accepts this and `_as_bool` dies later, in another caller."""
    assert idea("<!-- unit-tests: yes -->\n") == \
        ["lane-1.md:1: 'unit-tests' expected true or false, got 'yes'"]


def test_a_board_level_option_is_refused_as_a_header():
    found = idea("# Idea\n<!-- max-runtime: 10m -->\n")
    assert len(found) == 1 and found[0].startswith("lane-1.md:2:")
    assert "board-level option" in found[0]


def test_a_header_may_not_carry_the_per_lane_array_form():
    found = idea("<!-- unit-tests: [true] -->\n")
    assert len(found) == 1 and "one lane" in found[0]


def test_a_header_problem_names_its_line():
    found = idea("# Idea\n\n\n<!-- unit-tests: yes -->\n")
    assert found[0].startswith("lane-1.md:4:")


def test_the_script_refuses_a_bad_idea_file(tmp_path):
    p = tmp_path / "lane-1.md"
    p.write_text("<!-- unit_tests: true -->\n# Idea\n")
    r = subprocess.run([sys.executable, SCRIPT, str(p)], capture_output=True, text=True)
    assert r.returncode != 0 and "idea headers rejected" in r.stderr


def test_every_shipped_idea_passes_the_header_schema():
    """The manifests are red on the rename; the ideas are not — every shipped
    lane file's headers are already valid against the schema."""
    boards = os.path.join(REPO, "boards")
    for b in sorted(os.listdir(boards)):
        d = os.path.join(boards, b)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if name.startswith("lane-") and name.endswith(".md"):
                path = os.path.join(d, name)
                assert board_schema.validate_idea(open(path).read(), where=path) == [], path


def test_a_work_directory_must_be_absolute():
    """Three different current directories resolve it — create-board.sh's, the
    driver's, and each card's, which runs IN it — so a relative path is a
    different tree depending on who asks. `~` is worse: nothing expands it, so
    os.path.abspath makes a literal `~` directory inside the repo (2026-09-12)."""
    for bad in ("work", "./work", "~/.hermes/profiles/trader"):
        found = problems(slug="b", **{"default-workdir": bad})
        assert len(found) == 1 and "absolute path" in found[0], bad
    assert problems(slug="b", **{"default-workdir": "/srv/project"}) == []


def test_omitting_the_work_directory_is_the_normal_case():
    """Unset means the board's own work/ — every board but two."""
    assert problems(slug="b") == []
    assert board_schema.OPTIONS["default-workdir"][1] is None


def test_shipped_work_directories_are_absolute():
    for b in sorted(os.listdir(os.path.join(REPO, "boards"))):
        p = os.path.join(REPO, "boards", b, "board.json")
        if not os.path.isfile(p):
            continue
        wd = json.load(open(p)).get("default-workdir")
        assert wd is None or os.path.isabs(wd), (b, wd)


# ---- the idea's prose, checked at the doors --------------------------------

def body(text):
    return board_schema.validate_idea(text, where="lane-1.md")


def test_an_empty_idea_file_is_refused():
    """A lane whose idea is empty stops the chain, and the board cannot tell that
    from one still being typed."""
    found = body("<!-- unit-tests: true -->\n")
    assert len(found) == 1 and "no idea here" in found[0]


def test_an_idea_without_done_means_is_refused():
    found = body("## Idea 1: x\n\nbuild the thing\n")
    assert len(found) == 1 and "Done means" in found[0]


def test_an_empty_done_means_is_refused():
    found = body("## Idea 1: x\n\nbuild it\n\n### Done means\n")
    assert len(found) == 1 and "is empty" in found[0]


def test_a_complete_idea_passes():
    assert body("## Idea 1: x\n\nbuild it\n\n### Done means\n\n- it is built\n") == []


def test_the_body_rules_do_not_reach_parse_idea():
    """`parse_idea` reads options; a missing success criterion is the doors'
    business, where the person who wrote the idea can still fix it."""
    import lanes
    headers, _b = lanes.parse_idea("## Idea\n<!-- unit-tests: true -->\n\nno criterion\n")
    assert headers == {"unit-tests": "true"}


def test_every_shipped_idea_satisfies_the_body_rules():
    boards = os.path.join(REPO, "boards")
    for b in sorted(os.listdir(boards)):
        d = os.path.join(boards, b)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("lane-") and name.endswith(".md"):
                path = os.path.join(d, name)
                assert board_schema.validate_idea(open(path).read(), where=path) == [], path


# ---- options that were hardcoded Hermes parameters -------------------------

def test_goal_max_turns_is_an_option_and_reaches_the_flag():
    import lanes
    assert board_schema.PASS_THROUGH["goal-max-turns"] == "--goal-max-turns"
    assert lanes.goal_args("I", cards=["I"], max_turns=12) == ["--goal", "--goal-max-turns", "12"]
    # unset falls back to the schema's default, not a literal in lanes.py
    assert lanes.goal_args("I", cards=["I"])[-1] == str(board_schema.OPTIONS["goal-max-turns"][1])


def test_a_goal_flag_still_never_reaches_a_reviewer_or_gate():
    """A goal-loop judge can push a card whose success case is BLOCKING into
    completing, silently opening the gate it guards."""
    import lanes
    for code in ("Gi", "Gp", "Gc", "RVp", "RVa", "RVc"):
        assert lanes.goal_args(code, cards=[code], max_turns=99) == [], code


def test_timeout_min_is_the_drivers_own_cap():
    """Hermes-shaped name, but start-board.sh passes it to run.py — so it is an
    option with no `hermes kanban` flag, and the schema says so rather than
    inventing one."""
    assert "timeout-min" in board_schema.BOARD_KEYS
    assert "timeout-min" not in board_schema.PASS_THROUGH
    assert "timeout-min" in board_schema.DRIVER_OPTIONS
    assert board_schema.validate({"slug": "b", "timeout-min": 90}) == []
    assert board_schema.validate({"slug": "b", "timeout-min": 0})


# ---- an external work directory is another project's tree ------------------

def test_an_absent_work_directory_is_reported(tmp_path):
    found = board_schema.workdir_problems(
        {"default-workdir": str(tmp_path / "nope")}, where="m")
    assert len(found) == 1 and "does not exist on this host" in found[0]


def test_a_board_owned_work_directory_asks_none_of_this():
    assert board_schema.workdir_problems({}) == []


def test_any_host_validates_a_board_whose_workdir_is_absent(tmp_path):
    """A CI runner is not the board's host: an owner's absolute `default-workdir` cannot be
    there, so the existence half must be switchable off — without weakening the declaration
    checks, which is what the strict default (previous test) keeps doing."""
    cfg = {"slug": "b", "default-workdir": str(tmp_path / "nope")}
    assert board_schema.workdir_problems(cfg, any_host=True) == []
    manifest = tmp_path / "board.json"
    manifest.write_text(json.dumps(cfg))
    assert subprocess.run([sys.executable, SCRIPT, "--any-host", str(manifest)]).returncode == 0
    assert subprocess.run([sys.executable, SCRIPT, str(manifest)]).returncode != 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(dict(cfg, **{"goal-cards": "C"})))
    assert subprocess.run([sys.executable, SCRIPT, "--any-host", str(bad)]).returncode != 0
    assert subprocess.run([sys.executable, SCRIPT, "--any-host"]).returncode != 0


def test_a_dirty_index_in_the_work_directory_is_a_notice_not_a_fault(tmp_path):
    """USER RULE (2026-09-12): the board promises nothing about the work directory's
    contents — staged and unstaged files alike are the lane's working material — so a
    pending entry is reported, never grounds to refuse. It still matters: `git diff
    --cached` lists the WHOLE index and the operator's entries reach a reviewer, which
    is why the notice says to scope every check with a pathspec (E17 carries the
    failing half, at the audit)."""
    import subprocess
    wd = tmp_path / "repo"
    wd.mkdir()
    subprocess.run(["git", "init", "-q", str(wd)], check=True)
    (wd / "theirs.txt").write_text("mine, not the lane's\n")
    subprocess.run(["git", "-C", str(wd), "add", "theirs.txt"], check=True)
    assert board_schema.workdir_problems({"default-workdir": str(wd)}, where="m") == []
    notices = board_schema.workdir_notices({"default-workdir": str(wd)}, where="m")
    assert len(notices) == 1 and "index" in notices[0] and "theirs.txt" in notices[0]
    assert "pathspec" in notices[0]

    subprocess.run(["git", "-C", str(wd), "reset", "-q"], check=True)
    assert board_schema.workdir_notices({"default-workdir": str(wd)}, where="m") == []


# ---- options added for what the manifest could not say ---------------------

def test_the_rework_retry_budget_is_its_own_option():
    """1 by rule (2026-09-12): a failure is final, and the only thing that retries work
    is the REVIEW that sent it back, by filing the revision card. The option stays
    declared because Hermes names it, and refuses anything else, so a manifest cannot
    re-enable a dispatcher retry. A revision card takes the same 1 — the board option
    that used to hold a second number is gone."""
    assert "must be 1" in problems(slug="b", **{"max-retries": 3})[0]
    assert "unknown option" in problems(slug="b", **{"max_retries": 2})[0]
    assert "rework-max-retries" not in board_schema.BOARD_KEYS
    assert "rework-max-retries" not in board_schema.DRIVER_OPTIONS


def test_a_revision_card_is_one_attempt_too():
    """No manifest value can change it: the knob that could ask for a second attempt at
    a revision is gone, and the count a board may choose is `max-reworks` (rounds the
    DRIVER files), not dispatcher retries."""
    import run
    assert run.rework_retries() == "1"


def test_the_roles_a_board_may_remap_are_the_roles_the_graph_fills():
    """A key nothing reads would be accepted silently; a role the graph gained
    would be refused as unknown. One set, checked against the graph."""
    import lanes
    assert board_schema.ROLES == {r[2] for r in lanes.LANE_CARDS}


def test_assignees_remaps_a_role_everywhere_it_appears():
    import lanes
    cards = lanes.lane_cards(1, assignees={"coder": "senior", "researcher": "qa"})
    for c in cards:
        if c["role"] == "coder":
            assert c["assignee"] == "senior", c["id"]
        elif c["role"] == "researcher":
            assert c["assignee"] == "qa", c["id"]
        else:
            assert c["assignee"] == lanes.assignee_for(c["role"]), c["id"]


def test_every_filed_card_carries_one_attempt():
    """USER RULE (2026-09-12): only a failed REVIEW retries. Nothing else does — a
    card that times out, crashes or never spawns is final, so filing must never ask
    the dispatcher for a second attempt (the 3-retry budget on cards feeding a
    reviewer was exactly that, and it is gone)."""
    import file_lanes
    import lanes
    for remap in (None, {"coder": "senior"}):
        cards = lanes.lane_cards(1, assignees=remap)
        assert not hasattr(file_lanes, "REVIEWER_FEED_MAX_RETRIES")
        assert not hasattr(file_lanes, "_retries_for")
        assert file_lanes.DEFAULT_MAX_RETRIES == 1, remap
        assert all(c["role"] for c in cards)


def test_an_unknown_role_or_empty_profile_is_refused():
    assert "unknown role" in problems(slug="b", assignees={"nope": "x"})[0]
    assert "non-empty string" in problems(slug="b", assignees={"coder": ""})[0]
    assert "mapping" in problems(slug="b", assignees="notadict")[0]


# ---- goal-cards: the goal judge on some worker cards only --------------------

def test_goal_cards_is_a_board_level_list_of_worker_codes():
    """A list here names cards, not lanes: it must not be read as the per-lane form."""
    assert problems(slug="b", lanes=2, **{"goal-cards": ["C", "TI"]}) == []
    assert "goal-cards" not in board_schema.PER_LANE


def test_goal_cards_refuses_a_code_that_is_not_a_worker_card():
    for bad in (["Gc"], ["RVa"], ["X"], "C"):
        assert problems(slug="b", **{"goal-cards": bad}), bad


def test_goal_cards_narrows_which_cards_get_the_goal_flag():
    import lanes
    flags = ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("C", cards=["C", "TI"]) == flags
    assert lanes.goal_args("P", cards=["C", "TI"]) == []
    # no list is no judge: there is no switch that could arm one behind it
    assert lanes.goal_args("C") == [] and lanes.goal_args("C", cards=[]) == []
    # a gate or review never gets it, whatever the list says
    assert lanes.goal_args("Gc", cards=["Gc"]) == []


def test_goal_profiles_names_the_profiles_whose_judge_decides_a_card():
    import lanes
    assert lanes.goal_profiles({}) == {}
    assert lanes.goal_profiles({"goal-cards": []}) == {}
    assert lanes.goal_profiles({"goal-cards": ["C", "TI"],
                                "integration-tests": False}) == {"coder": ["C"]}
    everything = lanes.goal_profiles({"goal-cards": list(board_schema.GOAL_CODES)})
    assert everything["researcher"] == ["I"] and "RVa" not in everything["coder"]


# ---- auto-gates: true/false, or the gates the driver completes itself --------

def test_auto_gates_takes_a_list_of_gate_codes():
    assert problems(slug="b", **{"auto-gates": ["Gi"]}) == []
    assert problems(slug="b", **{"auto-gates": ["Gi", "Gp", "Gc"]}) == []
    assert problems(slug="b", **{"auto-gates": ["RVa"]})
    assert problems(slug="b", **{"auto-gates": ["gi"]}), "codes are spelled as the graph spells them"


def test_a_boolean_is_no_longer_accepted_for_auto_gates():
    """One shape, always an array: `true` was ambiguous beside the per-lane form."""
    for bad in (True, False, [True, False], "Gi"):
        assert problems(slug="b", lanes=2, **{"auto-gates": bad}), bad


def test_gate_is_auto_reads_the_list():
    assert board_schema.gate_is_auto(["Gi"], "Gi") is True
    assert board_schema.gate_is_auto(["Gi"], "Gp") is False
    assert board_schema.gate_is_auto([], "Gi") is False
    assert board_schema.gate_is_auto(None, "Gc") is False


def test_auto_gates_is_board_level_not_per_lane():
    """Which gates a person holds is a property of the board, like who is watching it —
    and a per-lane form would collide with the code list."""
    assert "auto-gates" not in board_schema.PER_LANE
    assert problems(where="lane-1.md", only=board_schema.HEADER_KEYS,
                    **{"auto-gates": ["Gi"]})


def test_an_empty_gate_list_is_every_gate_human():
    assert problems(slug="b", lanes=2, **{"auto-gates": []}) == []
    for code in board_schema.GATE_CODES:
        assert board_schema.gate_is_auto([], code) is False


def test_an_empty_goal_card_list_arms_nothing():
    """`[]` is the explicit "no card", the same shape `auto-gates: []` carries."""
    import lanes
    assert problems(slug="b", **{"goal-cards": []}) == []
    assert problems(slug="b", **{"goal-cards": [], "goal-max-turns": 80}) == []
    assert lanes.goal_args("C", cards=[]) == []
