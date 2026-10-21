"""
Incident Memory Module

Provides vector similarity search for finding similar past incidents.
Uses ChromaDB with SQLite persistence for storing and retrieving incidents.

Usage:
    from memory import IncidentMemoryStore

    store = IncidentMemoryStore()

    # Store a resolved incident
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

from .incident_store import IncidentMemoryStore
from .models import SimilarIncident, StoredIncident

__all__ = ["IncidentMemoryStore", "StoredIncident", "SimilarIncident"]
