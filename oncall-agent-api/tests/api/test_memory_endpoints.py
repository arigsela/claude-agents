"""
Integration tests for memory API endpoints
"""

import pytest
import tempfile
import shutil
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.api_server import app
from src.api.memory import get_memory_store


@pytest.fixture(scope="module")
def temp_memory_dir():
    """Create a temporary directory for test database"""
    temp_dir = tempfile.mkdtemp(prefix="memory_api_test_")
    yield temp_dir
    # Cleanup after all tests in module
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def test_client(temp_memory_dir):
    """Create a test client with isolated memory store"""
    # Override the memory store dependency with a test instance
    from src.memory.incident_store import IncidentMemoryStore

    test_store = IncidentMemoryStore(persist_directory=temp_memory_dir)

    def override_get_memory_store():
        return test_store

    app.dependency_overrides[get_memory_store] = override_get_memory_store

    client = TestClient(app)
    yield client

    # Clear overrides after tests
    app.dependency_overrides.clear()


@pytest.fixture
def stored_incident(test_client):
    """Store a test incident and return its ID"""
    response = test_client.post(
        "/memory/store",
        json={
            "service": "proteus-api",
            "namespace": "proteus-dev",
            "cluster": "dev-eks",
            "error_type": "OOMKilled",
            "root_cause": "Memory limit too low for batch processing",
            "remediation_steps": ["Increase memory limit to 2Gi", "Add memory request"],
            "severity": "high",
            "confidence": "high"
        }
    )
    assert response.status_code == 200
    return response.json()["incident_id"]


