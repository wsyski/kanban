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
import json
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


def test_a_missing_profile_is_named_as_missing(tmp_path):
    """Existence comes from the filesystem. `hermes profile list` is display output, so a
    CLI that fails prints nothing — and reading that as "profile not available" is how a
    board refused to file while all three profiles were present."""
    board = tmp_path / "boards" / "ghost"
    board.mkdir(parents=True)
    (board / "board.json").write_text(
        json.dumps({"slug": "ghost", "assignees": {"coder": "no-such-profile"}}))
    env = _stub_env(tmp_path, silent=True)
    r = subprocess.run(["bash", os.path.join(DRIVER, "create-board.sh"), "--board", str(board)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode != 0
    assert "no-such-profile" in r.stderr and "not available" in r.stderr


def test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal(tmp_path):
    """The other direction: the directory is there, the CLI is silent about it. That is a
    note, not a refusal — the profile the board asks for does exist."""
    home = tmp_path / "fakehome"
    for name in ("researcher", "tester"):   # the graph's own default role, plus the remap
        (home / ".hermes" / "profiles" / name).mkdir(parents=True)
    board = tmp_path / "boards" / "b"
    board.mkdir(parents=True)
    (board / "board.json").write_text(
        json.dumps({"slug": "b", "assignees": {"coder": "tester"}}))
    env = _stub_env(tmp_path, home=home, silent=True)
    r = subprocess.run(["bash", os.path.join(DRIVER, "create-board.sh"), "--board", str(board)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert "did not name tester" in r.stderr
    assert "profile tester not available" not in r.stderr


def _stub_env(tmp_path, *, home=None, silent=True):
    """A PATH whose `hermes` answers everything and says nothing — the shape of a CLI that
    failed without an error code worth trusting."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "hermes"
    stub.write_text("#!/bin/sh\nexit 0\n" if silent else "#!/bin/sh\necho ' coder '\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    if home is not None:
        env["HOME"] = str(home)
    return env


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
