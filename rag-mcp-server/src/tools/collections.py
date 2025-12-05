"""RAG Collections Tool - Manage vector database collections.

Provides MCP tools for listing collections and getting collection statistics.
"""

import logging
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import CollectionInfo

from src.config import get_settings
from src.tools.search import get_qdrant_client

logger = logging.getLogger(__name__)


async def rag_list_collections() -> Dict[str, Any]:
    """List all available collections in the vector database.

    Returns:
        Dict containing:
            - success: Boolean indicating if operation succeeded
            - collections: List of collection names
            - count: Number of collections

    Example:
        result = await rag_list_collections()
        # {"success": True, "collections": ["oncall-playbooks", "runbooks"], "count": 2}
    """
    try:
        client = get_qdrant_client()
        collections_response = client.get_collections()

        collection_names = [c.name for c in collections_response.collections]

        logger.info(f"Listed {len(collection_names)} collections")

        return {
            "success": True,
            "collections": collection_names,
            "count": len(collection_names),
        }

    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "collections": [],
            "count": 0,
        }


async def rag_collection_stats(
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """Get statistics for a specific collection or all collections.

    Provides detailed information about collection size, vector count,
    and configuration.

    Args:
        collection: Collection name (default: from config, or all if None)

    Returns:
        Dict containing:
            - success: Boolean indicating if operation succeeded
            - stats: Collection statistics (single or list)
            - collection: Collection name (if single collection)

    Example:
        # Single collection stats
        result = await rag_collection_stats(collection="oncall-playbooks")
        # {
        #     "success": True,
        #     "collection": "oncall-playbooks",
        #     "stats": {
        #         "vectors_count": 150,
        #         "points_count": 150,
        #         "indexed_vectors_count": 150,
        #         "status": "green",
        #         "vector_size": 384,
        #         "distance": "Cosine"
        #     }
        # }

        # All collections stats
        result = await rag_collection_stats()
        # {"success": True, "stats": [...], "total_collections": 3}
    """
    try:
        client = get_qdrant_client()
        settings = get_settings()

        if collection:
            # Get stats for specific collection
            collection_name = collection

            # Check if collection exists
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]

            if collection_name not in collection_names:
                return {
                    "success": False,
                    "error": f"Collection '{collection_name}' not found",
                    "collection": collection_name,
                    "available_collections": collection_names,
                }

            # Get collection info
            info = client.get_collection(collection_name)

            stats = _format_collection_stats(info)

            logger.info(
                f"Collection '{collection_name}' stats: "
                f"{stats['points_count']} points, status={stats['status']}"
            )

            return {
                "success": True,
                "collection": collection_name,
                "stats": stats,
            }

        else:
            # Get stats for all collections
            collections = client.get_collections().collections
            all_stats = []

            for col in collections:
                info = client.get_collection(col.name)
                stats = _format_collection_stats(info)
                stats["name"] = col.name
                all_stats.append(stats)

            # Sort by points count descending
            all_stats.sort(key=lambda x: x["points_count"], reverse=True)

            total_points = sum(s["points_count"] for s in all_stats)

            logger.info(
                f"Retrieved stats for {len(all_stats)} collections, "
                f"total points: {total_points}"
            )

            return {
                "success": True,
                "stats": all_stats,
                "total_collections": len(all_stats),
                "total_points": total_points,
            }

    except Exception as e:
        logger.error(f"Error getting collection stats: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "stats": None,
        }


def _format_collection_stats(info: CollectionInfo) -> Dict[str, Any]:
    """Format collection info into stats dictionary.

    Args:
        info: Qdrant CollectionInfo object

    Returns:
        Formatted stats dictionary
    """
    # Extract vector config
    vector_config = info.config.params.vectors

    # Handle both single and named vector configs
    if hasattr(vector_config, "size"):
        # Single vector config
        vector_size = vector_config.size
        distance = str(vector_config.distance)
    else:
        # Named vectors - get first one
        first_config = next(iter(vector_config.values()), None)
        vector_size = first_config.size if first_config else 0
        distance = str(first_config.distance) if first_config else "unknown"

    # Handle qdrant-client 1.7+ API changes where counts might be in different locations
    vectors_count = getattr(info, 'vectors_count', None)
    points_count = getattr(info, 'points_count', None)
    indexed_vectors_count = getattr(info, 'indexed_vectors_count', None)
    segments_count = getattr(info, 'segments_count', None)

    # Fallback to checking nested attributes for newer API versions
    if vectors_count is None and hasattr(info, 'collection_info'):
        vectors_count = getattr(info.collection_info, 'vectors_count', 0)
    if points_count is None and hasattr(info, 'collection_info'):
        points_count = getattr(info.collection_info, 'points_count', 0)

    return {
        "vectors_count": vectors_count or 0,
        "points_count": points_count or 0,
        "indexed_vectors_count": indexed_vectors_count or 0,
        "status": str(info.status),
        "vector_size": vector_size,
        "distance": distance,
        "segments_count": segments_count or 0,
    }


async def rag_delete_collection(
    collection: str,
    confirm: bool = False,
) -> Dict[str, Any]:
    """Delete a collection from the vector database.

    WARNING: This permanently deletes all documents in the collection.

    Args:
        collection: Collection name to delete
        confirm: Must be True to actually delete (safety flag)

    Returns:
        Dict containing:
            - success: Boolean indicating if deletion succeeded
            - collection: Collection name
            - message: Status message

    Example:
        # This will fail (safety check)
        result = await rag_delete_collection("old-collection")
        # {"success": False, "error": "Confirm flag required"}

        # This will delete
        result = await rag_delete_collection("old-collection", confirm=True)
        # {"success": True, "collection": "old-collection", "message": "Deleted"}
    """
    if not confirm:
        return {
            "success": False,
            "error": "Set confirm=True to delete collection. This is irreversible.",
            "collection": collection,
        }

    try:
        client = get_qdrant_client()

        # Check if collection exists
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]

        if collection not in collection_names:
            return {
                "success": False,
                "error": f"Collection '{collection}' not found",
                "collection": collection,
            }

        # Get stats before deletion for logging
        info = client.get_collection(collection)
        points_count = info.points_count or 0

        # Delete collection
        client.delete_collection(collection)

        logger.warning(
            f"Deleted collection '{collection}' with {points_count} points"
        )

        return {
            "success": True,
            "collection": collection,
            "message": f"Collection '{collection}' deleted ({points_count} points removed)",
            "points_deleted": points_count,
        }

    except Exception as e:
        logger.error(f"Error deleting collection '{collection}': {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "collection": collection,
        }
