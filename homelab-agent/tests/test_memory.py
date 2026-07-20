"""memory.get_store(): configured store or None, and it never raises."""

from homelab_agent.memory import EMBEDDING_DIMS, get_store
from homelab_agent import memory


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


class _FakeStore:
    def setup(self):
        pass


class _FakeStoreSetupFails:
    def setup(self):
        raise RuntimeError("setup boom")


class _FakeCM:
    """Fake context manager mimicking PostgresStore.from_conn_string()."""

    def __init__(self, store):
        self._store = store
        self.exited = False
        self.exit_args = None

    def __enter__(self):
        return self._store

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        self.exit_args = (exc_type, exc, tb)
        return False


def test_retains_entered_store_cm_for_process_lifetime(monkeypatch):
    memory._OPEN_STORE_CMS.clear()
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://fake:fake@127.0.0.1:1/fakedb")
    from homelab_agent.config import Settings

    monkeypatch.setattr(memory, "settings", Settings.from_env())

    fake_store = _FakeStore()
    fake_cm = _FakeCM(fake_store)

    import langgraph.store.postgres as postgres_mod

    monkeypatch.setattr(
        postgres_mod.PostgresStore, "from_conn_string", lambda *a, **k: fake_cm
    )

    result = memory.get_store()

    assert result is fake_store
    assert fake_cm in memory._OPEN_STORE_CMS
    memory._OPEN_STORE_CMS.clear()


def test_closes_cm_when_setup_fails_after_enter(monkeypatch):
    memory._OPEN_STORE_CMS.clear()
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://fake:fake@127.0.0.1:1/fakedb")
    from homelab_agent.config import Settings

    monkeypatch.setattr(memory, "settings", Settings.from_env())

    fake_store = _FakeStoreSetupFails()
    fake_cm = _FakeCM(fake_store)

    import langgraph.store.postgres as postgres_mod

    monkeypatch.setattr(
        postgres_mod.PostgresStore, "from_conn_string", lambda *a, **k: fake_cm
    )

    result = memory.get_store()

    assert result is None
    assert fake_cm.exited is True
    assert fake_cm not in memory._OPEN_STORE_CMS
    memory._OPEN_STORE_CMS.clear()
