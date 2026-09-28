"""`arm.sh` — the shell go-signal, run for real against a stub `hermes`.

It had no test at all, and under `set -euo pipefail` its documented title fallback was
dead code (2026-09-23 review, Important 21).
"""
import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARM = os.path.join(REPO, "driver", "arm.sh")


def _arm(tmp_path, idea_text, *args):
    """arm.sh copied into a scratch repo (it resolves REPO from its own path), one idea
    file, and a `hermes` that records every call and answers `list` with no cards.
    Default argv is the documented arm; pass args to drive the interface itself."""
    repo = tmp_path / "repo"
    (repo / "driver").mkdir(parents=True)
    shutil.copy(ARM, repo / "driver" / "arm.sh")
    # arm.sh starts the board's driver when none is up, so the scratch repo needs the helper
    # it asks (driver-pid.sh) and a `start-board.sh` that records being called.
    shutil.copy(os.path.join(REPO, "driver", "driver-pid.sh"),
                repo / "driver" / "driver-pid.sh")
    started = tmp_path / "start-board.log"
    (repo / "driver" / "start-board.sh").write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {started}\n")
    (repo / "driver" / "start-board.sh").chmod(0o755)
    (repo / "boards" / "b").mkdir(parents=True)
    (repo / "boards" / "b" / "lane-1.md").write_text(idea_text)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "hermes.log"
    stub = bin_dir / "hermes"
    stub.write_text("#!/usr/bin/env bash\n"
                    f"printf '%s\\n' \"$*\" >> {log}\n"
                    "case \" $* \" in *' list '*) echo '[]' ;; esac\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    argv = args or ("--slug", "b", "--lane", "1")
    r = subprocess.run(["bash", str(repo / "driver" / "arm.sh"), *argv],
                       capture_output=True, text=True, env=env, timeout=30)
    return r, (log.read_text() if log.exists() else "")


def test_a_headingless_idea_is_armed_under_the_fallback_title(tmp_path):
    """`grep` exits 1 on an idea with no '## ' heading; pipefail propagated it and
    set -e aborted BEFORE the `Idea $LANE` fallback on the next line — reproduced
    2026-09-23: exit 1. A headingless idea is an expected input: validate_idea needs
    only a body and '### Done means', and file_lanes.idea_title has the same fallback."""
    r, calls = _arm(tmp_path, "no heading here\n\n### Done means\n\nx\n")
    assert r.returncode == 0, r.stderr
    assert "arming b lane 1 — 'Idea 1'" in r.stdout, r.stdout
    assert "create Idea 1 --body" in calls, calls


def test_a_headed_idea_is_armed_under_its_own_title(tmp_path):
    r, calls = _arm(tmp_path, "## Idea 1: the CLI\n\n### Done means\n\nx\n")
    assert r.returncode == 0, r.stderr
    assert "create Idea 1: the CLI --body" in calls, calls


def test_the_script_does_not_claim_a_guard_that_does_not_exist():
    """It said arming a lane twice "is caught downstream: the driver refuses a lane it
    has two ideas for". Nothing does: adopt_and_refile writes one lane-<k>.md per armed
    card, last wins (review comments PRIOR-I3)."""
    src = open(ARM).read()
    assert "caught downstream" not in src
    assert "last" in src and "Arm a lane once" in src


def test_the_armed_card_is_filed_blocked_and_the_prose_says_so(tmp_path):
    """The header said arm cards sit in `todo` and repeated it at the usage line; the
    create call has filed `--initial-status blocked` since 2026-09-15 (a `todo` card
    with no assignee is claimed and worked by the dispatcher — the first arm had a
    coder worker build the board's whole deliverable off this card), and the driver's
    `armed_ideas` reads the blocked card back (final review D)."""
    r, calls = _arm(tmp_path, "## Idea 1: the CLI\n\n### Done means\n\nx\n")
    assert r.returncode == 0, r.stderr
    assert "--initial-status blocked" in calls, calls
    src = open(ARM).read()
    # the dashboard's drag moves a card to `todo`; this script does not drag, it
    # CREATES the card blocked, so the prose must not promise the other state
    assert "card in\n# `todo`" not in src, "the prose must say where the card lands"
    assert "sits in todo" not in src


def test_the_board_is_named_with_a_flag_not_positionally(tmp_path):
    """The old shape was `arm.sh <slug> [lane]` — the only positional board among the four
    scripts (start-board takes `--slug`; create-board and reset take `--board <dir>`), and
    the one line the docs printed next to `start-board.sh --slug <s>`. The refusal names
    the flag, so old muscle memory gets corrected instead of a card filed for the wrong
    thing."""
    r, calls = _arm(tmp_path, "## Idea 1: x\n\n### Done means\n\ny\n", "b", "1")
    assert r.returncode == 2, r.stdout
    assert "unknown arg: b" in r.stderr and "--slug" in r.stderr, r.stderr
    assert calls == "", calls


def test_a_lane_that_is_not_a_number_is_refused(tmp_path):
    """`--lane` is interpolated into the idea path, so it is digits only."""
    r, calls = _arm(tmp_path, "## Idea 1: x\n\n### Done means\n\ny\n",
                    "--slug", "b", "--lane", "1x")
    assert r.returncode == 2, r.stdout
    assert "lane number" in r.stderr, r.stderr
    assert calls == "", calls


def test_a_flag_with_no_value_is_a_usage_error(tmp_path):
    r, calls = _arm(tmp_path, "## Idea 1: x\n\n### Done means\n\ny\n", "--slug")
    assert r.returncode == 2, r.stdout
    assert "needs a value" in r.stderr, r.stderr
    assert calls == "", calls


def test_arming_starts_the_board_when_no_driver_is_up(tmp_path):
    """A finished board has NO driver (it exits with the run it drove), so the shell go
    signal starts one — otherwise the card just sits blocked and nobody reads it. It is the
    same door as start-board.sh: same lock, same refusal, a no-op when a driver is up."""
    r, calls = _arm(tmp_path, "## Idea 1: x\n\n### Done means\n\ny\n")
    assert r.returncode == 0, r.stderr
    started = tmp_path / "start-board.log"
    assert started.exists(), r.stdout
    assert started.read_text().strip() == "--slug b", started.read_text()
