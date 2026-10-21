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
    ResponseMessage,
    ImageTagResponse
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


class TestImageTagResponse:
    """Tests for ImageTagResponse model (DEVOPS-7737)"""

    def test_valid_image_tag_response(self):
        """Test valid ImageTagResponse with all fields"""
        response = ImageTagResponse(
            service_name="hermes",
            deployment_name="hermesapp",
            namespace="artemis-dev",
            container_name="app",
            current_image_url="docker.io/artemishealth/hermes:v1.2.3",
            pod_count=3
        )
        assert response.service_name == "hermes"
        assert response.deployment_name == "hermesapp"
        assert response.namespace == "artemis-dev"
        assert response.container_name == "app"
        assert response.current_image_url == "docker.io/artemishealth/hermes:v1.2.3"
        assert response.pod_count == 3
        assert isinstance(response.timestamp, datetime)

    def test_image_tag_response_timestamp_default(self):
        """Test that timestamp defaults to current time"""
        before = datetime.utcnow()
        response = ImageTagResponse(
            service_name="proteus",
            deployment_name="proteus",
            namespace="proteus-dev",
            container_name="main",
            current_image_url="ecr.aws/artemis/proteus:latest",
            pod_count=2
        )
        after = datetime.utcnow()
        assert before <= response.timestamp <= after

    def test_image_tag_response_pod_count_zero(self):
        """Test pod_count can be zero (deployment scaled down)"""
        response = ImageTagResponse(
            service_name="test-service",
            deployment_name="test-deploy",
            namespace="test-ns",
            container_name="app",
            current_image_url="nginx:latest",
            pod_count=0
        )
        assert response.pod_count == 0

    def test_image_tag_response_negative_pod_count_rejected(self):
        """Test that negative pod_count is rejected"""
        with pytest.raises(ValidationError):
            ImageTagResponse(
                service_name="test",
                deployment_name="test",
                namespace="test",
                container_name="app",
                current_image_url="nginx:latest",
                pod_count=-1
            )

    def test_image_tag_response_serialization(self):
        """Test ImageTagResponse serializes to JSON correctly"""
        response = ImageTagResponse(
            service_name="zeus",
            deployment_name="zeus",
            namespace="zeus-dev",
            container_name="zeus-app",
            current_image_url="docker.io/artemishealth/zeus:v2.0.0",
            pod_count=5
        )
        data = response.model_dump()
        assert data["service_name"] == "zeus"
        assert data["deployment_name"] == "zeus"
        assert data["namespace"] == "zeus-dev"
        assert data["container_name"] == "zeus-app"
        assert data["current_image_url"] == "docker.io/artemishealth/zeus:v2.0.0"
        assert data["pod_count"] == 5
        assert "timestamp" in data

    def test_image_tag_response_json_schema(self):
        """Test ImageTagResponse has correct JSON schema for OpenAPI"""
        schema = ImageTagResponse.model_json_schema()
        assert "properties" in schema
        required_fields = ["service_name", "deployment_name", "namespace",
                          "container_name", "current_image_url", "pod_count"]
        for field in required_fields:
            assert field in schema["properties"]
