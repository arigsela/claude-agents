"""RAG Store Tool - Store documents in vector database.

Provides the rag_store MCP tool for indexing documents
into Qdrant vector database with deduplication support.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)

from src.config import get_settings
from src.embeddings import get_embedding_service
from src.tools.search import get_qdrant_client

logger = logging.getLogger(__name__)


def _generate_content_hash(content: str) -> str:
    """Generate MD5 hash for content deduplication.

    Args:
        content: Text content to hash

    Returns:
        MD5 hash string
    """
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _ensure_collection_exists(client: QdrantClient, collection_name: str) -> bool:
    """Ensure collection exists, create if not.

    Args:
        client: Qdrant client instance
        collection_name: Name of collection

    Returns:
        True if collection was created, False if already existed
    """
    settings = get_settings()

    # Check if collection exists
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]

    if collection_name in collection_names:
        return False

    # Create collection with configured vector params
    logger.info(f"Creating collection: {collection_name}")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=settings.vector_size,
            distance=Distance[settings.distance_metric.upper()],
        ),
    )
    return True


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
        client = get_qdrant_client()

        # Ensure collection exists
        _ensure_collection_exists(client, collection_name)

        # Generate content hash for deduplication
        content_hash = _generate_content_hash(content)

        # Check for existing document with same hash (deduplication)
        if deduplicate:
            existing = client.scroll(
                collection_name=collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="content_hash",
                            match=MatchValue(value=content_hash),
                        )
                    ]
                ),
                limit=1,
            )[0]

            if existing:
                logger.debug(f"Document already exists with hash {content_hash[:8]}...")
                return {
                    "success": True,
                    "id": str(existing[0].id),
                    "collection": collection_name,
                    "created": False,
                    "content_hash": content_hash,
                    "message": "Document already exists (deduplicated)",
                }

        # Generate embedding
        embedding_service = get_embedding_service()
        vector = embedding_service.embed_text(content)

        # Prepare payload
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "content": content,
            "content_hash": content_hash,
            "source": source or "unknown",
            "title": title or "",
            "chunk_index": chunk_index,
            "timestamp": timestamp,
            "indexed_at": timestamp,
        }

        # Add custom metadata
        if metadata:
            payload["metadata"] = metadata

        # Generate document ID
        doc_id = str(uuid.uuid4())

        # Store in Qdrant
        client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=doc_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )

        logger.info(
            f"Stored document in '{collection_name}': "
            f"id={doc_id[:8]}..., source={source or 'unknown'}"
        )

        return {
            "success": True,
            "id": doc_id,
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