class TestMemoryHealthEndpoint:
    """Tests for /memory/health endpoint"""

    def test_health_check(self, test_client):
        """Test memory health endpoint returns OK"""
        response = test_client.get("/memory/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "total_incidents" in data
        assert "persist_directory" in data


class TestMemoryStatsEndpoint:
    """Tests for /memory/stats endpoint"""

    def test_get_stats_empty(self, test_client):
        """Test getting stats from empty store"""
        # Reset the store first
        test_client.post("/memory/reset?confirm=true")

        response = test_client.get("/memory/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_incidents"] == 0
        assert "error_type_distribution" in data

    def test_get_stats_with_incidents(self, test_client, stored_incident):
        """Test getting stats with incidents"""
        response = test_client.get("/memory/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_incidents"] >= 1
        assert "OOMKilled" in data.get("error_type_distribution", {})


class TestMemoryStoreEndpoint:
    """Tests for /memory/store endpoint"""

    def test_store_incident_full(self, test_client):
        """Test storing incident with all fields"""
        response = test_client.post(
            "/memory/store",
            json={
                "service": "artemis-app",
                "namespace": "artemis-dev",
                "cluster": "dev-eks",
                "error_type": "CrashLoopBackOff",
                "root_cause": "Missing environment variable",
                "remediation_steps": ["Add CONFIG_PATH env var", "Restart deployment"],
                "severity": "high",
                "confidence": "medium",
                "resolution_outcome": "resolved"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "incident_id" in data
        assert len(data["incident_id"]) == 36  # UUID format

    def test_store_incident_minimal(self, test_client):
        """Test storing incident with minimal required fields"""
        response = test_client.post(
            "/memory/store",
            json={
                "service": "test-service",
                "namespace": "test-ns",
                "cluster": "test-cluster",
                "error_type": "TestError",
                "root_cause": "Test root cause",
                "remediation_steps": ["Step 1"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "incident_id" in data

    def test_store_incident_invalid_json(self, test_client):
        """Test storing incident with invalid JSON"""
        response = test_client.post(
            "/memory/store",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 422  # Validation error

    def test_store_incident_missing_required_fields(self, test_client):
        """Test storing incident with missing required fields"""
        response = test_client.post(
            "/memory/store",
            json={
                "service": "test-service"
                # Missing other required fields
            }
        )

        assert response.status_code == 422  # Validation error


class TestMemoryGetIncidentEndpoint:
    """Tests for /memory/incident/{incident_id} GET endpoint"""

    def test_get_incident_by_id(self, test_client, stored_incident):
        """Test retrieving incident by ID"""
        response = test_client.get(f"/memory/incident/{stored_incident}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["incident"]["id"] == stored_incident
        assert data["incident"]["service"] == "proteus-api"
        assert data["incident"]["namespace"] == "proteus-dev"
        assert data["incident"]["error_type"] == "OOMKilled"

    def test_get_nonexistent_incident(self, test_client):
        """Test retrieving non-existent incident"""
        response = test_client.get("/memory/incident/nonexistent-uuid-12345")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestMemoryDeleteIncidentEndpoint:
    """Tests for /memory/incident/{incident_id} DELETE endpoint"""

    def test_delete_incident(self, test_client):
        """Test deleting an incident"""
        # First store an incident
        store_response = test_client.post(
            "/memory/store",
            json={
                "service": "delete-test",
                "namespace": "test-ns",
                "cluster": "dev-eks",
                "error_type": "TestError",
                "root_cause": "To be deleted",
                "remediation_steps": ["Step"]
            }
        )
        incident_id = store_response.json()["incident_id"]

        # Delete it
        delete_response = test_client.delete(f"/memory/incident/{incident_id}")

        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        # Verify it's gone
        get_response = test_client.get(f"/memory/incident/{incident_id}")
        assert get_response.status_code == 404

    def test_delete_nonexistent_incident(self, test_client):
        """Test deleting non-existent incident"""
        response = test_client.delete("/memory/incident/nonexistent-uuid")

        # LanceDB delete is idempotent - returns success even for non-existent IDs
        # This is expected behavior for idempotent delete operations
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"


class TestMemorySearchEndpoint:
    """Tests for /memory/search endpoint"""

    def test_search_similar_incidents(self, test_client):
        """Test searching for similar incidents"""
        # Store a few test incidents
        test_client.post("/memory/reset?confirm=true")

        # Store OOMKilled incidents
        test_client.post(
            "/memory/store",
            json={
                "service": "proteus-api",
                "namespace": "proteus-dev",
                "cluster": "dev-eks",
                "error_type": "OOMKilled",
                "root_cause": "Memory limit too low",
                "remediation_steps": ["Increase memory"]
            }
        )

        test_client.post(
            "/memory/store",
            json={
                "service": "artemis-app",
                "namespace": "artemis-dev",
                "cluster": "dev-eks",
                "error_type": "OOMKilled",
                "root_cause": "Large query result",
                "remediation_steps": ["Optimize query"]
            }
        )

        # Search for similar
        response = test_client.post(
            "/memory/search",
            json={
                "service": "proteus-api",
                "namespace": "proteus-dev",
                "error_type": "OOMKilled",
                "limit": 5
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 2
        # Same service should rank higher
        assert data["results"][0]["service"] == "proteus-api"

    def test_search_with_error_message(self, test_client):
        """Test search with error message context"""
        response = test_client.post(
            "/memory/search",
            json={
                "service": "test-service",
                "namespace": "test-ns",
                "error_type": "OOMKilled",
                "error_message": "Container killed: OOM limit exceeded",
                "limit": 3
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "query" in data

    def test_search_empty_results(self, test_client):
        """Test search with no matching results"""
        test_client.post("/memory/reset?confirm=true")

        response = test_client.post(
            "/memory/search",
            json={
                "service": "nonexistent",
                "namespace": "nonexistent",
                "error_type": "UnknownError"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []

    def test_search_with_min_similarity(self, test_client):
        """Test search with minimum similarity threshold"""
        response = test_client.post(
            "/memory/search",
            json={
                "service": "test",
                "namespace": "test",
                "error_type": "OOMKilled",
                "min_similarity": 0.95  # Very high threshold
            }
        )

        assert response.status_code == 200
        # High threshold likely filters out all results
        data = response.json()
        assert "results" in data

    def test_search_missing_required_fields(self, test_client):
        """Test search with missing required fields"""
        response = test_client.post(
            "/memory/search",
            json={
                "service": "test"
                # Missing namespace and error_type
            }
        )

        assert response.status_code == 422


class TestMemoryResetEndpoint:
    """Tests for /memory/reset endpoint"""

    def test_reset_without_confirmation(self, test_client):
        """Test reset without confirmation fails"""
        response = test_client.post("/memory/reset")

        assert response.status_code == 400
        assert "confirm=true" in response.json()["detail"]

    def test_reset_with_confirmation(self, test_client):
        """Test reset with confirmation clears all data"""
        # Store an incident first
        test_client.post(
            "/memory/store",
            json={
                "service": "reset-test",
                "namespace": "test-ns",
                "cluster": "dev-eks",
                "error_type": "TestError",
                "root_cause": "Test",
                "remediation_steps": ["Step"]
            }
        )

        # Verify incident exists
        stats = test_client.get("/memory/stats").json()
        assert stats["total_incidents"] >= 1

        # Reset
        response = test_client.post("/memory/reset?confirm=true")

        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Verify empty
        stats = test_client.get("/memory/stats").json()
        assert stats["total_incidents"] == 0


class TestSimilarIncidentResponse:
    """Tests for similar incident response format"""

    def test_similar_incident_structure(self, test_client):
        """Test that similar incident response has correct structure"""
        test_client.post("/memory/reset?confirm=true")

        # Store an incident
        test_client.post(
            "/memory/store",
            json={
                "service": "proteus-api",
                "namespace": "proteus-dev",
                "cluster": "dev-eks",
                "error_type": "OOMKilled",
                "root_cause": "Low memory limit",
                "remediation_steps": ["Increase limit"],
                "severity": "high"
            }
        )

        # Search for it
        response = test_client.post(
            "/memory/search",
            json={
                "service": "proteus-api",
                "namespace": "proteus-dev",
                "error_type": "OOMKilled"
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["results"]) == 1
        result = data["results"][0]

        # Check structure
        assert "id" in result
        assert "service" in result
        assert "namespace" in result
        assert "error_type" in result
        assert "root_cause" in result
        assert "remediation_steps" in result
        assert "similarity_score" in result
        assert "match_reasons" in result
        assert "timestamp" in result

        # Check match reasons
        assert "same service" in result["match_reasons"]
        assert "same namespace" in result["match_reasons"]
        assert "same error type (OOMKilled)" in result["match_reasons"]
