"""RAG Search Tool - Semantic search across document collections.

Provides the rag_search MCP tool for retrieving relevant documents
from Qdrant vector database using semantic similarity.
"""

import logging
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.config import get_settings
from src.embeddings import get_embedding_service

logger = logging.getLogger(__name__)

# Qdrant client singleton
_qdrant_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """Get or create Qdrant client instance."""
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout,
        )
        logger.info(f"Connected to Qdrant at {settings.qdrant_url}")
    return _qdrant_client


async def rag_search(
    query: str,
    collection: Optional[str] = None,
    limit: int = 5,
    score_threshold: Optional[float] = None,
    filter_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for relevant documents using semantic similarity.

    Performs vector similarity search in Qdrant to find documents
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

        # Build filter if specified
        search_filter = None
        if filter_source:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=filter_source),
                    )
                ]
            )

        # Perform search using query_points (qdrant-client 1.7+ API)
        client = get_qdrant_client()
        from qdrant_client.models import QueryResponse
        search_response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            score_threshold=threshold,
            query_filter=search_filter,
            with_payload=True,
        )
        # Extract points from QueryResponse
        search_results = search_response.points if hasattr(search_response, 'points') else []

        # Format results
        results = []
        for hit in search_results:
            result = {
                "id": str(hit.id),
                "score": round(hit.score, 4),
                "content": hit.payload.get("content", ""),
                "metadata": {
                    "source": hit.payload.get("source", "unknown"),
                    "chunk_index": hit.payload.get("chunk_index", 0),
                    "timestamp": hit.payload.get("timestamp", ""),
                    "title": hit.payload.get("title", ""),
                },
            }
            results.append(result)

        logger.info(
            f"Search in '{collection_name}': query='{query[:50]}...', "
            f"found={len(results)}, limit={limit}"
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
