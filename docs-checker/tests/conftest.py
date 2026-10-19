import pytest


@pytest.fixture(autouse=True)
def no_real_anthropic(monkeypatch):
    """No test may reach the Anthropic API or use a real key, even by accident."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "kagent-credential-injected")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")
