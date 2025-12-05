"""Vector store factory for backend selection.

Provides a unified way to get the configured vector store backend
based on environment variables.
"""

import logging
from typing import Optional

from src.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)

# Singleton instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get or create the configured vector store instance.

    Backend selection based on environment variables:
        - RAG_VECTOR_BACKEND: 'qdrant' or 'pgvector' (default: 'qdrant')

    For Qdrant backend:
        - RAG_QDRANT_URL: Qdrant server URL
        - RAG_QDRANT_API_KEY: Optional API key

    For pgvector backend:
        - RAG_DATABASE_URL: PostgreSQL connection string

    Returns:
        Configured VectorStore instance
    """
    global _vector_store

    if _vector_store is not None:
        return _vector_store

    # Import settings
    from src.config import get_settings

    settings = get_settings()

    # Get backend type from config
    backend = getattr(settings, "vector_backend", "qdrant").lower()

    if backend == "pgvector":
        _vector_store = _create_pgvector_store(settings)
    else:
        _vector_store = _create_qdrant_store(settings)

    logger.info(f"Using vector store backend: {_vector_store.backend_name}")
    return _vector_store


def _create_qdrant_store(settings) -> VectorStore:
    """Create Qdrant vector store from settings."""
    from src.vectorstore.qdrant_store import QdrantStore

    return QdrantStore(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.qdrant_timeout,
        vector_size=settings.vector_size,
        distance_metric=settings.distance_metric,
    )


def _create_pgvector_store(settings) -> VectorStore:
    """Create PostgreSQL + pgvector store from settings."""
    from src.vectorstore.pgvector_store import PgVectorStore

    database_url = getattr(settings, "database_url", None)
    if not database_url:
        raise ValueError(
            "RAG_DATABASE_URL is required for pgvector backend. "
            "Set to PostgreSQL connection string."
        )

    return PgVectorStore(
        database_url=database_url,
        vector_size=settings.vector_size,
    )


async def initialize_vector_store() -> VectorStore:
    """Initialize the vector store (create tables/collections if needed).

    Should be called at application startup.

    Returns:
        Initialized VectorStore instance
    """
    store = get_vector_store()
    await store.initialize()
    return store


async def close_vector_store() -> None:
    """Close the vector store connection.

    Should be called at application shutdown.
    """
    global _vector_store

    if _vector_store is not None:
        await _vector_store.close()
        _vector_store = None


def reset_vector_store() -> None:
    """Reset the vector store singleton (for testing)."""
    global _vector_store
    _vector_store = None
