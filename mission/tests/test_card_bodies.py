import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

BODIES = os.path.join(os.path.dirname(__file__), "..", "card-bodies")
BANNED = re.compile(r"wordcount|mvn |spring|maven|pom\.xml|task 1|task 2", re.I)
ALLOWED_PLACEHOLDERS = {
    "<RUNS>","<WORKDIR>", "<BOARD>", "<N>", "<IDEA>", "<REFINED>", "<PLAN>",
                        "<TARGETS>", "<PLAN_CHECKLIST>", "<TOOLCHAIN_BOUNDARY>", "<RESULT_FIELD>"}
FRAGMENT_FILES = sorted(file_lanes.FRAGMENTS.values())


def read(name):
    return open(os.path.join(BODIES, name)).read()


def body_texts():
    for _, body, *_ in lanes.LANE_CARDS:
        yield body, read(body)


def all_texts():
    yield from body_texts()
    for name in FRAGMENT_FILES:
        yield name, read(name)


def test_every_lane_card_has_a_body_file():
    for code, body, *_ in lanes.LANE_CARDS:
        assert os.path.exists(os.path.join(BODIES, body)), f"{code}: {body} missing"


def test_every_fragment_exists_and_includes_no_fragment():
    for name in FRAGMENT_FILES:
        text = read(name)
        assert not any(ph in text for ph in file_lanes.FRAGMENTS), name


def test_bodies_carry_no_scenario_specific_language():
    for name, text in all_texts():
        assert not BANNED.search(text), f"{name} mentions a specific scenario"


def test_bodies_use_only_known_placeholders():
    for name, text in all_texts():
        for ph in set(re.findall(r"<[A-Z_]+>", text)):
            assert ph in ALLOWED_PLACEHOLDERS, f"{name}: unknown placeholder {ph}"


def test_gate_bodies_never_instruct_a_commit_as_a_requirement():
    for body in ("gp-body.txt", "gc-body.txt"):
        text = read(body).lower()
        assert "the driver never commits" in text
        assert "commit sha in the result" not in text


def test_plan_card_reads_the_refined_idea():
    """The researcher's output must actually reach the planner.

    It did not until 2026-09-09: i-body told the researcher "the manager plans
    against THIS file" while p-body read only the raw snapshot, so every
    refinement was read once by a human at the gate and then dropped.
    """
    assert "<REFINED>" in read("p-body.txt"), "the plan card must read the refined idea"
    assert "<REFINED>" in read("i-body.txt"), "the researcher must write the refined idea"


def test_worker_bodies_point_at_the_snapshot_not_the_source():
    for body in ("p-body.txt", "rvp-body.txt", "rva-body.txt"):
        text = read(body)
        assert "<IDEA>" in text, f"{body} must reference the idea snapshot"
        assert not re.search(r"lane-(<N>|\d+)\.md", text), \
            f"{body} points at the mutable source, not the snapshot"


def test_worker_bodies_forbid_committing():
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        assert "do not commit" in read(body).lower(), body


def test_card_sessions_leave_their_profile_alone():
    """Card sessions patched skills in their own profile (manager's
    hermes-kanban-missions twice, coder's kanban-worker once) and every later
    card in that profile loaded the patched copy."""
    for body in ("i-body.txt", "p-body.txt", "rvp-body.txt", "tw-body.txt", "c-body.txt",
                 "rva-body.txt", "ti-body.txt", "rvc-body.txt"):
        assert "Do not write profile memories or create, patch or delete skills" in read(body), body


def test_nothing_temporary_is_written_outside_runs():
    """`work/` is what a human receives; every transient — scratch, patches,
    review files — lives under `<RUNS>/scratch/<card>/` (user rule)."""
    for name in sorted(os.listdir(BODIES)):
        if not name.endswith("-body.txt") or name.startswith("_"):
            continue
        with open(os.path.join(BODIES, name)) as fh:
            body = fh.read()
        assert "/tmp" not in body, f"{name} still sends something to /tmp"
        if "Scratch" in body or "review.md" in body or "patch.diff" in body:
            assert "<RUNS>" in body, f"{name} writes a transient outside runs/"


