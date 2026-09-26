import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
import file_lanes
import lanes
import run

BODIES = os.path.join(os.path.dirname(__file__), "..", "template", "card-bodies")
BANNED = re.compile(r"wordcount|mvn |spring|maven|pom\.xml|task 1|task 2", re.I)
def allowed_placeholders():
    """Every placeholder render_body actually resolves, plus the one it deliberately
    leaves for the worker.

    Derived, not listed: a hand-kept copy beside a computable set drifts the moment a
    placeholder is added, and it drifts SILENTLY — the check below then passes for a
    name nothing resolves.
    """
    values = card_render.render_body_values(repo="/r", board="b", workdir="/w",
                                           lane=1, targets=(), run_id="r1")
    return set(values) | set(card_render.FRAGMENTS) | run.LEFT_FOR_THE_WORKER
FRAGMENT_FILES = sorted(card_render.FRAGMENTS.values())


def read(name):
    return open(os.path.join(BODIES, name)).read()


def body_texts():
    for _, body, *_ in lanes.LANE_CARDS:
        yield body, read(body)


def all_texts():
    yield from body_texts()
    for name in FRAGMENT_FILES:
        yield name, read(name)


def test_the_integration_card_may_change_anything_to_make_the_integration_tests_work():
    """HUMAN RULE (2026-09-13): the integration card may change everything and the test
    must work — the implementation, the TW card's unit tests, build and configuration.
    What keeps it reviewable: every change outside its own tests is staged, attached
    apart from them and named with its reason, and the final review judges it."""
    ti = read("ti-body.txt")
    assert "MAY change ANY file" in ti
    for what in ("implementation", "the TW card's unit tests", "build", "configuration"):
        assert what in ti, what
    assert "patch-code.diff" in ti
    assert "WHY the end-to-end run needed it" in ti
    assert "may not change the plan" in ti
    assert "no change outside the integration tests" in ti
    done = ti.split("DONE WHEN:", 1)[1].split("\n\n", 1)[0]
    assert "integration suite is GREEN" in done and "unit suite still green" in done


def test_the_final_review_re_derives_the_code_checks_on_the_tree_the_gate_gets():
    """The implementation review runs BEFORE the integration card, so its verdict
    cannot cover a code change that card made: the final review is the one that
    reviews the tree the gate receives."""
    rvc = read("rvc-body.txt")
    assert "as it STANDS is the plan's implementation" in rvc
    assert "the implementation review saw it BEFORE these changes" in rvc
    assert "outside its own integration test files" in rvc
    assert "REJECT with `OWNER: TI`" in rvc
    assert "PASS requires" in rvc and "green" in rvc
    assert "OWNER: TI` for an integration test" in rvc
    # and the earlier review knows the limit of its own verdict
    rva = read("rva-body.txt")
    assert "the FINAL review re-derives the code checks" in rva


def test_the_plan_names_the_seam_the_integration_tests_drive():
    checklist = read("_plan-checklist.txt")
    assert "names the SEAM it drives" in checklist
    assert "instead of inventing an interface at the end" in checklist


def test_every_lane_card_has_a_body_file():
    for code, body, *_ in lanes.LANE_CARDS:
        assert os.path.exists(os.path.join(BODIES, body)), f"{code}: {body} missing"


def test_every_fragment_exists_and_includes_no_fragment():
    for name in FRAGMENT_FILES:
        text = read(name)
        assert not any(ph in text for ph in card_render.FRAGMENTS), name


def test_bodies_carry_no_scenario_specific_language():
    for name, text in all_texts():
        assert not BANNED.search(text), f"{name} mentions a specific scenario"


def test_bodies_use_only_known_placeholders():
    """The regex has to allow hyphens. `<[A-Z_]+>` matched no hyphenated name, so
    <WORKDIR-STATE> and <YOUR-CARD-ID> were never checked at all and a typo in either
    would have shipped."""
    allowed = allowed_placeholders()
    assert "<WORKDIR-STATE>" in allowed and "<YOUR-CARD-ID>" in allowed
    for name, text in all_texts():
        for ph in set(run._PLACEHOLDER_RE.findall(text)):
            assert ph in allowed, f"{name}: unknown placeholder {ph}"


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


