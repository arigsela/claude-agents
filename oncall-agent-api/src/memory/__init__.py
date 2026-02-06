"""
Incident Memory Module

Provides vector similarity search for finding similar past incidents.
Uses ChromaDB with SQLite persistence for storing and retrieving incidents.

Usage:
    from memory import IncidentMemoryStore

    store = IncidentMemoryStore()

    # Store a resolved incident
    store.store_incident(
        service="proteus-api",
        namespace="proteus-dev",
        cluster="dev-eks",
        error_type="OOMKilled",
        root_cause="Memory limit too low",
        remediation_steps=["Increase memory to 1Gi"],
        severity="high"
    )

    # Find similar incidents
    similar = store.find_similar(
        service="proteus-api",
        namespace="proteus-dev",
        error_type="OOMKilled"
    )
"""

from .incident_store import IncidentMemoryStore
from .models import SimilarIncident, StoredIncident

__all__ = ["IncidentMemoryStore", "StoredIncident", "SimilarIncident"]
