"""Vector Store Abstraction Layer.

Provides a unified interface for vector database backends:
- Qdrant: For local development and standalone deployments
- PostgreSQL + pgvector: For Kubernetes with existing RDS

Usage:
    from src.vectorstore import get_vector_store

    store = get_vector_store()  # Returns configured backend
    await store.store(content, embedding, metadata)
    results = await store.search(query_embedding, limit=5)
"""

from src.vectorstore.base import VectorStore, SearchResult, StoredDocument
from src.vectorstore.factory import get_vector_store

__all__ = [
    "VectorStore",
    "SearchResult",
    "StoredDocument",
    "get_vector_store",
]