def test_the_hand_off_cards_never_stage_a_runs_path():
    """The researcher and planner hand-offs live under runs/, and every path
    there stays unstaged: they attach the document itself. A staged hand-off is
    what the operator sees in `git status` and asks about."""
    for name, path in (("i", "<REFINED>"), ("p", "<PLAN>")):
        with open(os.path.join(BODIES, f"{name}-body.txt")) as fh:
            body = fh.read()
        assert "git add -f" not in body, f"{name}-body still stages its hand-off"
        assert "UNSTAGED" in body
        assert f"cp {path}" in body and "attach" in body


def test_patch_attach_commands_carry_a_pathspec():
    """A bare `git diff --cached > patch` bundles EVERYTHING earlier cards
    staged — the E2E coder patch carried the refined idea, the plan and the
    tester's tests. Every command that writes a patch must scope to own paths."""
    for name, text in all_texts():
        for m in re.finditer(r"git diff --cached([^`\n]*?)\s+>\s*/tmp/", text):
            assert re.match(r"\s+--\s+\S", m.group(1)), f"{name}: {m.group(0)!r}"


def test_plan_card_and_plan_review_share_one_checklist():
    for body in ("p-body.txt", "rvp-body.txt"):
        assert "<PLAN_CHECKLIST>" in read(body), body
    checklist = read("_plan-checklist.txt")
    for n in range(1, 9):
        assert re.search(rf"^{n}\. ", checklist, re.M), f"checklist item {n}"


def test_plan_body_forbids_probes_and_allows_marked_unverified_facts():
    """The manager may not probe (Findings is the lane's only source of
    environment facts), so a fact Findings lack is marked, never guessed."""
    assert "No environment probes" in read("p-body.txt")
    assert "UNVERIFIED — executor confirms by:" in read("_plan-checklist.txt")


def test_refined_template_matches_the_idea_gate():
    text = read("i-body.txt")
    for name in lanes.REFINED_SECTIONS:
        assert f"## {name}\n" in text, name


def test_worker_bodies_state_when_they_are_done():
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        assert "DONE WHEN:" in read(body), body


def test_the_code_gate_hands_the_human_the_plan_too():
    """The gate-holder judges the success criteria the refined idea marks manual;
    the plan is where those criteria are implemented, so name its path."""
    assert "<PLAN>" in read("gc-body.txt")


def test_the_plan_card_and_review_ignore_foreign_index_entries():
    """`git diff --cached --name-only` lists the whole index. A foreign entry (an
    uncommitted deletion) sent P1 and RVp1 off to read the repository's files
    (2026-09-11); both now carry the rule."""
    assert "belong to other cards" in read("p-body.txt")
    assert "belongs to another card" in read("_plan-checklist.txt")


def test_plan_review_stays_inside_this_lane():
    """Item 8's command lists the WHOLE index, so a foreign staged entry (an
    uncommitted deletion, another lane's file) sent the reviewer off to audit the
    repository's docs, engine and tests for 4 minutes on a 30-line plan
    (2026-09-11). rva/rvc already say foreign entries are not theirs; RVp did not."""
    text = read("rvp-body.txt")
    assert "never a document under `docs/`" in text
    assert "not this lane's to judge" in text


def test_worker_bodies_send_their_report_to_the_result_field():
    """The `kanban_complete` tool's schema prefers `summary`, and every worker
    card on the 2026-09-11 run reported there — its result stayed empty while the
    body asked for `--result`. One fragment states the field for all five."""
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        assert "<RESULT_FIELD>" in read(body), body


def test_verdict_bodies_put_the_verdict_first_and_never_pass_an_unfinished_review():
    for body in ("rvp-body.txt", "rva-body.txt", "rvc-body.txt"):
        text = read(body)
        assert "first word is the verdict" in text, body
        assert "REJECT: incomplete review" in text, body


def test_no_body_carries_retired_mechanics():
    for name, text in all_texts():
        assert "LOOP_COMPLETE" not in text, name
        assert "transient" not in text.lower(), name
        assert "plans/" not in text, name
