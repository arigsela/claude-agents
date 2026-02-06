"""
Memory API endpoints for incident memory management.

Provides REST API access to the incident memory store for:
- Viewing memory statistics
- Searching for similar incidents
- Manually storing incidents
- Managing memory (reset)
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# Import memory module
try:
    from memory import IncidentMemoryStore

    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    IncidentMemoryStore = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["Incident Memory"])

# Global memory store instance (singleton)
_memory_store: IncidentMemoryStore | None = None


def get_memory_store() -> IncidentMemoryStore:
    """Get or initialize the global memory store instance."""
    global _memory_store

    if not MEMORY_AVAILABLE:
        raise HTTPException(
            status_code=503, detail="Incident memory module not available. Install lancedb."
        )

    if _memory_store is None:
        try:
            _memory_store = IncidentMemoryStore()
            logger.info("Memory store initialized on first access")
        except Exception as e:
            logger.error(f"Failed to initialize memory store: {e}")
            raise HTTPException(
                status_code=503, detail=f"Failed to initialize memory store: {str(e)}"
            )

    return _memory_store


# Request/Response Models


class MemoryStatsResponse(BaseModel):
    """Response model for memory statistics."""

    status: str = "success"
    total_incidents: int
    persist_directory: str
    table_name: str
    error_type_distribution: dict[str, int] | None = None


class SimilarIncidentSearchRequest(BaseModel):
    """Request model for searching similar incidents."""

    service: str = Field(..., description="Service name (e.g., 'proteus-api')")
    namespace: str = Field(..., description="Kubernetes namespace")
    error_type: str = Field(..., description="Error type (e.g., 'OOMKilled')")
    error_message: str = Field(default="", description="Optional error message for better matching")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum results to return")
    min_similarity: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum similarity score"
    )


class SimilarIncidentResult(BaseModel):
    """Result item for similar incident search."""

    id: str
    service: str
    namespace: str
    cluster: str
    error_type: str
    root_cause: str
    remediation_steps: list[str]
    severity: str
    similarity_score: float
    match_reasons: list[str]
    timestamp: datetime


class SimilarIncidentSearchResponse(BaseModel):
    """Response model for similar incident search."""

    status: str = "success"
    query: dict[str, Any]
    results: list[SimilarIncidentResult]
    total_found: int


def _get_default_cluster() -> str:
    """Get default cluster from environment."""
    import os
    return os.getenv("K8S_CONTEXT", "dev-eks")


class StoreIncidentRequest(BaseModel):
    """Request model for storing a new incident."""

    service: str = Field(..., description="Service name")
    namespace: str = Field(..., description="Kubernetes namespace")
    cluster: str = Field(default_factory=_get_default_cluster, description="Cluster name")
    error_type: str = Field(..., description="Error type")
    root_cause: str = Field(..., description="Root cause analysis")
    remediation_steps: list[str] = Field(..., description="Steps taken to resolve")
    severity: str = Field(default="medium", description="Severity level")
    confidence: str = Field(default="medium", description="Analysis confidence")
    resolution_outcome: str = Field(default="resolved", description="Resolution outcome")


class StoreIncidentResponse(BaseModel):
    """Response model for storing an incident."""

    status: str = "success"
    incident_id: str
    message: str


class ResetMemoryResponse(BaseModel):
    """Response model for memory reset."""

    status: str
    message: str


# API Endpoints


@router.get("/health")
async def memory_health():
    """
    Health check for incident memory service.

    Returns availability status and basic stats.
    """
    if not MEMORY_AVAILABLE:
        return {"status": "unavailable", "message": "Memory module not installed"}

    try:
        store = get_memory_store()
        stats = store.get_stats()
        return {
            "status": "healthy",
            "total_incidents": stats["total_incidents"],
            "persist_directory": stats["persist_directory"],
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats():
    """
    Get incident memory statistics.

    Returns:
        Total incident count, storage location, and error type distribution.
    """
    store = get_memory_store()
    stats = store.get_stats()

    return MemoryStatsResponse(
        total_incidents=stats["total_incidents"],
        persist_directory=stats["persist_directory"],
        table_name=stats["table_name"],
        error_type_distribution=stats.get("error_type_distribution"),
    )


@router.post("/search", response_model=SimilarIncidentSearchResponse)
async def search_similar_incidents(request: SimilarIncidentSearchRequest):
    """
    Search for similar past incidents.

    Uses hybrid search combining:
    - Deterministic filter by error_type
    - Vector similarity on incident content
    - Score boosting for same namespace/service

    Args:
        request: Search parameters including service, namespace, error_type

    Returns:
        List of similar incidents with similarity scores and match reasons
    """
    store = get_memory_store()

    similar = store.find_similar(
        service=request.service,
        namespace=request.namespace,
        error_type=request.error_type,
        error_message=request.error_message,
        limit=request.limit,
        min_similarity=request.min_similarity,
    )

    results = []
    for sim in similar:
        incident = sim.incident
        results.append(
            SimilarIncidentResult(
                id=incident.id,
                service=incident.service,
                namespace=incident.namespace,
                cluster=incident.cluster,
                error_type=incident.error_type,
                root_cause=incident.root_cause,
                remediation_steps=incident.remediation_steps,
                severity=incident.severity,
                similarity_score=sim.similarity_score,
                match_reasons=sim.match_reasons,
                timestamp=incident.timestamp,
            )
        )

    return SimilarIncidentSearchResponse(
        query={
            "service": request.service,
            "namespace": request.namespace,
            "error_type": request.error_type,
        },
        results=results,
        total_found=len(results),
    )


@router.post("/store", response_model=StoreIncidentResponse)
async def store_incident(request: StoreIncidentRequest):
    """
    Manually store an incident in memory.

    Use this to add known incidents and their resolutions to the memory
    for future similarity matching.

    Args:
        request: Incident details including service, error, root cause, remediation

    Returns:
        Stored incident ID
    """
    store = get_memory_store()

    incident_id = store.store_incident(
        service=request.service,
        namespace=request.namespace,
        cluster=request.cluster,
        error_type=request.error_type,
        root_cause=request.root_cause,
        remediation_steps=request.remediation_steps,
        severity=request.severity,
        confidence=request.confidence,
        resolution_outcome=request.resolution_outcome,
    )

    logger.info(f"Incident stored via API: {incident_id[:8]}...")

    return StoreIncidentResponse(incident_id=incident_id, message="Incident stored successfully")


@router.get("/incident/{incident_id}")
async def get_incident(incident_id: str):
    """
    Retrieve a specific incident by ID.

    Args:
        incident_id: UUID of the incident

    Returns:
        Full incident details

    Raises:
        404 if incident not found
    """
    store = get_memory_store()
    incident = store.get_incident(incident_id)

    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident not found: {incident_id}")

    return {"status": "success", "incident": incident.model_dump()}


@router.delete("/incident/{incident_id}")
async def delete_incident(incident_id: str):
    """
    Delete a specific incident from memory.

    Args:
        incident_id: UUID of the incident to delete

    Returns:
        Success message

    Raises:
        404 if incident not found
    """
    store = get_memory_store()
    deleted = store.delete_incident(incident_id)

    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Incident not found or could not be deleted: {incident_id}"
        )

    logger.info(f"Incident deleted via API: {incident_id}")

    return {"status": "deleted", "incident_id": incident_id}


@router.post("/reset", response_model=ResetMemoryResponse)
async def reset_memory(
    confirm: bool = Query(
        default=False,
        description="Must be true to confirm reset. This permanently deletes all incidents.",
    )
):
    """
    Reset (clear) all incidents from memory.

    WARNING: This permanently deletes all stored incidents.
    Requires confirm=true query parameter.

    Args:
        confirm: Must be true to proceed with reset

    Returns:
        Success message
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Reset requires confirm=true query parameter. This action is irreversible.",
        )

    store = get_memory_store()
    success = store.reset()

    if success:
        logger.warning("Incident memory reset via API - all incidents deleted")
        return ResetMemoryResponse(
            status="success", message="Incident memory has been reset. All incidents deleted."
        )
    else:
        raise HTTPException(status_code=500, detail="Failed to reset incident memory")
