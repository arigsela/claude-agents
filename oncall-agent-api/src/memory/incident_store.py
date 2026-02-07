"""
LanceDB-based incident memory store.

Stores past incidents with embeddings for similarity search.
Uses LanceDB with local file persistence (no external server required).

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
import re
import uuid
from datetime import datetime
from typing import Any

try:
    import lancedb

    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False

from .embeddings import create_incident_text, create_query_text
from .models import SimilarIncident, StoredIncident

# Pattern for safe query values (alphanumeric, underscore, hyphen, dot)
SAFE_QUERY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def _sanitize_query_value(value: str) -> str:
    """
    Sanitize a value for use in LanceDB queries to prevent injection.

    Args:
        value: The value to sanitize

    Returns:
        The sanitized value

    Raises:
        ValueError: If value contains unsafe characters
    """
    if not value:
        return value

    if not SAFE_QUERY_PATTERN.match(value):
        raise ValueError(
            f"Query value contains unsafe characters: {value[:50]}... "
            "Only alphanumeric, underscore, hyphen, and dot allowed."
        )

    return value


logger = logging.getLogger(__name__)

# Embedding dimension for simple text hashing (we'll use a basic approach)
# For production, you'd use sentence-transformers or OpenAI embeddings
EMBEDDING_DIM = 384


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
    Persistent incident memory using LanceDB.

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
        Initialize LanceDB with persistence.

        Args:
            persist_directory: Directory to store LanceDB data.
                              Defaults to 'data/incident_memory'
            table_name: Name of the LanceDB table.
                       Defaults to 'incidents'

        Raises:
            ImportError: If lancedb is not installed
        """
        if not LANCEDB_AVAILABLE:
            raise ImportError(
                "lancedb is required for incident memory. " "Install it with: pip install lancedb"
            )

        self.persist_directory = persist_directory or os.getenv(
            "INCIDENT_MEMORY_PATH", self.DEFAULT_PERSIST_DIR
        )
        self.table_name = table_name

        # Create persist directory if it doesn't exist
        os.makedirs(self.persist_directory, exist_ok=True)

        # Initialize LanceDB
        self.db = lancedb.connect(self.persist_directory)

        # Check if table exists, create if not
        existing_tables = self.db.table_names()
        if self.table_name in existing_tables:
            self.table = self.db.open_table(self.table_name)
            count = self.table.count_rows()
        else:
            # Create empty table with schema
            self.table = None
            count = 0

        logger.info(
            f"Incident memory initialized: {count} incidents stored "
            f"(persist_dir={self.persist_directory})"
        )

    def _ensure_table(self, data: list[dict]) -> None:
        """Ensure table exists, create with data if needed."""
        if self.table is None:
            self.table = self.db.create_table(self.table_name, data)
        else:
            self.table.add(data)

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

        # Prepare record
        record = {
            "id": incident_id,
            "service": service,
            "namespace": namespace,
            "cluster": cluster,
            "error_type": error_type,
            "severity": severity,
            "confidence": confidence,
            "resolution_outcome": resolution_outcome,
            "root_cause": root_cause[:500] if root_cause else "",
            "remediation_steps": "|".join(remediation_steps),
            "llm_model": llm_model,
            "timestamp": timestamp,
            "document_text": document_text,
            "vector": embedding,
            "time_to_resolution_minutes": time_to_resolution_minutes or -1,
        }

        # Store in LanceDB
        self._ensure_table([record])

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
        1. Filter by error_type (deterministic, reduces noise)
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
        if self.table is None or self.table.count_rows() == 0:
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
            # Search with vector similarity
            # Filter by error_type if specified (with sanitization to prevent injection)
            if error_type and error_type.lower() != "unknown":
                try:
                    sanitized_error_type = _sanitize_query_value(error_type)
                    results = (
                        self.table.search(query_embedding)
                        .where(f"error_type = '{sanitized_error_type}'", prefilter=True)
                        .limit(limit * 2)
                        .to_list()
                    )
                except ValueError as ve:
                    logger.warning(
                        f"Invalid error_type for filtering: {ve}, searching without filter"
                    )
                    results = self.table.search(query_embedding).limit(limit * 2).to_list()
            else:
                results = self.table.search(query_embedding).limit(limit * 2).to_list()
        except Exception as e:
            logger.debug(f"Filtered search failed ({e}), trying without filter")
            try:
                results = self.table.search(query_embedding).limit(limit * 2).to_list()
            except Exception as e2:
                logger.error(f"Similarity search failed: {e2}")
                return []

        similar_incidents = []

        for row in results:
            # LanceDB returns _distance (L2 distance)
            distance = row.get("_distance", 2.0)

            # Convert distance to similarity (0-1)
            # L2 distance for normalized vectors: 0 = identical, 2 = opposite
            similarity = max(0.0, 1.0 - (distance / 2.0))

            if similarity < min_similarity:
                continue

            # Boost score for matching namespace or service
            match_reasons = []

            if row.get("namespace") == namespace:
                similarity = min(1.0, similarity + 0.1)
                match_reasons.append("same namespace")

            if row.get("service") == service:
                similarity = min(1.0, similarity + 0.1)
                match_reasons.append("same service")

            if row.get("error_type") == error_type:
                match_reasons.append(f"same error type ({error_type})")
            else:
                match_reasons.append(f"similar to {row.get('error_type', 'unknown')}")

            # Parse remediation steps back to list
            remediation_str = row.get("remediation_steps", "")
            remediation_steps = remediation_str.split("|") if remediation_str else []

            # Parse TTR
            ttr = row.get("time_to_resolution_minutes")
            if ttr is not None and ttr < 0:
                ttr = None

            # Create StoredIncident
            stored_incident = StoredIncident(
                id=row.get("id", ""),
                timestamp=datetime.fromisoformat(row.get("timestamp", datetime.now().isoformat())),
                service=row.get("service", ""),
                namespace=row.get("namespace", ""),
                cluster=row.get("cluster", ""),
                error_type=row.get("error_type", ""),
                summary=row.get("document_text", "")[:200],
                root_cause=row.get("root_cause", ""),
                remediation_steps=remediation_steps,
                resolution_outcome=row.get("resolution_outcome", "unknown"),
                time_to_resolution_minutes=ttr,
                severity=row.get("severity", "medium"),
                confidence=row.get("confidence", "medium"),
                llm_model=row.get("llm_model", "unknown"),
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
        if self.table is None:
            return None

        try:
            # Validate incident_id is a valid UUID to prevent injection
            try:
                uuid.UUID(incident_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid incident ID format: {incident_id[:50]}")
                return None

            results = self.table.search().where(f"id = '{incident_id}'").limit(1).to_list()

            if results:
                row = results[0]
                remediation_str = row.get("remediation_steps", "")
                remediation_steps = remediation_str.split("|") if remediation_str else []

                ttr = row.get("time_to_resolution_minutes")
                if ttr is not None and ttr < 0:
                    ttr = None

                return StoredIncident(
                    id=row.get("id", ""),
                    timestamp=datetime.fromisoformat(
                        row.get("timestamp", datetime.now().isoformat())
                    ),
                    service=row.get("service", ""),
                    namespace=row.get("namespace", ""),
                    cluster=row.get("cluster", ""),
                    error_type=row.get("error_type", ""),
                    summary=row.get("document_text", "")[:200],
                    root_cause=row.get("root_cause", ""),
                    remediation_steps=remediation_steps,
                    resolution_outcome=row.get("resolution_outcome", "unknown"),
                    time_to_resolution_minutes=ttr,
                    severity=row.get("severity", "medium"),
                    confidence=row.get("confidence", "medium"),
                    llm_model=row.get("llm_model", "unknown"),
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
        if self.table is None:
            return False

        try:
            # Validate incident_id is a valid UUID to prevent injection
            try:
                uuid.UUID(incident_id)
            except (ValueError, TypeError):
                logger.warning(f"Invalid incident ID format for deletion: {incident_id[:50]}")
                return False

            self.table.delete(f"id = '{incident_id}'")
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
        count = self.table.count_rows() if self.table else 0

        stats = {
            "total_incidents": count,
            "persist_directory": self.persist_directory,
            "table_name": self.table_name,
            "lancedb_available": LANCEDB_AVAILABLE,
        }

        # Get breakdown by error type if we have incidents
        if count > 0 and self.table:
            try:
                # Get all records for distribution
                all_records = self.table.search().limit(min(count, 100)).to_list()
                error_types = {}
                for row in all_records:
                    et = row.get("error_type", "unknown")
                    error_types[et] = error_types.get(et, 0) + 1
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
            if self.table_name in self.db.table_names():
                self.db.drop_table(self.table_name)
            self.table = None
            logger.warning("Incident memory has been reset (all incidents deleted)")
            return True
        except Exception as e:
            logger.error(f"Failed to reset incident memory: {e}")
            return False
