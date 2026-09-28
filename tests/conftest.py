import sys

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "probe_rule: run with the driver's real probe-log check on plan reviews")


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