def test_the_result_fragment_names_both_valid_outcomes():
    """USER RULE (2026-09-12): a lane that changes nothing because nothing needed
    changing is a valid ending, and a lane pointed at an existing project discovers
    that by reading the directory. Both rules have to be in the text a worker reads,
    or it invents work to look busy."""
    text = read("_result-field.txt")
    assert "CHANGED:" in text and "NO CHANGE:" in text
    tw = read("tw-body.txt")
    assert "manufacture a FAIL" in tw
    assert "already pass" in tw
    assert "WORK DIRECTORY IS THE INPUT" in tw
    assert "expect FAIL" not in read("_plan-checklist.txt")


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


def test_both_code_reviews_run_ocr_review():
    """RVa and RVc force-load `ocr-review` (lanes.LANE_CARDS), so their bodies must ASK for
    the dispatch — the worker contract permits only a dispatch the card asks for — and must
    keep the verdict theirs: a finding is evidence for the card's own checks, never a
    rejection ground of its own."""
    for body in ("rva-body.txt", "rvc-body.txt"):
        text = read(body)
        assert "OCR-REVIEW" in text, body
        assert "EVIDENCE" in text, body
        assert "read-only" in text, body


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


def test_the_board_stages_only_the_lanes_own_work():
    """User rule (2026-09-12): the board stages its work and nothing else.

    The three product cards stage their own paths inside <WORKDIR>; the hand-off
    cards (i, p) stage NOTHING — they write their document under runs/ and attach
    it — and the review cards, the gates and the driver stage nothing at all. So no
    body may
    carry an unscoped form (`git add .`, `-A`, `-u`, `-f`) and none may stage a
    hand-off path. A body that says "staged" about a runs/ document sends a worker
    off-contract into the one thing the operator sees in `git status`."""
    staging = set()
    for name in sorted(os.listdir(BODIES)):
        if not name.endswith(".txt"):
            continue
        body = read(name)
        for m in re.finditer(r"git add\s+([^\s`]*)", body):
            assert m.group(1) == "--", f"{name}: unscoped staging {m.group(0)!r}"
            staging.add(name)
        assert not re.search(r"git add[^\n`]*(<REFINED>|<PLAN>|<IDEA>|<RUNS>)", body), name
    assert staging == {"c-body.txt", "ti-body.txt", "tw-body.txt"}, staging


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


def test_every_report_body_sends_its_report_to_the_result_field():
    """The `kanban_complete` tool's schema prefers `summary`, and every worker card
    on the 2026-09-11 run reported there — its result stayed empty while the body
    asked for `--result`. One fragment states the field for all of them, reviews
    included: a review whose verdict landed in the summary leaves the gate it guards
    holding forever, with nothing readable to act on (RVa1, 2026-09-13)."""
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt",
                 "rvp-body.txt", "rva-body.txt", "rvc-body.txt"):
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


def test_every_worker_and_verdict_body_carries_the_worker_contract():
    """The card contract used to sit in every profile's SOUL.md, paid by every session of
    the profile — desktop, cron, telegram — and kept in three copies. The SOUL now only says
    the card wins; the rules themselves travel with the cards, written once."""
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt",
                 "rvp-body.txt", "rva-body.txt", "rvc-body.txt"):
        assert "<WORKER_CONTRACT>" in read(body), body
    text = read("_worker-contract.txt")
    for rule in ("kanban.db", "tool_search", "request-review", "block", "memories", "skills",
                 "/opt/backup/agents/", "full sentences", "-p no:cacheprovider"):
        assert rule in text, rule


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FINISH = "a failing test is a finished card, not a blocker"


def judge_window(code, body):
    """What the goal judge reads: title + body, cut at 2000 chars from the start
    (`_goal_gate` → `goals._truncate(goal, 2000)`). A rule past the cut is invisible
    to it: every rendered DONE WHEN: line sits beyond 3700 chars."""
    text = card_render.render_body(body, repo=REPO, board="b", workdir="/w", lane=1,
                                  run_id="r1")
    return f"{lanes.card_title(code, 1)}\n\n{text}"[:2000]


def test_the_goal_judge_sees_that_a_failing_test_is_a_finish():
    """HUMAN RULE (2026-09-13): a failing test is always an acceptable finish for a
    worker card; only the reviewers reject. C2 on roman-evaluator-java reported a red
    test, the judge said `blocked`, and C2 blocked itself — so the rule has to be in
    the part of the body the judge actually reads."""
    for code, body in (("C", "c-body.txt"), ("TW", "tw-body.txt"), ("TI", "ti-body.txt")):
        window = judge_window(code, body)
        assert FINISH in window, body
        assert "complete" in window.split(FINISH, 1)[1], body


