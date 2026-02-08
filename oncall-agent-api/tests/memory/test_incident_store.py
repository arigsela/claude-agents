"""
Tests for IncidentMemoryStore (sqlite-vec-based storage)
"""

import pytest
import tempfile
import shutil
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.incident_store import IncidentMemoryStore, simple_text_embedding, EMBEDDING_DIM, SQLITE_VEC_AVAILABLE
from src.memory.models import StoredIncident, SimilarIncident

pytestmark = pytest.mark.skipif(
    not SQLITE_VEC_AVAILABLE,
    reason="sqlite-vec not installed"
)


@pytest.fixture
def temp_memory_dir():
    """Create a temporary directory for test database"""
    temp_dir = tempfile.mkdtemp(prefix="incident_memory_test_")
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def memory_store(temp_memory_dir):
    """Create an IncidentMemoryStore instance for testing"""
    return IncidentMemoryStore(persist_directory=temp_memory_dir)


class TestSimpleTextEmbedding:
    """Tests for the simple_text_embedding function"""

    def test_embedding_dimension(self):
        """Test that embedding has correct dimension"""
        text = "Test text for embedding"
        embedding = simple_text_embedding(text)
        assert len(embedding) == EMBEDDING_DIM

    def test_embedding_normalized(self):
        """Test that embedding is normalized (magnitude ≈ 1)"""
        text = "Test text for embedding normalization"
        embedding = simple_text_embedding(text)
        magnitude = sum(x * x for x in embedding) ** 0.5
        assert abs(magnitude - 1.0) < 0.01  # Close to 1

    def test_similar_texts_similar_embeddings(self):
        """Test that similar texts produce similar embeddings"""
        text1 = "OOMKilled in proteus-api pod"
        text2 = "OOMKilled in proteus-api container"
        text3 = "Network timeout in artemis service"

        emb1 = simple_text_embedding(text1)
        emb2 = simple_text_embedding(text2)
        emb3 = simple_text_embedding(text3)

        # Calculate cosine similarity
        def cosine_sim(a, b):
            return sum(x * y for x, y in zip(a, b))

        sim_1_2 = cosine_sim(emb1, emb2)
        sim_1_3 = cosine_sim(emb1, emb3)

        # Similar texts should have higher similarity
        assert sim_1_2 > sim_1_3

    def test_empty_text(self):
        """Test handling of empty text"""
        embedding = simple_text_embedding("")
        assert len(embedding) == EMBEDDING_DIM
        # All zeros after normalization of zero vector
        assert all(x == 0.0 for x in embedding)


