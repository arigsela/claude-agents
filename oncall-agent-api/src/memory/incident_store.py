"""
sqlite-vec-based incident memory store.

Stores past incidents with embeddings for similarity search.
Uses sqlite-vec with local file persistence (no external server required).

Architecture inspired by Incident.io's hybrid approach:
- Deterministic filtering by error_type (reduces noise)
- Vector similarity for semantic matching
- Score boosting for same namespace/service matches

Usage:
    store = IncidentMemoryStore()

    # Store an incident
    store.store_incident(
        service="chores-tracker-backend",
        namespace="chores-tracker-backend",
        cluster="default",
        error_type="OOMKilled",
        root_cause="Memory limit too low",
        remediation_steps=["Increase memory to 1Gi"],
        severity="high"
    )

    # Find similar incidents
    similar = store.find_similar(
        service="chores-tracker-backend",
        namespace="chores-tracker-backend",
        error_type="OOMKilled"
    )
"""

import logging
import os
import sqlite3
import struct
import uuid
from datetime import datetime
from typing import Any

try:
    import sqlite_vec

    SQLITE_VEC_AVAILABLE = True
except ImportError:
    SQLITE_VEC_AVAILABLE = False

from .embeddings import create_incident_text, create_query_text
from .models import SimilarIncident, StoredIncident

logger = logging.getLogger(__name__)

# Embedding dimension for simple text hashing (we'll use a basic approach)
# For production, you'd use sentence-transformers or OpenAI embeddings
EMBEDDING_DIM = 384


def _serialize_vector(embedding: list[float]) -> bytes:
    """Serialize a float list to bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def simple_text_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Create a simple text embedding using character-level hashing.

    This is a basic approach that works without external ML libraries.
    For better results, replace with sentence-transformers or OpenAI embeddings.

    Args:
        text: Text to embed
        dim: Embedding dimension

    Returns:
        List of floats representing the embedding
    """
    import hashlib

    # Normalize text
    text = text.lower().strip()

    # Create embedding by hashing n-grams
    embedding = [0.0] * dim

    # Use different n-gram sizes for richer representation
    for n in [2, 3, 4]:
        for i in range(len(text) - n + 1):
            ngram = text[i : i + n]
            # Hash the n-gram and use it to set embedding values
            h = int(hashlib.md5(ngram.encode()).hexdigest(), 16)
            idx = h % dim
            embedding[idx] += 1.0

    # Normalize
    magnitude = sum(x * x for x in embedding) ** 0.5
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


