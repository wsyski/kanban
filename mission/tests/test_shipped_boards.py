import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARDS = os.path.join(REPO, "boards")


def boards():
    return sorted(d for d in os.listdir(BOARDS)
                  if os.path.isfile(os.path.join(BOARDS, d, "board.json")))


def ideas(board):
    for name in sorted(os.listdir(os.path.join(BOARDS, board))):
        m = re.fullmatch(r"lane-(\d+)\.md", name)
        if m:
            yield int(m.group(1)), os.path.join(BOARDS, board, name)


def test_every_shipped_manifest_uses_known_keys():
    for b in boards():
        cfg = json.load(open(os.path.join(BOARDS, b, "board.json")))
        assert not set(cfg) - file_lanes.BOARD_KEYS, b
        assert isinstance(cfg.get("lanes", 1), int), b


def test_every_shipped_idea_parses_and_fits_its_board():
    for b in boards():
        lanes_n = json.load(open(os.path.join(BOARDS, b, "board.json"))).get("lanes", 1)
        for k, path in ideas(b):
            assert k <= lanes_n, path
            assert lanes.read_idea(path) is not None, path


def test_ideas_name_no_board_path():
    """An idea is portable between boards: its paths are relative to the work directory."""
    for b in boards():
        for _k, path in ideas(b):
            assert "boards/" not in open(path).read(), path


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout


def test_the_suite_writes_nothing_into_the_repo():
    """A test that leaves RUN_DIR unpatched writes into boards/runs — BOARD is
    "" at import, so the module-level path resolves above the board directories.
    That dir is neither tracked nor gitignored; it just sits in the operator's
    working tree. Found there 2026-09-11 (halt.txt, chain.jsonl)."""
    assert not os.path.exists(os.path.join(REPO, "boards", "runs")), \
        "a test wrote into boards/runs — patch run.RUN_DIR in its fixture"


def test_no_board_commits_its_run_state():
    """`boards/<slug>/work/` is the board's PRODUCT and belongs in history: its
    cards stage it, the human commits it at the gate. What must never sit in
    HEAD is run state (`boards/<slug>/runs/`, and the hand-offs inside it),
    an installed dependency tree and tool caches. A path in HEAD that is
    deleted in the worktree is the pending removal, and that is fine.

    Match in Python, not with a git pathspec: `ls-files` globs `boards/*/runs/*`
    across slashes and `ls-tree` does NOT (it needs `:(glob)`), so a pathspec
    version asserted over an empty set passed vacuously (2026-09-11).
    """
    assert fnmatch("boards/x/runs/y.md", "boards/*/runs/*")   # the pattern itself
    tracked = git("ls-tree", "-r", "--name-only", "HEAD").split()
    forbidden = {p for p in tracked
                 if fnmatch(p, "boards/*/runs/*")
                 or "node_modules/" in p
                 or "/__pycache__/" in p
                 or p.endswith(".pyc")
                 or "/.pytest_cache/" in p}
    removed = set(git("diff", "--name-only", "--diff-filter=D", "HEAD").split())
    assert forbidden <= removed, forbidden - removed


def test_a_boards_product_is_not_gitignored():
    """The deliverable must be committable: `boards/<slug>/work/` is where the
    lane's artifact lives and the gate commit is what puts it in history.
    `git check-ignore --no-index` reads the ignore rules regardless of what is on
    disk, so a re-added `boards/*/work/` line fails here (2026-09-12)."""
    for b in boards():
        probe = f"boards/{b}/work/probe.py"
        rc = subprocess.run(["git", "check-ignore", "--no-index", "-q", probe],
                            cwd=REPO).returncode
        assert rc != 0, f"{probe} is gitignored — its deliverable could never be committed"
