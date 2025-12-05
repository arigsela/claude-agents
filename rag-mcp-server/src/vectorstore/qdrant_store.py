"""Qdrant vector store implementation.

Uses Qdrant as the vector database backend.
Ideal for local development and standalone deployments.
"""

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

from src.vectorstore.base import (
    VectorStore,
    StoredDocument,
    SearchResult,
    CollectionStats,
)

logger = logging.getLogger(__name__)


class QdrantStore(VectorStore):
    """Qdrant implementation of the VectorStore interface.

    Configuration via environment variables:
        RAG_QDRANT_URL: Qdrant server URL (default: http://localhost:6333)
        RAG_QDRANT_API_KEY: Optional API key for Qdrant Cloud
        RAG_VECTOR_SIZE: Vector dimension size (default: 384)
        RAG_DISTANCE_METRIC: Distance metric (default: Cosine)
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: Optional[str] = None,
        timeout: int = 30,
        vector_size: int = 384,
        distance_metric: str = "Cosine",
    ):
        """Initialize Qdrant store.

        Args:
            url: Qdrant server URL
            api_key: Optional API key for authentication
            timeout: Client timeout in seconds
            vector_size: Dimension of vectors
            distance_metric: Distance metric (Cosine, Euclidean, Dot)
        """
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.vector_size = vector_size
        self.distance_metric = distance_metric
        self._client: Optional[QdrantClient] = None

    async def initialize(self) -> None:
        """Initialize connection to Qdrant."""
        if self._client is None:
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
            logger.info(f"Connected to Qdrant at {self.url}")

    async def close(self) -> None:
        """Close Qdrant connection."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Closed Qdrant connection")

    @property
    def client(self) -> QdrantClient:
        """Get Qdrant client, initializing if needed."""
        if self._client is None:
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    async def ensure_collection(self, collection: str) -> bool:
        """Ensure collection exists in Qdrant."""
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if collection in collection_names:
            return False

        logger.info(f"Creating Qdrant collection: {collection}")
        self.client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=self.vector_size,
                distance=Distance[self.distance_metric.upper()],
            ),
        )
        return True

    async def store(
        self,
        content: str,
        embedding: List[float],
        collection: str,
        content_hash: str,
        source: Optional[str] = None,
        title: Optional[str] = None,
        chunk_index: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StoredDocument:
        """Store document in Qdrant."""
        await self.ensure_collection(collection)

        doc_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)

        payload = {
            "content": content,
            "content_hash": content_hash,
            "source": source or "unknown",
            "title": title or "",
            "chunk_index": chunk_index,
            "timestamp": timestamp.isoformat(),
            "indexed_at": timestamp.isoformat(),
        }

        if metadata:
            payload["metadata"] = metadata

        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=doc_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

        logger.debug(f"Stored document {doc_id[:8]}... in Qdrant collection '{collection}'")

        return StoredDocument(
            id=doc_id,
            content=content,
            content_hash=content_hash,
            embedding=embedding,
            metadata=metadata or {},
            source=source or "unknown",
            title=title or "",
            chunk_index=chunk_index,
            created_at=timestamp,
        )

    async def search(
        self,
        query_embedding: List[float],
        collection: str,
        limit: int = 5,
        score_threshold: float = 0.0,
        filter_source: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search for similar documents in Qdrant."""
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

        response = self.client.query_points(
            collection_name=collection,
            query=query_embedding,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=search_filter,
            with_payload=True,
        )

        results = []
        for hit in response.points:
            results.append(
                SearchResult(
                    id=str(hit.id),
                    score=hit.score,
                    content=hit.payload.get("content", ""),
                    metadata={
                        "source": hit.payload.get("source", "unknown"),
                        "chunk_index": hit.payload.get("chunk_index", 0),
                        "timestamp": hit.payload.get("timestamp", ""),
                        "title": hit.payload.get("title", ""),
                    },
                )
            )

        return results

    async def find_by_hash(
        self,
        content_hash: str,
        collection: str,
    ) -> Optional[StoredDocument]:
        """Find document by content hash in Qdrant."""
        try:
            result = self.client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="content_hash",
                            match=MatchValue(value=content_hash),
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
                with_vectors=True,
            )[0]

            if not result:
                return None

            point = result[0]
            return StoredDocument(
                id=str(point.id),
                content=point.payload.get("content", ""),
                content_hash=content_hash,
                embedding=point.vector if isinstance(point.vector, list) else [],
                metadata=point.payload.get("metadata", {}),
                source=point.payload.get("source", "unknown"),
                title=point.payload.get("title", ""),
                chunk_index=point.payload.get("chunk_index", 0),
            )
        except Exception:
            return None

    async def list_collections(self) -> List[str]:
        """List all Qdrant collections."""
        collections = self.client.get_collections().collections
        return [c.name for c in collections]

    async def get_collection_stats(self, collection: str) -> Optional[CollectionStats]:
        """Get Qdrant collection statistics."""
        try:
            info = self.client.get_collection(collection)

            # Extract vector config
            vector_config = info.config.params.vectors
            if hasattr(vector_config, "size"):
                vector_size = vector_config.size
                distance = str(vector_config.distance)
            else:
                first_config = next(iter(vector_config.values()), None)
                vector_size = first_config.size if first_config else 0
                distance = str(first_config.distance) if first_config else "unknown"

            return CollectionStats(
                name=collection,
                points_count=info.points_count or 0,
                vectors_count=info.vectors_count or 0,
                indexed_vectors_count=info.indexed_vectors_count or 0,
                status=str(info.status),
                vector_size=vector_size,
                distance=distance,
            )
        except Exception:
            return None

    async def delete_collection(self, collection: str) -> bool:
        """Delete a Qdrant collection."""
        try:
            collections = await self.list_collections()
            if collection not in collections:
                return False

            self.client.delete_collection(collection)
            logger.warning(f"Deleted Qdrant collection: {collection}")
            return True
        except Exception as e:
            logger.error(f"Error deleting collection {collection}: {e}")
            return False

    @property
    def backend_name(self) -> str:
        """Return backend name."""
        return "qdrant"