class TestIncidentMemoryStore:
    """Tests for IncidentMemoryStore"""

    def test_initialization(self, memory_store):
        """Test that store initializes correctly"""
        assert memory_store is not None
        assert memory_store.conn is not None

    def test_store_incident(self, memory_store):
        """Test storing an incident"""
        incident_id = memory_store.store_incident(
            service="proteus-api",
            namespace="proteus-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Memory limit too low for batch processing",
            remediation_steps=["Increase memory limit", "Add memory request"],
            severity="high",
            confidence="high"
        )

        assert incident_id is not None
        assert len(incident_id) == 36  # UUID format

    def test_store_incident_minimal(self, memory_store):
        """Test storing incident with minimal required fields"""
        incident_id = memory_store.store_incident(
            service="test-service",
            namespace="test-ns",
            cluster="test-cluster",
            error_type="TestError",
            root_cause="Test root cause",
            remediation_steps=["Step 1"],
            severity="low"
        )

        assert incident_id is not None

    def test_get_incident(self, memory_store):
        """Test retrieving an incident by ID"""
        # Store an incident
        incident_id = memory_store.store_incident(
            service="proteus-api",
            namespace="proteus-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Memory limit too low",
            remediation_steps=["Increase memory"],
            severity="high"
        )

        # Retrieve it
        incident = memory_store.get_incident(incident_id)

        assert incident is not None
        assert incident.id == incident_id
        assert incident.service == "proteus-api"
        assert incident.namespace == "proteus-dev"
        assert incident.error_type == "OOMKilled"
        assert incident.severity == "high"

    def test_get_nonexistent_incident(self, memory_store):
        """Test retrieving non-existent incident"""
        incident = memory_store.get_incident("nonexistent-uuid-1234")
        assert incident is None

    def test_delete_incident(self, memory_store):
        """Test deleting an incident"""
        # Store an incident
        incident_id = memory_store.store_incident(
            service="delete-test",
            namespace="test-ns",
            cluster="dev-eks",
            error_type="TestError",
            root_cause="Test cause",
            remediation_steps=["Step"],
            severity="low"
        )

        # Verify it exists
        assert memory_store.get_incident(incident_id) is not None

        # Delete it
        deleted = memory_store.delete_incident(incident_id)
        assert deleted is True

        # Verify it's gone
        assert memory_store.get_incident(incident_id) is None

    def test_delete_nonexistent_incident(self, memory_store):
        """Test deleting non-existent incident"""
        # This should not raise an error
        deleted = memory_store.delete_incident("nonexistent-uuid")
        # sqlite-vec returns False for non-existent IDs
        assert deleted is False

    def test_find_similar_exact_match(self, memory_store):
        """Test finding similar incidents with exact error type match"""
        # Store test incidents
        memory_store.store_incident(
            service="proteus-api",
            namespace="proteus-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Memory limit too low",
            remediation_steps=["Increase memory"],
            severity="high"
        )

        memory_store.store_incident(
            service="artemis-app",
            namespace="artemis-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Report query used too much memory",
            remediation_steps=["Optimize query"],
            severity="medium"
        )

        # Search for similar
        similar = memory_store.find_similar(
            service="proteus-api",
            namespace="proteus-dev",
            error_type="OOMKilled",
            limit=5
        )

        assert len(similar) == 2
        # Same service/namespace should rank higher
        assert similar[0].incident.service == "proteus-api"
        assert similar[0].similarity_score > similar[1].similarity_score

    def test_find_similar_with_error_filter(self, memory_store):
        """Test that error_type filter works correctly"""
        # Store different error types
        memory_store.store_incident(
            service="test-service",
            namespace="test-ns",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="OOM cause",
            remediation_steps=["OOM fix"],
            severity="high"
        )

        memory_store.store_incident(
            service="test-service",
            namespace="test-ns",
            cluster="dev-eks",
            error_type="CrashLoopBackOff",
            root_cause="Crash cause",
            remediation_steps=["Crash fix"],
            severity="high"
        )

        # Search for OOMKilled only
        similar = memory_store.find_similar(
            service="test-service",
            namespace="test-ns",
            error_type="OOMKilled",
            limit=5
        )

        # Should only find OOMKilled incident
        assert len(similar) == 1
        assert similar[0].incident.error_type == "OOMKilled"

    def test_find_similar_empty_store(self, memory_store):
        """Test searching empty store"""
        similar = memory_store.find_similar(
            service="any",
            namespace="any",
            error_type="OOMKilled"
        )

        assert similar == []

    def test_find_similar_match_reasons(self, memory_store):
        """Test that match_reasons are populated correctly"""
        memory_store.store_incident(
            service="proteus-api",
            namespace="proteus-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Test cause",
            remediation_steps=["Test step"],
            severity="high"
        )

        similar = memory_store.find_similar(
            service="proteus-api",
            namespace="proteus-dev",
            error_type="OOMKilled"
        )

        assert len(similar) == 1
        reasons = similar[0].match_reasons

        assert "same service" in reasons
        assert "same namespace" in reasons
        assert "same error type (OOMKilled)" in reasons

    def test_find_similar_min_similarity(self, memory_store):
        """Test minimum similarity threshold"""
        memory_store.store_incident(
            service="completely-different",
            namespace="different-ns",
            cluster="other-cluster",
            error_type="OOMKilled",
            root_cause="Different cause",
            remediation_steps=["Different step"],
            severity="low"
        )

        # Search with high similarity threshold
        similar = memory_store.find_similar(
            service="proteus-api",
            namespace="proteus-dev",
            error_type="OOMKilled",
            min_similarity=0.9  # Very high threshold
        )

        # Should not find the different incident
        assert len(similar) == 0

    def test_get_stats(self, memory_store):
        """Test getting store statistics"""
        # Initially empty
        stats = memory_store.get_stats()
        assert stats["total_incidents"] == 0

        # Add some incidents
        memory_store.store_incident(
            service="service1",
            namespace="ns1",
            cluster="dev-eks",
            error_type="OOMKilled",
            root_cause="Cause 1",
            remediation_steps=["Step 1"],
            severity="high"
        )

        memory_store.store_incident(
            service="service2",
            namespace="ns2",
            cluster="dev-eks",
            error_type="CrashLoopBackOff",
            root_cause="Cause 2",
            remediation_steps=["Step 2"],
            severity="medium"
        )

        stats = memory_store.get_stats()
        assert stats["total_incidents"] == 2
        assert "error_type_distribution" in stats
        assert stats["error_type_distribution"].get("OOMKilled") == 1
        assert stats["error_type_distribution"].get("CrashLoopBackOff") == 1

    def test_reset(self, memory_store):
        """Test resetting the store"""
        # Add some incidents
        memory_store.store_incident(
            service="test",
            namespace="test",
            cluster="dev-eks",
            error_type="Test",
            root_cause="Test",
            remediation_steps=["Test"],
            severity="low"
        )

        stats = memory_store.get_stats()
        assert stats["total_incidents"] == 1

        # Reset
        success = memory_store.reset()
        assert success is True

        # Verify empty
        stats = memory_store.get_stats()
        assert stats["total_incidents"] == 0


