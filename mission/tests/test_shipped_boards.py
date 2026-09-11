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


def test_no_board_tracks_generated_output():
    """Generated paths may be STAGED — that is how a card hands off
    (`git add -f`) — but never COMMITTED. A path in HEAD that is deleted in the
    worktree is the pending removal, and that is fine.

    Match in Python, not with a git pathspec: `ls-files` globs `boards/*/work/*`
    across slashes and `ls-tree` does NOT (it needs `:(glob)`), so a pathspec
    version asserted over an empty set and passed vacuously.
    """
    assert fnmatch("boards/x/work/y.py", "boards/*/work/*")   # the pattern itself
    tracked = git("ls-tree", "-r", "--name-only", "HEAD").split()
    in_head = {p for p in tracked
               if fnmatch(p, "boards/*/work/*") or fnmatch(p, "boards/*/runs/*")}
    removed = set(git("diff", "--name-only", "--diff-filter=D", "HEAD").split())
    assert in_head <= removed, in_head - removed
