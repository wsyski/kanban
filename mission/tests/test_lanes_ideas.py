import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

IDEA = """## Idea 1: a small thing
<!-- integration-tests: false -->
<!-- auto-gates: true -->

Build a fat-jar CLI reading stdin and printing a word count.
"""


def test_parse_idea_extracts_headers_and_body():
    headers, body = lanes.parse_idea(IDEA)
    assert headers == {"integration-tests": "false", "auto-gates": "true"}
    assert "fat-jar CLI" in body
    assert "integration-tests" not in body


def test_parse_idea_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown idea header"):
        lanes.parse_idea("## X\n<!-- integraton-tests: false -->\n\ntext\n")


def test_parse_idea_ignores_ordinary_html_comments():
    headers, body = lanes.parse_idea("## X\n<!-- just a note -->\n\ntext\n")
    assert headers == {}


def test_read_idea_reads_one_lane_file(tmp_path):
    """One file per lane: position is the filename, never a heading's order in
    some larger document."""
    (tmp_path / "lane-2.md").write_text(
        "## Two\n<!-- integration-tests: true -->\nbody\n")
    headers, body = lanes.read_idea(str(tmp_path / "lane-2.md"))
    assert headers == {"integration-tests": "true"}
    assert body.strip() == "## Two\nbody"


def test_read_idea_treats_missing_and_empty_alike(tmp_path):
    """A lane with no idea and a lane with an empty placeholder are the same
    thing to the board: nothing to file, and the chain stops there."""
    assert lanes.read_idea(str(tmp_path / "lane-1.md")) is None
    (tmp_path / "lane-1.md").write_text("   \n")
    assert lanes.read_idea(str(tmp_path / "lane-1.md")) is None


def test_resolve_prefers_header_over_board_default():
    defaults = {"integration_tests": True, "auto_gates": False}
    opts = lanes.resolve_lane_options(
        defaults, {"integration-tests": "false", "auto-gates": "true"})
    assert opts == {"integration_tests": False, "auto_gates": True}


def test_resolve_falls_back_to_board_default():
    defaults = {"integration_tests": False, "auto_gates": True}
    opts = lanes.resolve_lane_options(defaults, {})
    assert opts["integration_tests"] is False
    assert opts["auto_gates"] is True


def test_bool_values_are_exactly_true_or_false():
    with pytest.raises(ValueError, match="expected true or false"):
        lanes.resolve_lane_options({}, {"integration-tests": "no"})
    with pytest.raises(ValueError, match="expected true or false"):
        lanes.resolve_lane_options({}, {"auto-gates": "1"})


def test_resolve_rejects_a_suite_header():
    with pytest.raises(ValueError, match="unknown idea header"):
        lanes.parse_idea("## X\n<!-- suite: mvn -q verify -->\n\ntext\n")


def test_read_idea_returns_none_for_missing_or_blank(tmp_path):
    assert lanes.read_idea(str(tmp_path / "nope.md")) is None
    blank = tmp_path / "lane-1.md"
    blank.write_text("\n   \n")
    assert lanes.read_idea(str(blank)) is None


def test_read_idea_returns_parsed_content(tmp_path):
    f = tmp_path / "lane-1.md"
    f.write_text(IDEA)
    headers, body = lanes.read_idea(str(f))
    assert headers["auto-gates"] == "true"
    assert "fat-jar" in body
