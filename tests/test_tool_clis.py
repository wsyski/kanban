"""Every tool in the engine answers --help and refuses a bad argument.

Cheap, and it catches what a refactor breaks silently: a tool whose usage you cannot
ask for is one people guess at, and two of these had stopped answering (a hand-rolled
parser that treated --help as an unknown argument, and one that treated it as a file
path). Nothing here checks the TEXT, only that the contract holds.

The tools live in TWO directories — `template/` (what both drivers share) and `driver/`
(the kanban driver's own) — so the search walks both, and a tool that moves between
them is still collected.
"""
import glob
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS = tuple(os.path.join(REPO, layer) for layer in ("template", "driver"))
DRIVER = os.path.join(REPO, "driver")


def _is_cli(path):
    """A module with a __main__ block. lanes.py, file_lanes.py and runs_util.py are
    libraries: running them does nothing and exits 0, which would make the checks
    below pass for the wrong reason."""
    return '__name__ == "__main__"' in open(path).read()


def _tools():
    found = {}
    for layer in LAYERS:
        for path in glob.glob(os.path.join(layer, "*.py")):
            name = os.path.basename(path)
            if _is_cli(path) and name != "run.py":     # a daemon, not a CLI
                found[name] = path
    return found


TOOLS = sorted(_tools())


def run(tool, *args):
    return subprocess.run([sys.executable, _tools()[tool], *args],
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
        r = subprocess.run([os.path.join(DRIVER, script), "--help"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (script, r.stderr[:200])
        assert r.stdout.strip(), script