def test_done_when_never_requires_a_green_suite():
    """The integration card is the one exception: its finish is green (test above)."""
    for body in ("c-body.txt", "tw-body.txt"):
        done = read(body).split("DONE WHEN:", 1)[1].split("\n\n", 1)[0]
        assert "every failing test" in done, body
        assert "A green suite is not part of this finish" in done, body
    done = read("c-body.txt").split("DONE WHEN:", 1)[1].split("\n\n", 1)[0]
    assert "test-fix.diff" in done and "Neither is a blocker" in done


def test_the_coder_may_correct_a_tw_test_only_when_every_condition_holds():
    c = read("c-body.txt")
    assert "never edit them to make them pass" in c
    for condition in ("`done`", "unsatisfiable", "intent", "no test is deleted",
                      "coverage does not shrink", "test-fix.diff", "plan step",
                      "TEST DEFECT (not corrected)"):
        assert condition in c, condition
    assert "say so in your result and stop" not in c


def test_the_result_fragment_carries_the_test_lines_and_keeps_them_visible_to_the_judge():
    """`_goal_gate` judges `summary or result` (kanban_tools.py:585): a short summary
    hides the evidence the result carries."""
    text = read("_result-field.txt")
    assert "TEST FIX: <test> (plan step <n>)" in text
    assert "TEST DEFECT (not corrected): <test>" in text
    assert "`result` only" in text
    assert "repeat" in text and "summary" in text


def test_block_is_only_for_a_missing_external_decision_or_tool():
    text = read("_worker-contract.txt")
    assert "missing external decision or a missing tool" in text
    assert "never for a test, a plan step or another card's output" in text


def test_a_worker_never_blocks_with_kind_dependency():
    """`_route_block` sends `--kind dependency` to `todo` and `recompute_ready` puts it
    straight back: no recurrence count, no human. Goal mode allows only needs_input and
    dependency (kanban_tools._GOAL_MODE_BLOCK_ALLOWED_KINDS), so the contract names the
    one to use."""
    text = read("_worker-contract.txt")
    assert "never `block --kind dependency`" in text
    assert "`--kind needs_input`" in text


def test_the_implementation_review_judges_every_test_the_coder_changed():
    rva = read("rva-body.txt")
    assert "test-fix.diff" in rva
    assert "REJECT with `OWNER: C`" in rva
    assert "REJECT with `OWNER: TW`" in rva
    for body in ("rva-body.txt", "rvc-body.txt"):
        assert "may not edit the TW card's files" not in read(body), body


def test_the_integration_card_that_cannot_get_green_still_completes():
    """Wedge guard: green is required, but a TI card that cannot reach it after genuine
    effort completes naming each failing test — the final review rejects. The judge has
    to read that inside its window, or it pushes the card into a block."""
    window = judge_window("TI", "ti-body.txt")
    assert "cannot get the integration suite green" in window
    assert "never block" in window.split("cannot get the integration suite green", 1)[1]


def test_the_plan_review_checks_every_asserted_property_is_achievable():
    assert "achievable with the plan's named toolchain" in read("_plan-checklist.txt")


def test_the_plan_must_write_a_tick_sentence_and_derive_its_values():
    """The two rejection causes measured on is-even with `swift15-27b` (2026-09-26): a
    [TW] tick resting on a RED no card could observe (TW runs BESIDE C), and an expected
    value the plan's own toolchain does not produce (`is_even(0.5)` asserted True while
    Python 3.14 evaluates `0.5 % 2 == 0.5`). Both are checklist item 4, so the two forms
    a card CAN make are named there — and in the plan card's own contract, which is what
    the planner reads while writing the steps."""
    checklist = read("_plan-checklist.txt")
    assert "TICK SENTENCE:" in checklist
    assert "DERIVED VALUE:" in checklist
    assert "re-derivation of the predicted FAIL from the two patches" in checklist
    p = read("p-body.txt")
    assert "item 4's two forms" in p and "DERIVE every expected value" in p


def test_the_coders_test_fix_diff_holds_only_its_own_correction():
    """`git diff --cached` after staging diffs against HEAD: the TW card's whole file
    plus C's edit. Taken before staging, against the index still holding TW's version,
    the diff is the correction alone — what the review has to judge."""
    c = read("c-body.txt")
    assert "`git diff -- <the test paths> > <RUNS>/scratch/<YOUR-CARD-ID>/test-fix.diff`" in c
    assert "git diff --cached -- <the test paths>" not in c
    assert "BEFORE you stage it" in c
    assert "restore the TW card's version" in c
    revision = c.split("ON A REVISION CARD:", 1)[1]
    assert "restore the TW card's version" in revision


