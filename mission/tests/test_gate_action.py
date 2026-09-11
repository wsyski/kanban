import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run

GI = lanes.card_title("Gi", 1)
STATE = {GI: {"id": "t_gi", "status": "blocked"}}


def refined(findings_bullet="- F1: python3 present — `python3 --version` → 3.14"):
    parts = []
    for name in lanes.REFINED_SECTIONS:
        parts.append(f"## {name}\n{findings_bullet if name == 'Findings' else '- a line'}\n")
    return "\n".join(parts)


@pytest.fixture
def refined_file(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto_gates": False})
    monkeypatch.setattr(run, "log", lambda msg: None)
    run._ANNOUNCED.clear()
    d = tmp_path / "artifacts" / "lane-1"
    d.mkdir(parents=True)
    yield d / "refined.md"
    run._ANNOUNCED.clear()


def test_idea_gate_holds_until_every_template_section_exists(refined_file):
    refined_file.write_text(refined().replace("## Verification recipe", "## Checks"))
    assert run.gate_action(STATE, GI, "gi", 1) == \
        "waiting: refined idea missing section(s): Verification recipe"


def test_idea_gate_counts_only_findings_bullets(refined_file):
    refined_file.write_text(refined(findings_bullet="none"))
    assert "Findings section is empty" in run.gate_action(STATE, GI, "gi", 1)


def test_idea_gate_opens_on_a_complete_refinement(refined_file):
    refined_file.write_text(refined())
    assert run.gate_action(STATE, GI, "gi", 1) == "gate-held"


def test_md_section_stops_at_the_next_heading():
    text = "## Findings\nnone\n## Success criteria\n- SC1: x\n"
    assert run.md_section(text, "Findings") == "none\n"
    assert run.md_section(text, "Success criteria") == "- SC1: x\n"
    assert run.md_section(text, "Prior art") == ""
