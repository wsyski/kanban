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


def test_every_shipped_manifest_validates():
    """Every board, not the first offender: asserting inside the loop hides the
    rest of the job behind whichever board sorts earliest, and `validate` already
    collects each manifest's problems."""
    import board_schema
    bad = {}
    for b in boards():
        problems = board_schema.validate(
            json.load(open(os.path.join(BOARDS, b, "board.json"))), where=b)
        if problems:
            bad[b] = problems
    assert not bad, "\n".join(f"{b}: {p}" for b, ps in bad.items() for p in ps)


def test_a_board_can_be_built_without_unit_tests():
    """THE BOARD-LEVEL PARAMETER, on the board that uses it. `unit-tests` is a board
    option exactly like `integration-tests` (same table, same door — board_schema.OPTIONS
    marks both as per-lane), and blade-workspace sets it false in its manifest AND repeats
    it in its idea header. Either door leaves the lane without a tester cell and the
    review waiting on the coder alone — and the cards are still FILED, which is what lets
    a header turn the level back on for a single lane."""
    cfg = json.load(open(os.path.join(BOARDS, "blade-workspace", "board.json")))
    assert cfg["unit-tests"] is False
    for lane, path in ideas("blade-workspace"):
        parsed = lanes.read_idea(path)
        assert parsed is not None, path
        headers, _body = parsed
        opts = lanes.resolve_lane_options(cfg, headers, lane)
        assert opts["unit-tests"] is False, (path, opts)
        cards = lanes.lane_cards(lane, integration_tests=opts["integration-tests"],
                                 unit_tests=opts["unit-tests"])
        codes = [c["code"] for c in cards]
        assert "TW" not in codes, codes
        assert "C" in codes and "RVa" in codes, codes
        rva = [c for c in cards if c["code"] == "RVa"][0]
        assert rva["parents"] == [f"C{lane}"], rva
        # filed complete, pruned at lane open: that is what makes the header reversible
        assert [c["code"] for c in lanes.lane_cards(lane)] == [
            "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc"]


def test_the_two_lane_board_resolves_each_lane_its_own_options():
    """THE PER-LANE ARRAY FORM, on the only shipped board that uses it. `lanes: 2`
    with `"integration-tests": [false, true]` says lane 1 files and prunes the
    integration cards while lane 2 keeps them — the one option shape no other board
    exercises, and the one an off-by-one index would silently reverse. Both lanes
    are FILED complete either way; the list decides what each lane keeps on opening."""
    cfg = json.load(open(os.path.join(BOARDS, "roman-evaluator-java", "board.json")))
    assert cfg["lanes"] == 2, cfg
    assert isinstance(cfg["integration-tests"], list), cfg
    shipped = [lane for lane, _ in ideas("roman-evaluator-java")]
    assert shipped == [1, 2], shipped
    for lane, path in ideas("roman-evaluator-java"):
        parsed = lanes.read_idea(path)
        assert parsed is not None, path
        headers, _body = parsed
        opts = lanes.resolve_lane_options(cfg, headers, lane)
        assert opts["integration-tests"] is (lane == 2), (lane, opts)
        assert opts["unit-tests"] is True, (lane, opts)
        codes = [c["code"] for c in lanes.lane_cards(
            lane, integration_tests=opts["integration-tests"],
            unit_tests=opts["unit-tests"])]
        assert ("TI" in codes) is (lane == 2), (lane, codes)
        assert ("RVc" in codes) is (lane == 2), (lane, codes)
        assert codes[-1] == "Gc", codes
        assert [c["code"] for c in lanes.lane_cards(lane)] == [
            "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc"]


def test_every_shipped_idea_validates():
    import board_schema
    bad = {}
    for b in boards():
        for k, path in ideas(b):
            problems = board_schema.validate_idea(open(path).read(),
                                                  where=f"{b}/lane-{k}.md")
            if problems:
                bad[path] = problems
    assert not bad, "\n".join(f"{p}" for ps in bad.values() for p in ps)


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