def test_finish_never_stops_implementation_at_a_red_test():
    """TW tests are red by design while C works; FINISH governs the end of the card,
    not each step."""
    assert "never keep going over red tests" not in read("c-body.txt")
    assert "Once every [C] step is implemented" in judge_window("C", "c-body.txt")
    assert "Once every [TW] step is written" in judge_window("TW", "tw-body.txt")
    assert "or cannot keep the unit suite green" in judge_window("TI", "ti-body.txt")


def test_the_final_review_routes_every_red_test_to_the_integration_card():
    rvc = read("rvc-body.txt")
    assert "The TW card is not routed from this review" in rvc
    assert "OWNER: TW" not in rvc and "C|TW|TI" not in rvc


def test_no_body_hardcodes_a_rework_cap():
    """`max-reworks` is per lane and read from the lane's idea header, which does not
    exist yet when the cards are filed — so a number in the prose is a second source
    of truth that disagrees with any board or lane that sets its own cap."""
    cap = re.compile(r"\bmax\s+\d+|\d+\s+(?:rework\s+)?rounds?\b", re.I)
    offenders = [name for name, text in all_texts() if cap.search(text)]
    assert offenders == [], offenders


def test_the_contract_hands_off_by_file_and_an_empty_diff_hands_off_nothing():
    """`is-even`, 2026-09-15. RVp1 attached a fabricated `<?php ` stub: `kanban_attach`
    takes `content_base64` INLINE, and a worker that has not read the file invents filler
    — it then base64'd the real bytes and attached them again as `review (1).md`; the four
    local-model I1 cards died in that same copy. TW1, on a lane the plan proved was already
    satisfied, wrote 1789 bytes of prose inside `patch.diff` because an empty diff looked
    like nothing to hand over; C1 handed over nothing for the same reason and the doc chain
    calls that valid (F5). So the shared rule names the scratch path, forbids attaching,
    and keeps the empty-diff case."""
    text = read("_worker-contract.txt")
    assert "<RUNS>/scratch/<YOUR-CARD-ID>/" in text
    assert "never paste a file's bytes into a tool" in text
    assert "EMPTY" in text and "an empty file is not attached" in text and "NO CHANGE:" in text
    assert "never put prose inside a `.diff` file" in text


def test_every_gate_body_tells_a_person_how_to_answer_from_the_card():
    """The drawer shows the body: a person who clicks the gate must learn the comment
    protocol and the gestures that stop the board, without opening the README."""
    for body in ("gi-body.txt", "gp-body.txt", "gc-body.txt"):
        text = read(body)
        assert run.GATE_READY_MARK in text, body
        assert "COMMENT" in text and "PASS" in text, body
        assert "DO NOT" in text and "block this card" in text, body
        assert "REWORK: <" in text and "The reason is required" in text, body
    for body in ("gp-body.txt", "gc-body.txt"):
        assert "new GATE READY" in read(body), body
    assert "OWNER: TW" in read("gc-body.txt")


def test_no_worker_body_asks_a_worker_to_attach_anything():
    """`hermes kanban attach` is refused inside a dispatcher-owned worker, and the
    `kanban_attach` tool takes the bytes inline — which made every local-model card copy
    its own file out of tool output by hand and lose it. The driver attaches instead."""
    for name, text in all_texts():
        low = text.lower()
        assert "kanban_attach" not in low or "never" in low, name
        assert "board <board> attach" not in low, name
    contract = read("_worker-contract.txt")
    assert "NEVER attach anything yourself" in contract
    assert "the DRIVER attaches" in contract


def test_every_hand_off_file_a_body_names_is_one_the_driver_attaches():
    import re
    import run
    named = set()
    for _name, text in all_texts():
        named |= set(re.findall(r"<RUNS>/scratch/<YOUR-CARD-ID>/([A-Za-z0-9._-]+)", text))
    assert named, "the bodies must name their hand-off files"
    assert named <= set(run.HANDOFF_NAMES), sorted(named - set(run.HANDOFF_NAMES))


def test_no_card_body_knows_whether_the_lane_forks_or_chains():
    """`sequential` moves an edge in the graph, not a word in a contract: a body that
    described the schedule would turn every scheduling change into a card-contract
    change, and the goal judge reads that text too."""
    for name, text in all_texts():
        assert "sequential" not in text.lower(), name
