"""
Pydantic models for incident memory storage and retrieval.

Uses Pydantic v2 syntax.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StoredIncident(BaseModel):
    """
    An incident stored in memory for future retrieval.

    Contains all relevant information about a past incident including
    its root cause analysis and resolution steps.
    """

    # Unique identifier
    id: str = Field(..., description="UUID of the stored incident")
    timestamp: datetime = Field(..., description="When the incident was stored")

    # Identifiers (used for filtering)
    service: str = Field(..., description="Service name (e.g., 'proteus-api')")
    namespace: str = Field(..., description="Kubernetes namespace")
    cluster: str = Field(..., description="Cluster name (e.g., 'dev-eks')")
    error_type: str = Field(..., description="Error type (e.g., 'OOMKilled', 'CrashLoopBackOff')")

    # Content (used for embedding and display)
    summary: str = Field(..., description="Brief summary of the incident")
    root_cause: str = Field(..., description="Root cause analysis from LLM")

    # Resolution information
    remediation_steps: list[str] = Field(
        default_factory=list, description="Steps taken to resolve the incident"
    )
    resolution_outcome: str = Field(
        default="resolved", description="Outcome: 'resolved', 'escalated', 'recurring'"
    )
    time_to_resolution_minutes: int | None = Field(
        default=None, description="Time taken to resolve in minutes"
    )

    # Metadata
    severity: str = Field(
        default="medium", description="Incident severity: 'critical', 'high', 'medium', 'low'"
    )
    confidence: str = Field(
        default="medium", description="LLM confidence in analysis: 'high', 'medium', 'low'"
    )
    llm_model: str = Field(default="unknown", description="Which LLM model analyzed this incident")


class SimilarIncident(BaseModel):
    """
    A similar incident returned from similarity search.

    Wraps a StoredIncident with similarity score and match reasons.
    """

    incident: StoredIncident = Field(..., description="The matched incident")
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Similarity score from 0.0 to 1.0"
    )
    match_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons why this incident matched (e.g., 'same namespace', 'similar error')",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "incident": {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "timestamp": "2024-01-15T10:30:00Z",
                    "service": "proteus-api",
                    "namespace": "proteus-dev",
                    "cluster": "dev-eks",
                    "error_type": "OOMKilled",
                    "summary": "Pod killed due to memory limit",
                    "root_cause": "Memory limit too low for batch processing",
                    "remediation_steps": ["Increased memory from 512Mi to 1Gi"],
                    "resolution_outcome": "resolved",
                    "severity": "high",
                    "confidence": "high",
                    "llm_model": "claude-sonnet-4",
                },
                "similarity_score": 0.85,
                "match_reasons": ["same service", "same namespace", "similar OOMKilled"],
            }
        }
    )
