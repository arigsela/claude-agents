"""PostgreSQL + pgvector vector store implementation.

Uses PostgreSQL with the pgvector extension as the vector database backend.
Ideal for Kubernetes deployments with existing RDS infrastructure.

Requires:
    - PostgreSQL 14+ with pgvector extension
    - asyncpg for async database access
    - pgvector Python package
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import asyncpg
    from pgvector.asyncpg import register_vector

    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    asyncpg = None

from src.vectorstore.base import (
    VectorStore,
    StoredDocument,
    SearchResult,
    CollectionStats,
)

logger = logging.getLogger(__name__)


class PgVectorStore(VectorStore):
    """PostgreSQL + pgvector implementation of the VectorStore interface.

    Configuration via environment variables:
        RAG_DATABASE_URL: PostgreSQL connection string
        RAG_VECTOR_SIZE: Vector dimension size (default: 384)

    Example connection string:
        postgresql://user:password@host:5432/database

    Table schema (created automatically):
        CREATE TABLE rag_documents (
            id UUID PRIMARY KEY,
            collection VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            content_hash VARCHAR(32) NOT NULL,
            embedding vector(384),
            source VARCHAR(1024),
            title VARCHAR(512),
            chunk_index INTEGER DEFAULT 0,
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """

    def __init__(
        self,
        database_url: str,
        vector_size: int = 384,
        min_connections: int = 2,
        max_connections: int = 10,
    ):
        """Initialize PostgreSQL vector store.

        Args:
            database_url: PostgreSQL connection string
            vector_size: Dimension of vectors (must match embedding model)
            min_connections: Minimum pool connections
            max_connections: Maximum pool connections
        """
        if not PGVECTOR_AVAILABLE:
            raise ImportError(
                "pgvector and asyncpg are required for PostgreSQL backend. "
                "Install with: pip install asyncpg pgvector"
            )

        self.database_url = database_url
        self.vector_size = vector_size
        self.min_connections = min_connections
        self.max_connections = max_connections
        self._pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        """Initialize PostgreSQL connection pool and create tables."""
        if self._pool is not None:
            return

        # Create connection pool
        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=self.min_connections,
            max_size=self.max_connections,
            init=self._init_connection,
        )

        # Create extension and tables
        async with self._pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create main documents table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    collection VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    content_hash VARCHAR(32) NOT NULL,
                    embedding vector({self.vector_size}),
                    source VARCHAR(1024),
                    title VARCHAR(512),
                    chunk_index INTEGER DEFAULT 0,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Create indexes for efficient queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_collection
                ON rag_documents(collection)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_content_hash
                ON rag_documents(collection, content_hash)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_source
                ON rag_documents(collection, source)
            """)

            # Create HNSW index for vector similarity search (fast approximate search)
            # Using cosine distance (vector_cosine_ops)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rag_documents_embedding
                ON rag_documents
                USING hnsw (embedding vector_cosine_ops)
            """)

            # Create collections metadata table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_collections (
                    name VARCHAR(255) PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    description TEXT
                )
            """)

        logger.info(f"Connected to PostgreSQL with pgvector (pool size: {self.min_connections}-{self.max_connections})")

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """Initialize each connection with pgvector support."""
        await register_vector(conn)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Closed PostgreSQL connection pool")

    @property
    def pool(self) -> asyncpg.Pool:
        """Get connection pool, raising if not initialized."""
        if self._pool is None:
            raise RuntimeError("PgVectorStore not initialized. Call initialize() first.")
        return self._pool

    async def ensure_collection(self, collection: str) -> bool:
        """Ensure collection exists (tracked in metadata table)."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT name FROM rag_collections WHERE name = $1",
                collection,
            )
            if result:
                return False

            await conn.execute(
                "INSERT INTO rag_collections (name) VALUES ($1) ON CONFLICT DO NOTHING",
                collection,
            )
            logger.info(f"Created pgvector collection: {collection}")
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
        """Store document in PostgreSQL with pgvector."""
        await self.ensure_collection(collection)

        doc_id = uuid.uuid4()
        timestamp = datetime.now(timezone.utc)

        async with self.pool.acquire() as conn:
            # Convert metadata to JSON string if present
            import json

            metadata_json = json.dumps(metadata) if metadata else None

            await conn.execute(
                """
                INSERT INTO rag_documents
                    (id, collection, content, content_hash, embedding, source, title, chunk_index, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                doc_id,
                collection,
                content,
                content_hash,
                embedding,
                source or "unknown",
                title or "",
                chunk_index,
                metadata_json,
                timestamp,
            )

        logger.debug(f"Stored document {doc_id} in pgvector collection '{collection}'")

        return StoredDocument(
            id=str(doc_id),
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
        """Search for similar documents using pgvector."""
        async with self.pool.acquire() as conn:
            # Build query with optional source filter
            # Using 1 - cosine distance to get similarity score (0-1 range)
            if filter_source:
                rows = await conn.fetch(
                    """
                    SELECT
                        id,
                        content,
                        source,
                        title,
                        chunk_index,
                        metadata,
                        1 - (embedding <=> $1) as score
                    FROM rag_documents
                    WHERE collection = $2
                      AND source = $3
                      AND 1 - (embedding <=> $1) >= $4
                    ORDER BY embedding <=> $1
                    LIMIT $5
                    """,
                    query_embedding,
                    collection,
                    filter_source,
                    score_threshold,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT
                        id,
                        content,
                        source,
                        title,
                        chunk_index,
                        metadata,
                        1 - (embedding <=> $1) as score
                    FROM rag_documents
                    WHERE collection = $2
                      AND 1 - (embedding <=> $1) >= $3
                    ORDER BY embedding <=> $1
                    LIMIT $4
                    """,
                    query_embedding,
                    collection,
                    score_threshold,
                    limit,
                )

            results = []
            for row in rows:
                import json

                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                metadata.update(
                    {
                        "source": row["source"],
                        "title": row["title"],
                        "chunk_index": row["chunk_index"],
                    }
                )

                results.append(
                    SearchResult(
                        id=str(row["id"]),
                        score=float(row["score"]),
                        content=row["content"],
                        metadata=metadata,
                    )
                )

            return results

    async def find_by_hash(
        self,
        content_hash: str,
        collection: str,
    ) -> Optional[StoredDocument]:
        """Find document by content hash for deduplication."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, content, content_hash, embedding, source, title, chunk_index, metadata, created_at
                FROM rag_documents
                WHERE collection = $1 AND content_hash = $2
                LIMIT 1
                """,
                collection,
                content_hash,
            )

            if not row:
                return None

            import json

            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            return StoredDocument(
                id=str(row["id"]),
                content=row["content"],
                content_hash=row["content_hash"],
                embedding=list(row["embedding"]) if row["embedding"] else [],
                metadata=metadata,
                source=row["source"],
                title=row["title"],
                chunk_index=row["chunk_index"],
                created_at=row["created_at"],
            )

    async def list_collections(self) -> List[str]:
        """List all collection names."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT name FROM rag_collections ORDER BY name")
            return [row["name"] for row in rows]

    async def get_collection_stats(self, collection: str) -> Optional[CollectionStats]:
        """Get collection statistics from PostgreSQL."""
        async with self.pool.acquire() as conn:
            # Check if collection exists
            exists = await conn.fetchrow(
                "SELECT name FROM rag_collections WHERE name = $1",
                collection,
            )
            if not exists:
                return None

            # Get document count
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) as count FROM rag_documents WHERE collection = $1",
                collection,
            )
            points_count = count_row["count"] if count_row else 0

            return CollectionStats(
                name=collection,
                points_count=points_count,
                vectors_count=points_count,  # Same as points in pgvector
                indexed_vectors_count=points_count,  # Assume all indexed
                status="green",
                vector_size=self.vector_size,
                distance="Cosine",
            )

    async def delete_collection(self, collection: str) -> bool:
        """Delete a collection and all its documents."""
        async with self.pool.acquire() as conn:
            # Check if exists
            exists = await conn.fetchrow(
                "SELECT name FROM rag_collections WHERE name = $1",
                collection,
            )
            if not exists:
                return False

            # Delete documents
            await conn.execute(
                "DELETE FROM rag_documents WHERE collection = $1",
                collection,
            )

            # Delete collection metadata
            await conn.execute(
                "DELETE FROM rag_collections WHERE name = $1",
                collection,
            )

            logger.warning(f"Deleted pgvector collection: {collection}")
            return True

    @property
    def backend_name(self) -> str:
        """Return backend name."""
        return "pgvector"
