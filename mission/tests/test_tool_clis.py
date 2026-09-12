"""Every tool under mission/ answers --help and refuses a bad argument.

Cheap, and it catches what a refactor breaks silently: a tool whose usage you cannot
ask for is one people guess at, and two of these had stopped answering (a hand-rolled
parser that treated --help as an unknown argument, and one that treated it as a file
path). Nothing here checks the TEXT, only that the contract holds.
"""
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MISSION = os.path.join(REPO, "mission")
def _is_cli(path):
    """A module with a __main__ block. lanes.py, file_lanes.py and runs_util.py are
    libraries: running them does nothing and exits 0, which would make the checks
    below pass for the wrong reason."""
    return '__name__ == "__main__"' in open(path).read()


TOOLS = sorted(os.path.basename(p) for p in glob.glob(os.path.join(MISSION, "*.py"))
               if _is_cli(p) and os.path.basename(p) != "run.py")   # a daemon, not a CLI


def run(tool, *args):
    return subprocess.run([sys.executable, os.path.join(MISSION, tool), *args],
                          capture_output=True, text=True)


def test_every_tool_is_collected():
    """If this list empties, the tests below pass vacuously."""
    assert len(TOOLS) >= 5, TOOLS


def test_every_tool_answers_help():
    broken = []
    for tool in TOOLS:
        r = run(tool, "--help")
        if r.returncode != 0 or not (r.stdout.strip() or r.stderr.strip()):
            broken.append((tool, r.returncode, r.stderr.strip()[:80]))
    assert not broken, broken


def test_every_tool_refuses_an_unknown_argument():
    """Exit non-zero rather than doing something with a typo'd flag."""
    loud = []
    for tool in TOOLS:
        r = run(tool, "--definitely-not-a-flag")
        if r.returncode == 0:
            loud.append(tool)
    assert not loud, loud


def test_the_shell_entry_points_answer_help():
    for script in ("create-board.sh", "start-board.sh", "reset.sh"):
        r = subprocess.run([os.path.join(MISSION, script), "--help"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (script, r.stderr[:200])
        assert r.stdout.strip(), script
