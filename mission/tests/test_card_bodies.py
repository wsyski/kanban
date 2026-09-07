import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

BODIES = os.path.join(os.path.dirname(__file__), "..", "card-bodies")
BANNED = re.compile(r"wordcount|mvn |spring|maven|task 1|task 2", re.I)
ALLOWED_PLACEHOLDERS = {"<WORKDIR>", "<BOARD>", "<N>", "<IDEA>"}


def test_every_lane_card_has_a_body_file():
    for code, body, *_ in lanes.LANE_CARDS:
        assert os.path.exists(os.path.join(BODIES, body)), f"{code}: {body} missing"


def test_bodies_carry_no_scenario_specific_language():
    for _, body, *_ in lanes.LANE_CARDS:
        text = open(os.path.join(BODIES, body)).read()
        assert not BANNED.search(text), f"{body} mentions a specific scenario"


def test_bodies_use_only_known_placeholders():
    for _, body, *_ in lanes.LANE_CARDS:
        text = open(os.path.join(BODIES, body)).read()
        for ph in set(re.findall(r"<[A-Z_]+>", text)):
            assert ph in ALLOWED_PLACEHOLDERS, f"{body}: unknown placeholder {ph}"


def test_gate_bodies_never_instruct_a_commit_as_a_requirement():
    for body in ("gp-body.txt", "gc-body.txt"):
        text = open(os.path.join(BODIES, body)).read().lower()
        assert "the driver never commits" in text
        assert "commit sha in the result" not in text


def test_worker_bodies_point_at_the_snapshot_not_the_source():
    for body in ("p-body.txt", "rvp-body.txt", "rva-body.txt"):
        text = open(os.path.join(BODIES, body)).read()
        assert "<IDEA>" in text, f"{body} must reference the idea snapshot"
        assert "mission/ideas/" not in text, f"{body} points at the mutable source"


def test_worker_bodies_forbid_committing():
    for body in ("p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        text = open(os.path.join(BODIES, body)).read().lower()
        assert "do not commit" in text
