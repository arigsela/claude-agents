"""RAG Collections Tool - Manage vector database collections.

Provides MCP tools for listing collections and getting collection statistics.

Supports multiple backends:
    - Qdrant (local development)
    - PostgreSQL + pgvector (Kubernetes/RDS)
"""

import logging
from typing import Any, Dict, List, Optional

from src.config import get_settings
from src.vectorstore import get_vector_store

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
        store = get_vector_store()
        await store.initialize()

        collection_names = await store.list_collections()

        logger.info(f"Listed {len(collection_names)} collections ({store.backend_name})")

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
        store = get_vector_store()
        await store.initialize()

        if collection:
            # Get stats for specific collection
            stats = await store.get_collection_stats(collection)

            if stats is None:
                collection_names = await store.list_collections()
                return {
                    "success": False,
                    "error": f"Collection '{collection}' not found",
                    "collection": collection,
                    "available_collections": collection_names,
                }

            logger.info(
                f"Collection '{collection}' stats ({store.backend_name}): "
                f"{stats.points_count} points, status={stats.status}"
            )

            return {
                "success": True,
                "collection": collection,
                "stats": stats.to_dict(),
            }

        else:
            # Get stats for all collections
            collection_names = await store.list_collections()
            all_stats = []

            for name in collection_names:
                stats = await store.get_collection_stats(name)
                if stats:
                    all_stats.append(stats.to_dict())

            # Sort by points count descending
            all_stats.sort(key=lambda x: x["points_count"], reverse=True)

            total_points = sum(s["points_count"] for s in all_stats)

            logger.info(
                f"Retrieved stats for {len(all_stats)} collections ({store.backend_name}), "
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
        store = get_vector_store()
        await store.initialize()

        # Get stats before deletion for logging
        stats = await store.get_collection_stats(collection)
        if stats is None:
            return {
                "success": False,
                "error": f"Collection '{collection}' not found",
                "collection": collection,
            }

        points_count = stats.points_count

        # Delete collection
        deleted = await store.delete_collection(collection)

        if deleted:
            logger.warning(
                f"Deleted collection '{collection}' with {points_count} points ({store.backend_name})"
            )
            return {
                "success": True,
                "collection": collection,
                "message": f"Collection '{collection}' deleted ({points_count} points removed)",
                "points_deleted": points_count,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to delete collection '{collection}'",
                "collection": collection,
            }

    except Exception as e:
        logger.error(f"Error deleting collection '{collection}': {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "collection": collection,
        }
