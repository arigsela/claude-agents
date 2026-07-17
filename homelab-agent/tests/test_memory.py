"""memory.get_store(): configured store or None, and it never raises."""

from homelab_agent.memory import EMBEDDING_DIMS, get_store


def test_returns_none_without_db_url(monkeypatch):
    monkeypatch.delenv("MEMORY_DB_URL", raising=False)
    # settings is module-level; rebuild from patched env
    from homelab_agent.config import Settings
    from homelab_agent import memory

    monkeypatch.setattr(memory, "settings", Settings.from_env())
    assert get_store() is None


def test_never_raises_on_broken_config(monkeypatch):
    # A DB URL that cannot possibly connect must degrade to None, not raise.
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://nope:nope@127.0.0.1:1/nodb")
    from homelab_agent.config import Settings
    from homelab_agent import memory

    monkeypatch.setattr(memory, "settings", Settings.from_env())
    # Must return None (connection/setup fails) without propagating an exception.
    assert get_store() is None


def test_embedding_dims_matches_nomic():
    assert EMBEDDING_DIMS == 768
