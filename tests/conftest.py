import pytest


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """A halt test must never post a real notice: send_notice reads these two."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
