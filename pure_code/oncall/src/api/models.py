"""
Pydantic models for API request/response validation
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime


class QueryRequest(BaseModel):
    """Request model for /query endpoint"""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Query or instruction for the agent"
    )
    namespace: Optional[str] = Field(
        default="default",
        max_length=253,
        description="Kubernetes namespace context"
    )
    context: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Additional context for the query"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID for multi-turn conversations"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "What services are currently experiencing issues?",
                "namespace": "proteus-dev",
                "context": {
                    "user": "devops-team",
                    "source": "n8n-chat"
                }
            }
        }


class IncidentRequest(BaseModel):
    """Request model for /incident endpoint"""

    service: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Service name"
    )
    namespace: str = Field(
        default="default",
        max_length=253,
        description="Kubernetes namespace"
    )
    error: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Error message or description"
    )
    pod: Optional[str] = Field(
        default=None,
        max_length=253,
        description="Pod name"
    )
    restart_count: int = Field(
        default=0,
        ge=0,
        description="Number of pod restarts"
    )
    cluster: str = Field(
        default="dev-eks",
        description="Kubernetes cluster name"
    )

    @validator('cluster')
    def validate_cluster(cls, v):
        """Ensure only dev-eks cluster is allowed"""
        allowed_clusters = ['dev-eks']
        if v not in allowed_clusters:
            raise ValueError(f'Only {allowed_clusters} cluster(s) allowed. Got: {v}')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "service": "proteus",
                "namespace": "proteus-dev",
                "error": "CrashLoopBackOff",
                "pod": "proteus-api-7b9c8d6f4-xyz12",
                "restart_count": 5,
                "cluster": "dev-eks"
            }
        }


class SessionRequest(BaseModel):
    """Request model for session management"""

    user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="User identifier"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional metadata for the session"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "devops-user@artemishealth.com",
                "metadata": {
                    "source": "n8n-chat",
                    "team": "devops"
                }
            }
        }


class ResponseMessage(BaseModel):
    """Individual response message"""

    type: str = Field(..., description="Message type (text, tool_use, etc.)")
    content: str = Field(..., description="Message content")


class QueryResponse(BaseModel):
    """Response model for /query endpoint"""

    status: str = Field(..., description="Request status")
    session_id: Optional[str] = Field(None, description="Session ID if applicable")
    responses: List[ResponseMessage] = Field(
        ...,
        description="Agent response messages"
    )
    query: str = Field(..., description="Original query")
    duration_ms: Optional[float] = Field(
        None,
        description="Query processing duration in milliseconds"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Response timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "responses": [
                    {
                        "type": "text",
                        "content": "Currently monitoring 5 services in proteus-dev namespace..."
                    }
                ],
                "query": "What services are you monitoring?",
                "duration_ms": 1234.56,
                "timestamp": "2025-06-19T10:30:00Z"
            }
        }


class IncidentResponse(BaseModel):
    """Response model for /incident endpoint"""

    status: str = Field(..., description="Incident processing status")
    alert: Dict[str, Any] = Field(..., description="Original alert data")
    analysis: List[ResponseMessage] = Field(
        ...,
        description="Agent's incident analysis"
    )
    severity: Optional[str] = Field(
        None,
        description="Incident severity (critical, high, medium, low)"
    )
    duration_ms: Optional[float] = Field(
        None,
        description="Analysis duration in milliseconds"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Response timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "analyzed",
                "alert": {
                    "service": "proteus",
                    "namespace": "proteus-dev",
                    "error": "CrashLoopBackOff"
                },
                "analysis": [
                    {
                        "type": "text",
                        "content": "Detected CrashLoopBackOff in proteus service..."
                    }
                ],
                "severity": "high",
                "duration_ms": 3456.78,
                "timestamp": "2025-06-19T10:30:00Z"
            }
        }


class ErrorResponse(BaseModel):
    """Error response model"""

    status: str = Field(default="error", description="Status indicator")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Error timestamp"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "error",
                "error": "ValidationError",
                "message": "Invalid cluster specified",
                "detail": "Only dev-eks cluster is allowed",
                "timestamp": "2025-06-19T10:30:00Z"
            }
        }


class SessionResponse(BaseModel):
    """Response model for session operations"""

    status: str = Field(..., description="Operation status")
    session_id: str = Field(..., description="Session identifier")
    user_id: str = Field(..., description="User identifier")
    created_at: datetime = Field(..., description="Session creation time")
    last_accessed: Optional[datetime] = Field(
        None,
        description="Last access time"
    )
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Conversation history for the session"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "devops-user@artemishealth.com",
                "created_at": "2025-06-19T10:00:00Z",
                "last_accessed": "2025-06-19T10:30:00Z",
                "conversation_history": []
            }
        }
