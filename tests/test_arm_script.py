"""`arm.sh` — the shell go-signal, run for real against a stub `hermes`.

It had no test at all, and under `set -euo pipefail` its documented title fallback was
dead code (2026-09-23 review, Important 21).
"""
import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARM = os.path.join(REPO, "driver", "arm.sh")


def _arm(tmp_path, idea_text):
    """arm.sh copied into a scratch repo (it resolves REPO from its own path), one idea
    file, and a `hermes` that records every call and answers `list` with no cards."""
    repo = tmp_path / "repo"
    (repo / "driver").mkdir(parents=True)
    shutil.copy(ARM, repo / "driver" / "arm.sh")
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
    r = subprocess.run(["bash", str(repo / "driver" / "arm.sh"), "b", "1"],
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