class TestStoredIncidentModel:
    """Tests for StoredIncident Pydantic model"""

    def test_create_stored_incident(self):
        """Test creating a StoredIncident"""
        incident = StoredIncident(
            id="test-uuid-1234",
            timestamp=datetime.now(),
            service="proteus-api",
            namespace="proteus-dev",
            cluster="dev-eks",
            error_type="OOMKilled",
            summary="Pod killed due to OOM",
            root_cause="Memory limit too low",
            remediation_steps=["Increase memory"],
            severity="high"
        )

        assert incident.service == "proteus-api"
        assert incident.error_type == "OOMKilled"
        assert len(incident.remediation_steps) == 1

    def test_stored_incident_defaults(self):
        """Test StoredIncident default values"""
        incident = StoredIncident(
            id="test-uuid",
            timestamp=datetime.now(),
            service="test",
            namespace="test",
            cluster="test",
            error_type="test",
            summary="test",
            root_cause="test"
        )

        assert incident.resolution_outcome == "resolved"
        assert incident.severity == "medium"
        assert incident.confidence == "medium"
        assert incident.llm_model == "unknown"
        assert incident.remediation_steps == []


class TestSimilarIncidentModel:
    """Tests for SimilarIncident Pydantic model"""

    def test_create_similar_incident(self):
        """Test creating a SimilarIncident"""
        stored = StoredIncident(
            id="test-uuid",
            timestamp=datetime.now(),
            service="test",
            namespace="test",
            cluster="test",
            error_type="test",
            summary="test",
            root_cause="test"
        )

        similar = SimilarIncident(
            incident=stored,
            similarity_score=0.85,
            match_reasons=["same service", "same namespace"]
        )

        assert similar.similarity_score == 0.85
        assert len(similar.match_reasons) == 2

    def test_similarity_score_bounds(self):
        """Test that similarity score is bounded 0-1"""
        stored = StoredIncident(
            id="test",
            timestamp=datetime.now(),
            service="test",
            namespace="test",
            cluster="test",
            error_type="test",
            summary="test",
            root_cause="test"
        )

        # Valid score
        similar = SimilarIncident(
            incident=stored,
            similarity_score=0.5,
            match_reasons=[]
        )
        assert similar.similarity_score == 0.5

        # Score at boundaries
        similar_min = SimilarIncident(
            incident=stored,
            similarity_score=0.0,
            match_reasons=[]
        )
        assert similar_min.similarity_score == 0.0

        similar_max = SimilarIncident(
            incident=stored,
            similarity_score=1.0,
            match_reasons=[]
        )
        assert similar_max.similarity_score == 1.0
