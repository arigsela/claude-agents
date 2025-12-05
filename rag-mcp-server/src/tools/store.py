"""RAG Store Tool - Store documents in vector database.

Provides the rag_store MCP tool for indexing documents
with deduplication support.

Supports multiple backends:
    - Qdrant (local development)
    - PostgreSQL + pgvector (Kubernetes/RDS)
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

from src.config import get_settings
from src.embeddings import get_embedding_service
from src.vectorstore import get_vector_store

logger = logging.getLogger(__name__)


def _generate_content_hash(content: str) -> str:
    """Generate MD5 hash for content deduplication.

    Args:
        content: Text content to hash

    Returns:
        MD5 hash string
    """
    return hashlib.md5(content.encode("utf-8")).hexdigest()


async def rag_store(
    content: str,
    collection: Optional[str] = None,
    source: Optional[str] = None,
    title: Optional[str] = None,
    chunk_index: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
    deduplicate: bool = True,
) -> Dict[str, Any]:
    """Store a document in the vector database.

    Indexes document content with embeddings for semantic search.
    Supports deduplication via content hashing.

    Args:
        content: Text content to store
        collection: Collection name (default: from config)
        source: Source identifier (file path, URL, etc.)
        title: Document title
        chunk_index: Index if content is part of a chunked document
        metadata: Additional metadata to store with the document
        deduplicate: If True, skip if identical content exists (default: True)

    Returns:
        Dict containing:
            - success: Boolean indicating if store succeeded
            - id: Document ID (UUID or existing if deduplicated)
            - collection: Collection name
            - created: True if new, False if updated/skipped
            - content_hash: MD5 hash of content

    Example:
        # Store a playbook document
        result = await rag_store(
            content="When pod is in CrashLoopBackOff, first check logs...",
            collection="oncall-playbooks",
            source="playbooks/k8s-troubleshooting.md",
            title="Kubernetes Pod Troubleshooting"
        )
    """
    settings = get_settings()
    collection_name = collection or settings.default_collection

    try:
        # Get vector store
        store = get_vector_store()
        await store.initialize()

        # Generate content hash for deduplication
        content_hash = _generate_content_hash(content)

        # Check for existing document with same hash (deduplication)
        if deduplicate:
            existing = await store.find_by_hash(content_hash, collection_name)
            if existing:
                logger.debug(f"Document already exists with hash {content_hash[:8]}...")
                return {
                    "success": True,
                    "id": existing.id,
                    "collection": collection_name,
                    "created": False,
                    "content_hash": content_hash,
                    "message": "Document already exists (deduplicated)",
                }

        # Generate embedding
        embedding_service = get_embedding_service()
        vector = embedding_service.embed_text(content)

        # Store document
        doc = await store.store(
            content=content,
            embedding=vector,
            collection=collection_name,
            content_hash=content_hash,
            source=source,
            title=title,
            chunk_index=chunk_index,
            metadata=metadata,
        )

        logger.info(
            f"Stored document in '{collection_name}' ({store.backend_name}): "
            f"id={doc.id[:8]}..., source={source or 'unknown'}"
        )

        return {
            "success": True,
            "id": doc.id,
            "collection": collection_name,
            "created": True,
            "content_hash": content_hash,
        }

    except Exception as e:
        logger.error(f"Store error in collection '{collection_name}': {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "collection": collection_name,
            "created": False,
        }


async def rag_store_batch(
    documents: List[Dict[str, Any]],
    collection: Optional[str] = None,
    deduplicate: bool = True,
) -> Dict[str, Any]:
    """Store multiple documents in batch.

    More efficient than individual rag_store calls for bulk indexing.

    Args:
        documents: List of dicts with keys: content, source, title, metadata
        collection: Collection name (default: from config)
        deduplicate: If True, skip identical content (default: True)

    Returns:
        Dict containing:
            - success: Boolean
            - stored: Number of documents stored
            - skipped: Number of duplicates skipped
            - errors: Number of errors
            - collection: Collection name

    Example:
        results = await rag_store_batch(
            documents=[
                {"content": "Doc 1...", "source": "file1.md"},
                {"content": "Doc 2...", "source": "file2.md"},
            ],
            collection="oncall-playbooks"
        )
    """
    settings = get_settings()
    collection_name = collection or settings.default_collection

    stored = 0
    skipped = 0
    errors = 0

    for doc in documents:
        try:
            result = await rag_store(
                content=doc.get("content", ""),
                collection=collection_name,
                source=doc.get("source"),
                title=doc.get("title"),
                chunk_index=doc.get("chunk_index", 0),
                metadata=doc.get("metadata"),
                deduplicate=deduplicate,
            )

            if result.get("success"):
                if result.get("created"):
                    stored += 1
                else:
                    skipped += 1
            else:
                errors += 1

        except Exception as e:
            logger.error(f"Batch store error: {e}")
            errors += 1

    return {
        "success": errors == 0,
        "stored": stored,
        "skipped": skipped,
        "errors": errors,
        "total": len(documents),
        "collection": collection_name,
    }
