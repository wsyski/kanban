import sys

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "probe_rule: run with the driver's real probe-log check on plan reviews")
    config.addinivalue_line(
        "markers", "skill_rule: run with the real check of the profiles' worker-skill copies")


@pytest.fixture(autouse=True)
def _probed_reviews(monkeypatch, request):
    """A fixture's plan-review PASS is a verdict string with no probe log behind it; the
    driver reads such a PASS as an UNPROBED PASS (run.unprobed_review). Tests of
    everything else take the PASS as written; the rule itself is tested under the
    `probe_rule` marker, with the real check."""
    if request.node.get_closest_marker("probe_rule"):
        return
    run = sys.modules.get("run")
    if run is not None and hasattr(run, "unprobed_review"):
        monkeypatch.setattr(run, "unprobed_review", lambda card, lane, state=None: None)


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """A halt test must never post a real notice: send_notice reads these two."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)


@pytest.fixture(autouse=True)
def _private_work_directory(monkeypatch, tmp_path):
    """The driver publishes into `WORKDIR/docs/` from the gates and the chain record
    (publish_refined, publish_plan, publish_review). A test that drives those paths without
    naming its own WORKDIR wrote into the module default — `boards/work/docs/` in this
    checkout. Every test gets a private one; a test that sets WORKDIR itself still wins."""
    run = sys.modules.get("run")
    if run is not None and hasattr(run, "WORKDIR"):
        monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))


@pytest.fixture(autouse=True)
def _worker_skill_installed(monkeypatch, request):
    """create-board.sh and the driver refuse to file while a profile's copy of the worker
    skill is missing or differs from the repo's (lanes.worker_skill_problems), and a test
    host has no profiles of its own. Tests of everything else take the skill as installed;
    the rule itself is tested under the `skill_rule` marker, with the real check."""
    if request.node.get_closest_marker("skill_rule"):
        return
    lanes = sys.modules.get("lanes")
    if lanes is not None and hasattr(lanes, "worker_skill_problems"):
        monkeypatch.setattr(lanes, "worker_skill_problems",
                            lambda repo, cfg=None, hermes_root=None: [])