class IncidentMemoryStore:
    """
    Persistent incident memory using sqlite-vec.

    Features:
    - Vector similarity search for finding similar past incidents
    - Metadata filtering (namespace, service, error_type)
    - Local file persistence (survives container restarts)
    - Hybrid search: deterministic filters + vector similarity

    Uses a simple character-level embedding for compatibility.
    Can be upgraded to use sentence-transformers for better results.
    """

    # Default configuration
    DEFAULT_PERSIST_DIR = "data/incident_memory"
    DEFAULT_TABLE_NAME = "incidents"
    DEFAULT_MIN_SIMILARITY = 0.3  # Lower threshold for simple embeddings

    def __init__(self, persist_directory: str | None = None, table_name: str = DEFAULT_TABLE_NAME):
        """
        Initialize sqlite-vec with persistence.

        Args:
            persist_directory: Directory to store SQLite data.
                              Defaults to 'data/incident_memory'
            table_name: Name of the table (kept for API compatibility).
                       Defaults to 'incidents'

        Raises:
            ImportError: If sqlite-vec is not installed
        """
        if not SQLITE_VEC_AVAILABLE:
            raise ImportError(
                "sqlite-vec is required for incident memory. "
                "Install it with: pip install sqlite-vec"
            )

        self.persist_directory = persist_directory or os.getenv(
            "INCIDENT_MEMORY_PATH", self.DEFAULT_PERSIST_DIR
        )
        self.table_name = table_name

        # Create persist directory if it doesn't exist
        os.makedirs(self.persist_directory, exist_ok=True)

        # Initialize SQLite with sqlite-vec extension
        self.db_path = os.path.join(self.persist_directory, "incidents.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for concurrent reads
        self.conn.execute("PRAGMA journal_mode=WAL")

        # Load sqlite-vec extension
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

        # Create tables
        self._create_tables()

        count = self._count_rows()
        logger.info(
            f"Incident memory initialized: {count} incidents stored "
            f"(persist_dir={self.persist_directory})"
        )

    def _create_tables(self) -> None:
        """Create the metadata and vector tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL,
                service TEXT NOT NULL,
                namespace TEXT NOT NULL,
                cluster TEXT NOT NULL,
                error_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'medium',
                confidence TEXT NOT NULL DEFAULT 'medium',
                resolution_outcome TEXT NOT NULL DEFAULT 'resolved',
                root_cause TEXT NOT NULL DEFAULT '',
                remediation_steps TEXT NOT NULL DEFAULT '',
                llm_model TEXT NOT NULL DEFAULT 'unknown',
                timestamp TEXT NOT NULL,
                document_text TEXT NOT NULL DEFAULT '',
                time_to_resolution_minutes INTEGER DEFAULT -1
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_error_type ON incidents(error_type);
            CREATE INDEX IF NOT EXISTS idx_incidents_id ON incidents(id);
        """)

        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_incidents USING vec0(
                embedding float[384]
            )
        """)
        self.conn.commit()

    def _count_rows(self) -> int:
        """Count total incidents in the store."""
        result = self.conn.execute("SELECT COUNT(*) FROM incidents").fetchone()
        return result[0] if result else 0

    def store_incident(
        self,
        service: str,
        namespace: str,
        cluster: str,
        error_type: str,
        root_cause: str,
        remediation_steps: list[str],
        severity: str,
        confidence: str = "medium",
        resolution_outcome: str = "resolved",
        summary: str | None = None,
        llm_model: str | None = None,
        time_to_resolution_minutes: int | None = None,
    ) -> str:
        """
        Store a resolved incident for future retrieval.

        The incident is embedded and stored with metadata for filtering.

        Args:
            service: Service name (e.g., 'chores-tracker-backend')
            namespace: Kubernetes namespace
            cluster: Cluster name (e.g., 'dev-eks')
            error_type: Error type (e.g., 'OOMKilled', 'CrashLoopBackOff')
            root_cause: Root cause analysis from LLM
            remediation_steps: List of steps taken to resolve
            severity: Severity level ('critical', 'high', 'medium', 'low')
            confidence: LLM confidence ('high', 'medium', 'low')
            resolution_outcome: Outcome ('resolved', 'escalated', 'recurring')
            summary: Optional brief summary (defaults to root_cause)
            llm_model: Which LLM model analyzed this (defaults to ANTHROPIC_MODEL env var)
            time_to_resolution_minutes: Optional TTR in minutes

        Returns:
            Incident ID (UUID string)
        """
        # Default to configured model if not specified
        if llm_model is None:
            llm_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

        incident_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        # Create document text for embedding
        incident_data = {
            "service": service,
            "namespace": namespace,
            "cluster": cluster,
            "error_type": error_type,
            "root_cause": root_cause,
            "summary": summary or root_cause,
            "remediation_steps": remediation_steps,
        }
        document_text = create_incident_text(incident_data)

        # Create embedding
        embedding = simple_text_embedding(document_text)

        # Insert metadata into incidents table
        cursor = self.conn.execute(
            """INSERT INTO incidents
               (id, service, namespace, cluster, error_type, severity, confidence,
                resolution_outcome, root_cause, remediation_steps, llm_model,
                timestamp, document_text, time_to_resolution_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incident_id,
                service,
                namespace,
                cluster,
                error_type,
                severity,
                confidence,
                resolution_outcome,
                root_cause[:500] if root_cause else "",
                "|".join(remediation_steps),
                llm_model,
                timestamp,
                document_text,
                time_to_resolution_minutes or -1,
            ),
        )
        rowid = cursor.lastrowid

        # Insert vector into vec_incidents with matching rowid
        self.conn.execute(
            "INSERT INTO vec_incidents (rowid, embedding) VALUES (?, ?)",
            (rowid, _serialize_vector(embedding)),
        )

        self.conn.commit()

        logger.info(
            f"Stored incident {incident_id[:8]}...: "
            f"{service}/{namespace} - {error_type} ({severity})"
        )

        return incident_id

    def find_similar(
        self,
        service: str,
        namespace: str,
        error_type: str,
        error_message: str = "",
        limit: int = 5,
        min_similarity: float | None = None,
    ) -> list[SimilarIncident]:
        """
        Find similar past incidents using hybrid search.

        Strategy (inspired by Incident.io):
        1. Filter by error_type (post-filter after vector search)
        2. Vector similarity on content
        3. Boost matches in same namespace/service

        Args:
            service: Current service name
            namespace: Current namespace
            error_type: Current error type
            error_message: Optional error message for better matching
            limit: Maximum number of results to return
            min_similarity: Minimum similarity score (0.0-1.0)

        Returns:
            List of SimilarIncident objects, sorted by similarity
        """
        if self._count_rows() == 0:
            logger.debug("Incident memory is empty, no similar incidents to find")
            return []

        min_similarity = min_similarity or float(
            os.getenv("INCIDENT_MEMORY_MIN_SIMILARITY", str(self.DEFAULT_MIN_SIMILARITY))
        )

        # Build query text and embedding
        query_text = create_query_text(
            service=service, namespace=namespace, error_type=error_type, error_message=error_message
        )
        query_embedding = simple_text_embedding(query_text)

        try:
            # Over-fetch for post-filtering (sqlite-vec doesn't support WHERE on metadata)
            fetch_limit = limit * 3

            results = self.conn.execute(
                """SELECT i.id, i.service, i.namespace, i.cluster, i.error_type,
                          i.severity, i.confidence, i.resolution_outcome,
                          i.root_cause, i.remediation_steps, i.llm_model,
                          i.timestamp, i.document_text, i.time_to_resolution_minutes,
                          v.distance
                   FROM vec_incidents v
                   JOIN incidents i ON i.rowid = v.rowid
                   WHERE v.embedding MATCH ?
                   AND k = ?
                   ORDER BY v.distance""",
                (_serialize_vector(query_embedding), fetch_limit),
            ).fetchall()

        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

        similar_incidents = []

        for row in results:
            # Post-filter by error_type if specified
            if error_type and error_type.lower() != "unknown":
                if row["error_type"] != error_type:
                    continue

            # sqlite-vec returns distance (L2 distance)
            distance = row["distance"]

            # Convert distance to similarity (0-1)
            # L2 distance for normalized vectors: 0 = identical, 2 = opposite
            similarity = max(0.0, 1.0 - (distance / 2.0))

            if similarity < min_similarity:
                continue

            # Boost score for matching namespace or service
            match_reasons = []

            if row["namespace"] == namespace:
                similarity = min(1.0, similarity + 0.1)
                match_reasons.append("same namespace")

            if row["service"] == service:
                similarity = min(1.0, similarity + 0.1)
                match_reasons.append("same service")

            if row["error_type"] == error_type:
                match_reasons.append(f"same error type ({error_type})")
            else:
                match_reasons.append(f"similar to {row['error_type'] or 'unknown'}")

            # Parse remediation steps back to list
            remediation_str = row["remediation_steps"] or ""
            remediation_list = remediation_str.split("|") if remediation_str else []

            # Parse TTR
            ttr = row["time_to_resolution_minutes"]
            if ttr is not None and ttr < 0:
                ttr = None

            # Create StoredIncident
            stored_incident = StoredIncident(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                service=row["service"],
                namespace=row["namespace"],
                cluster=row["cluster"],
                error_type=row["error_type"],
                summary=(row["document_text"] or "")[:200],
                root_cause=row["root_cause"] or "",
                remediation_steps=remediation_list,
                resolution_outcome=row["resolution_outcome"] or "unknown",
                time_to_resolution_minutes=ttr,
                severity=row["severity"] or "medium",
                confidence=row["confidence"] or "medium",
                llm_model=row["llm_model"] or "unknown",
            )

            similar_incidents.append(
                SimilarIncident(
                    incident=stored_incident,
                    similarity_score=round(similarity, 3),
                    match_reasons=match_reasons,
                )
            )

        # Sort by similarity (highest first) and limit
        similar_incidents.sort(key=lambda x: x.similarity_score, reverse=True)
        result = similar_incidents[:limit]

        if result:
            logger.info(
                f"Found {len(result)} similar incidents for {service}/{error_type} "
                f"(top score: {result[0].similarity_score:.2f})"
            )
        else:
            logger.debug(f"No similar incidents found for {service}/{error_type}")

        return result

    def get_incident(self, incident_id: str) -> StoredIncident | None:
        """
        Retrieve a specific incident by ID.

        Args:
            incident_id: The incident UUID

        Returns:
            StoredIncident if found, None otherwise
        """
        try:
            # Validate incident_id is a valid UUID to prevent misuse
            try:
                uuid.UUID(incident_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid incident ID format: {incident_id[:50]}")
                return None

            row = self.conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()

            if row:
                remediation_str = row["remediation_steps"] or ""
                remediation_list = remediation_str.split("|") if remediation_str else []

                ttr = row["time_to_resolution_minutes"]
                if ttr is not None and ttr < 0:
                    ttr = None

                return StoredIncident(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    service=row["service"],
                    namespace=row["namespace"],
                    cluster=row["cluster"],
                    error_type=row["error_type"],
                    summary=(row["document_text"] or "")[:200],
                    root_cause=row["root_cause"] or "",
                    remediation_steps=remediation_list,
                    resolution_outcome=row["resolution_outcome"] or "unknown",
                    time_to_resolution_minutes=ttr,
                    severity=row["severity"] or "medium",
                    confidence=row["confidence"] or "medium",
                    llm_model=row["llm_model"] or "unknown",
                )
        except Exception as e:
            logger.error(f"Failed to retrieve incident {incident_id}: {e}")

        return None

    def delete_incident(self, incident_id: str) -> bool:
        """
        Delete an incident from the store.

        Args:
            incident_id: The incident UUID to delete

        Returns:
            True if deleted, False if not found or error
        """
        try:
            # Validate incident_id is a valid UUID
            try:
                uuid.UUID(incident_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid incident ID format for deletion: {incident_id[:50]}")
                return False

            # Look up the rowid first
            row = self.conn.execute(
                "SELECT rowid FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()

            if row is None:
                return False

            rowid = row["rowid"]

            # Delete from both tables
            self.conn.execute("DELETE FROM vec_incidents WHERE rowid = ?", (rowid,))
            self.conn.execute("DELETE FROM incidents WHERE rowid = ?", (rowid,))
            self.conn.commit()

            logger.info(f"Deleted incident {incident_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete incident {incident_id}: {e}")
            return False

    def get_stats(self) -> dict[str, Any]:
        """
        Get memory store statistics.

        Returns:
            Dictionary with stats including total count, persist directory, etc.
        """
        count = self._count_rows()

        stats = {
            "total_incidents": count,
            "persist_directory": self.persist_directory,
            "table_name": self.table_name,
            "sqlite_vec_available": SQLITE_VEC_AVAILABLE,
        }

        # Get breakdown by error type if we have incidents
        if count > 0:
            try:
                rows = self.conn.execute(
                    "SELECT error_type, COUNT(*) as cnt FROM incidents GROUP BY error_type"
                ).fetchall()
                error_types = {row["error_type"]: row["cnt"] for row in rows}
                stats["error_type_distribution"] = error_types
            except Exception as e:
                logger.debug(f"Could not get error type distribution: {e}")

        return stats

    def reset(self) -> bool:
        """
        Reset the incident memory (delete all incidents).

        WARNING: This permanently deletes all stored incidents.

        Returns:
            True if reset successful, False otherwise
        """
        try:
            self.conn.execute("DELETE FROM vec_incidents")
            self.conn.execute("DELETE FROM incidents")
            self.conn.commit()
            logger.warning("Incident memory has been reset (all incidents deleted)")
            return True
        except Exception as e:
            logger.error(f"Failed to reset incident memory: {e}")
            return False
