"""RAG Search Tool - Semantic search across document collections.

Provides the rag_search MCP tool for retrieving relevant documents
from the vector database using semantic similarity.

Supports multiple backends:
    - Qdrant (local development)
    - PostgreSQL + pgvector (Kubernetes/RDS)
"""

import logging
from typing import Any, Dict, List, Optional

from src.config import get_settings
from src.embeddings import get_embedding_service
from src.vectorstore import get_vector_store

logger = logging.getLogger(__name__)


async def rag_search(
    query: str,
    collection: Optional[str] = None,
    limit: int = 5,
    score_threshold: Optional[float] = None,
    filter_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for relevant documents using semantic similarity.

    Performs vector similarity search to find documents
    that are semantically related to the query.

    Args:
        query: Natural language search query
        collection: Collection name to search in (default: from config)
        limit: Maximum number of results to return (default: 5)
        score_threshold: Minimum similarity score (0.0-1.0, default: from config)
        filter_source: Optional filter by source path/name

    Returns:
        Dict containing:
            - success: Boolean indicating if search succeeded
            - results: List of matching documents with scores
            - query: The original query
            - collection: Collection searched
            - total_found: Number of results found

    Example:
        # Search for Kubernetes troubleshooting docs
        results = await rag_search(
            query="How to fix OOMKilled pods",
            collection="oncall-playbooks",
            limit=3
        )
    """
    settings = get_settings()
    collection_name = collection or settings.default_collection
    threshold = score_threshold if score_threshold is not None else settings.score_threshold

    try:
        # Generate query embedding
        embedding_service = get_embedding_service()
        query_vector = embedding_service.embed_text(query)

        # Get vector store and search
        store = get_vector_store()
        await store.initialize()

        search_results = await store.search(
            query_embedding=query_vector,
            collection=collection_name,
            limit=limit,
            score_threshold=threshold,
            filter_source=filter_source,
        )

        # Format results
        results = [result.to_dict() for result in search_results]

        logger.info(
            f"Search in '{collection_name}' ({store.backend_name}): "
            f"query='{query[:50]}...', found={len(results)}, limit={limit}"
        )

        return {
            "success": True,
            "results": results,
            "query": query,
            "collection": collection_name,
            "total_found": len(results),
        }

    except Exception as e:
        logger.error(f"Search error in collection '{collection_name}': {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "collection": collection_name,
            "results": [],
            "total_found": 0,
        }
