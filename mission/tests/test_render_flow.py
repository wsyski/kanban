import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_diagrams_are_generated_from_the_current_lane_table():
    r = subprocess.run([sys.executable, "mission/render-flow.py", "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_generic_diagram_names_no_build_tool():
    text = open(os.path.join(REPO, "mission", "flow.mmd")).read().lower()
    assert "failsafe" not in text
