"""Conversation-memory store factory.

LangGraph concept — the Store (long-term memory):
A checkpointer persists ONE thread's state (short-term, keyed by thread_id).
A Store is separate: a cross-thread key-value space that, when given an
`index`, also does semantic search — `store.search(namespace, query=...)`
embeds the query and returns the nearest stored values. That is exactly
"recall a similar past exchange," which a checkpointer cannot do.

Here the index embeds with Ollama `nomic-embed-text` (the same model the
Declarative agent used) and persists to kagent's pgvector Postgres. Like
`checkpointer.get_checkpointer()`, this degrades to None when unconfigured
or unreachable — memory is on in-cluster, off locally — and never raises.
"""

import logging

from langchain_ollama import OllamaEmbeddings
from langgraph.store.base import BaseStore

from homelab_agent.config import settings

logger = logging.getLogger(__name__)

# nomic-embed-text produces 768-dim vectors. If EMBEDDING_MODEL changes to a
# model with different dimensionality, update this constant to match.
EMBEDDING_DIMS = 768


def _index_config() -> dict:
    """Embedding index: embed the stored `question` field with Ollama."""
    embeddings = OllamaEmbeddings(model=settings.embedding_model, base_url=settings.ollama_base_url)
    return {"dims": EMBEDDING_DIMS, "embed": embeddings, "fields": ["question"]}


def get_store() -> BaseStore | None:
    """Return a pgvector-backed semantic store, or None when memory is off."""
    if not settings.memory_db_url:
        return None
    try:
        from langgraph.store.postgres import PostgresStore

        # from_conn_string returns a context manager; enter it manually and
        # keep the store for the process lifetime (the executor holds it).
        store_cm = PostgresStore.from_conn_string(settings.memory_db_url, index=_index_config())
        store = store_cm.__enter__()
        store.setup()  # idempotent: creates the store + vector tables if absent
        return store
    except Exception as exc:  # unreachable DB, bad DSN, missing pgvector, etc.
        logger.warning(
            "memory store unavailable (%s); running without conversation memory",
            exc,
        )
        return None
