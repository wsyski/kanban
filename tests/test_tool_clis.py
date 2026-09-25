"""Every tool in the engine answers --help and refuses a bad argument.

Cheap, and it catches what a refactor breaks silently: a tool whose usage you cannot
ask for is one people guess at, and two of these had stopped answering (a hand-rolled
parser that treated --help as an unknown argument, and one that treated it as a file
path). Nothing here checks the TEXT, only that the contract holds.

The tools live in TWO directories — `template/` (what the driver imports) and `driver/`
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


def test_review_package_help_is_the_header_not_a_line_range():
    """`sed -n '2,8p' "$0"` printed whatever sat on lines 2-8 of the script — a fragment
    the moment a line was added above them (review errors S11)."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(["bash", os.path.join(repo, "driver", "review-package.sh"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.startswith("Print one task's review package"), r.stdout
    assert "driver/review-package.sh <base>" in r.stdout


def test_reset_accepts_an_uppercase_yes(tmp_path):
    """The prompt says [y/N] and only a lowercase `y` proceeded (review errors S10)."""
    import json
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    (board / "board.json").write_text(json.dumps({"slug": "no-such-board-yes"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hermes").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "hermes").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               GIT_DIR=str(tmp_path / "no-git"))
    r = subprocess.run(["bash", os.path.join(repo, "driver", "reset.sh"), "--board", str(board)],
                       input="Y\n", capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no driver running" in r.stdout


def _reset_board(tmp_path, hermes_body, git_body=None):
    """Run reset.sh on a throwaway board with a stub `hermes` (and `git`) on PATH."""
    import json
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    (board / "board.json").write_text(json.dumps({"slug": "a-live-board"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("hermes", hermes_body), ("git", git_body)):
        if body is None:
            continue
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               GIT_DIR=str(tmp_path / "no-git"))
    return subprocess.run(["bash", os.path.join(repo, "driver", "reset.sh"),
                           "--board", str(board), "--batch"],
                          capture_output=True, text=True, env=env, timeout=60)


def test_reset_says_so_when_it_cannot_read_the_registry(tmp_path):
    """`hermes kanban boards list 2>/dev/null | awk … | grep -qx` made a FAILING CLI
    indistinguishable from "no such board": the door printed "board 'x' is not in the
    registry — nothing to archive" and exited 0 while every live card stayed unarchived
    (probed 2026-09-24 with a failing hermes stub). create-board.sh:463 already reads ONE
    answer and fails on it; the door mirrors that shape now."""
    r = _reset_board(tmp_path,
                     "#!/bin/sh\necho 'kanban: registry unavailable' >&2\nexit 3\n")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "cannot read the board registry" in r.stderr, r.stderr
    assert "registry unavailable" in r.stderr, r.stderr
    assert "is not in the registry" not in r.stdout, r.stdout


def test_reset_matches_the_slug_against_stdout_not_a_warning_on_stderr(tmp_path):
    """The registry read captures the CLI's output for the `grep -qx "$SLUG"` match, and
    `2>&1` merged the streams: a CLI that exits 0 while naming the slug on STDERR (a
    warning, a progress line) matched, so reset.sh took the ARCHIVE branch for a board
    the CLI never listed — and went on to `list --json` and `archive` against it
    (2026-09-25 fix-pass verification). The match is the CLI's STDOUT; its stderr is
    diagnostics and stays on this script's stderr."""
    r = _reset_board(tmp_path,
                     "#!/bin/sh\n"
                     'case "$*" in\n'
                     "  *'boards list'*)"
                     " echo 'warning: a-live-board is not in this CLI index' >&2; exit 0 ;;\n"
                     "esac\n"
                     'echo "USED $*"\n')
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is not in the registry" in r.stdout, r.stdout
    assert "cleared" not in r.stdout, r.stdout
    assert "USED" not in r.stdout, r.stdout        # nothing archived, nothing listed again
    assert "a-live-board is not in this CLI index" in r.stderr, r.stderr


def test_reset_still_archives_a_board_the_registry_lists_on_stdout(tmp_path):
    """The other half of the stdout-only match: a slug the CLI DOES list on stdout must
    still take the archive branch — this is the path that was working, and narrowing the
    capture to stdout must not turn it into "not in the registry" (2026-09-25 fix-pass
    verification of item 3)."""
    r = _reset_board(tmp_path,
                     "#!/bin/sh\n"
                     'case "$*" in\n'
                     "  *'boards list'*) echo 'a-live-board  the live board'; exit 0 ;;\n"
                     "  *'list --json'*) echo '[{\"id\": \"t_1\"}]'; exit 0 ;;\n"
                     "  *archive*) echo \"ARCHIVED:$*\" ; exit 0 ;;\n"
                     "esac\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "board 'a-live-board' cleared" in r.stdout, r.stdout
    assert "ARCHIVED:kanban --board a-live-board archive t_1" in r.stdout, r.stdout


def test_a_git_warning_on_a_successful_read_is_not_a_pathspec(tmp_path):
    """The staged read was `git diff --cached … 2>&1`, so a WARNING git writes to stderr
    on a read that SUCCEEDED became part of `$staged`: the count said N+1 and the warning
    text was handed to `git restore --staged` as a pathspec (2026-09-25 fix-pass
    verification). Stdout is the path list; stderr is not a path."""
    git = ("#!/bin/sh\n"
           'case "$*" in\n'
           "  *rev-parse*) exit 0 ;;\n"
           "  *diff*) printf 'warning: LF will be replaced by CRLF\\n' >&2\n"
           "          printf 'boards/b/work/one.txt\\nboards/b/work/two.txt\\n'; exit 0 ;;\n"
           "  *restore*) echo \"RESTORE:$*\" ; exit 0 ;;\n"
           "esac\n")
    r = _reset_board(tmp_path, "#!/bin/sh\nexit 0\n", git_body=git)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "unstaged 2 generated path(s)" in r.stdout, r.stdout
    restore = [l for l in r.stdout.splitlines() if l.startswith("RESTORE:")]
    assert len(restore) == 1, r.stdout
    assert restore[0].endswith("restore --staged -- boards/b/work/one.txt boards/b/work/two.txt"), \
        restore[0]
    assert "LF will be replaced" not in r.stdout, r.stdout
    # not dropped in silence either: what the read said on stderr is still on stderr
    assert "LF will be replaced" in r.stderr, r.stderr


def test_reset_says_so_when_it_cannot_read_the_index(tmp_path):
    """`git diff --cached … 2>/dev/null || true` made a failing index read the same as a
    clean index, so the unstage silently did nothing and the reset still exited 0: a
    failure must say so (2026-09-24 review). The read's status is checked, like the
    restore's."""
    git = ("#!/bin/sh\n"
           'case "$*" in\n'
           "  *rev-parse*) exit 0 ;;\n"
           "  *diff*) echo 'fatal: index file smaller than expected' >&2; exit 128 ;;\n"
           "esac\n")
    r = _reset_board(tmp_path, "#!/bin/sh\nexit 0\n", git_body=git)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "cannot read the git index" in r.stderr, r.stderr
    assert "smaller than expected" in r.stderr, r.stderr
    assert "cleared" not in r.stdout, r.stdout

