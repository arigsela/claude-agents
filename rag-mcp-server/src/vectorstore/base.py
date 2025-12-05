"""Abstract base class for vector store backends.

Defines the common interface that all vector store implementations
(Qdrant, PostgreSQL+pgvector) must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class StoredDocument:
    """Represents a document stored in the vector database."""

    id: str
    content: str
    content_hash: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    title: str = ""
    chunk_index: int = 0
    created_at: Optional[datetime] = None


@dataclass
class SearchResult:
    """Represents a search result from the vector database."""

    id: str
    score: float
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "score": round(self.score, 4),
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass
class CollectionStats:
    """Statistics for a collection."""

    name: str
    points_count: int
    vectors_count: int
    indexed_vectors_count: int
    status: str
    vector_size: int
    distance: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "points_count": self.points_count,
            "vectors_count": self.vectors_count,
            "indexed_vectors_count": self.indexed_vectors_count,
            "status": self.status,
            "vector_size": self.vector_size,
            "distance": self.distance,
        }


class VectorStore(ABC):
    """Abstract base class for vector store implementations.

    All vector database backends must implement this interface to ensure
    compatibility with the RAG MCP server tools.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the vector store connection.

        Should be called before any other operations.
        May create necessary tables/collections if they don't exist.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the vector store connection.

        Clean up any resources (connection pools, etc.)
        """
        pass

    @abstractmethod
    async def ensure_collection(self, collection: str) -> bool:
        """Ensure a collection exists, create if not.

        Args:
            collection: Name of the collection

        Returns:
            True if collection was created, False if already existed
        """
        pass

    @abstractmethod
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
        """Store a document with its embedding.

        Args:
            content: Text content to store
            embedding: Vector embedding of the content
            collection: Collection name
            content_hash: MD5 hash for deduplication
            source: Source identifier (file path, URL, etc.)
            title: Document title
            chunk_index: Index if content is part of chunked document
            metadata: Additional metadata

        Returns:
            StoredDocument with assigned ID
        """
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: List[float],
        collection: str,
        limit: int = 5,
        score_threshold: float = 0.0,
        filter_source: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search for similar documents.

        Args:
            query_embedding: Vector embedding of the query
            collection: Collection to search
            limit: Maximum number of results
            score_threshold: Minimum similarity score (0.0-1.0)
            filter_source: Optional filter by source

        Returns:
            List of SearchResult ordered by similarity (descending)
        """
        pass

    @abstractmethod
    async def find_by_hash(
        self,
        content_hash: str,
        collection: str,
    ) -> Optional[StoredDocument]:
        """Find a document by its content hash (for deduplication).

        Args:
            content_hash: MD5 hash of content
            collection: Collection to search

        Returns:
            StoredDocument if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_collections(self) -> List[str]:
        """List all collection names.

        Returns:
            List of collection names
        """
        pass

    @abstractmethod
    async def get_collection_stats(self, collection: str) -> Optional[CollectionStats]:
        """Get statistics for a collection.

        Args:
            collection: Collection name

        Returns:
            CollectionStats or None if collection doesn't exist
        """
        pass

    @abstractmethod
    async def delete_collection(self, collection: str) -> bool:
        """Delete a collection and all its documents.

        Args:
            collection: Collection name to delete

        Returns:
            True if deleted, False if didn't exist
        """
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return the name of the backend (e.g., 'qdrant', 'pgvector')."""
        pass
