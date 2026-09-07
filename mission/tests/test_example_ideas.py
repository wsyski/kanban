import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

DOCS = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "example-ideas")


def test_example_docs_exist():
    assert sorted(os.path.basename(p) for p in glob.glob(os.path.join(DOCS, "*.md"))) == [
        "portfolio.md", "smoke-test.md"]


def test_every_example_splits_and_parses():
    for path in glob.glob(os.path.join(DOCS, "*.md")):
        sections = lanes.split_ideas(open(path).read())
        assert sections, f"{path}: no '## ' sections"
        for s in sections:
            headers, body = lanes.parse_idea(s)   # raises on an unknown key
            assert body.strip(), f"{path}: empty idea body"


def test_smoke_test_example_reproduces_the_original_two_lanes():
    sections = lanes.split_ideas(open(os.path.join(DOCS, "smoke-test.md")).read())
    assert len(sections) == 2
    first, _ = lanes.parse_idea(sections[0])
    assert first["integration-tests"] == "false"


def test_portfolio_example_has_no_integration_tests_header():
    sections = lanes.split_ideas(open(os.path.join(DOCS, "portfolio.md")).read())
    assert len(sections) == 1
    headers, _ = lanes.parse_idea(sections[0])
    assert "integration-tests" not in headers
