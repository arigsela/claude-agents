"""
Tests for Pydantic models
"""

import pytest
from pydantic import ValidationError
from datetime import datetime
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.models import (
    QueryRequest,
    IncidentRequest,
    SessionRequest,
    QueryResponse,
    IncidentResponse,
    ErrorResponse,
    ResponseMessage
)


class TestQueryRequest:
    """Tests for QueryRequest model"""

    def test_valid_query_request(self):
        """Test valid query request"""
        request = QueryRequest(
            prompt="What services are running?",
            namespace="proteus-dev",
            context={"user": "test"}
        )
        assert request.prompt == "What services are running?"
        assert request.namespace == "proteus-dev"
        assert request.context == {"user": "test"}

    def test_query_request_defaults(self):
        """Test default values"""
        request = QueryRequest(prompt="Test query")
        assert request.namespace == "default"
        assert request.context == {}
        assert request.session_id is None

    def test_prompt_too_long(self):
        """Test prompt length validation"""
        with pytest.raises(ValidationError):
            QueryRequest(prompt="x" * 10001)  # Max is 10000

    def test_prompt_empty(self):
        """Test empty prompt validation"""
        with pytest.raises(ValidationError):
            QueryRequest(prompt="")


class TestIncidentRequest:
    """Tests for IncidentRequest model"""

    def test_valid_incident_request(self):
        """Test valid incident request"""
        request = IncidentRequest(
            service="proteus",
            namespace="proteus-dev",
            error="CrashLoopBackOff",
            pod="proteus-api-123",
            restart_count=5,
            cluster="dev-eks"
        )
        assert request.service == "proteus"
        assert request.namespace == "proteus-dev"
        assert request.restart_count == 5

    def test_incident_request_defaults(self):
        """Test default values"""
        request = IncidentRequest(
            service="test",
            error="Error"
        )
        assert request.namespace == "default"
        assert request.restart_count == 0
        assert request.cluster == "dev-eks"

    def test_cluster_validation_invalid(self):
        """Test cluster validation rejects prod-eks"""
        with pytest.raises(ValidationError) as exc_info:
            IncidentRequest(
                service="test",
                error="Error",
                cluster="prod-eks"
            )
        assert "Only" in str(exc_info.value)
        assert "dev-eks" in str(exc_info.value)

    def test_cluster_validation_valid(self):
        """Test cluster validation accepts dev-eks"""
        request = IncidentRequest(
            service="test",
            error="Error",
            cluster="dev-eks"
        )
        assert request.cluster == "dev-eks"

    def test_negative_restart_count(self):
        """Test restart count cannot be negative"""
        with pytest.raises(ValidationError):
            IncidentRequest(
                service="test",
                error="Error",
                restart_count=-1
            )


class TestSessionRequest:
    """Tests for SessionRequest model"""

    def test_valid_session_request(self):
        """Test valid session request"""
        request = SessionRequest(
            user_id="user@example.com",
            metadata={"team": "devops"}
        )
        assert request.user_id == "user@example.com"
        assert request.metadata == {"team": "devops"}

    def test_session_request_defaults(self):
        """Test default values"""
        request = SessionRequest(user_id="user@example.com")
        assert request.metadata == {}


class TestResponseModels:
    """Tests for response models"""

    def test_response_message(self):
        """Test ResponseMessage model"""
        msg = ResponseMessage(
            type="text",
            content="Test content"
        )
        assert msg.type == "text"
        assert msg.content == "Test content"

    def test_query_response(self):
        """Test QueryResponse model"""
        response = QueryResponse(
            status="success",
            responses=[
                ResponseMessage(type="text", content="Response 1")
            ],
            query="Test query",
            duration_ms=123.45
        )
        assert response.status == "success"
        assert len(response.responses) == 1
        assert response.duration_ms == 123.45
        assert isinstance(response.timestamp, datetime)

    def test_incident_response(self):
        """Test IncidentResponse model"""
        response = IncidentResponse(
            status="analyzed",
            alert={"service": "test"},
            analysis=[
                ResponseMessage(type="text", content="Analysis")
            ],
            severity="high",
            duration_ms=456.78
        )
        assert response.status == "analyzed"
        assert response.severity == "high"
        assert len(response.analysis) == 1

    def test_error_response(self):
        """Test ErrorResponse model"""
        error = ErrorResponse(
            error="ValidationError",
            message="Invalid input",
            detail="Field X is required"
        )
        assert error.status == "error"
        assert error.error == "ValidationError"
        assert error.message == "Invalid input"
        assert error.detail == "Field X is required"
