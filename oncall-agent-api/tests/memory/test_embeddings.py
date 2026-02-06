"""
Tests for incident embeddings module
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.embeddings import create_incident_text, create_query_text, extract_key_terms


class TestCreateIncidentText:
    """Tests for create_incident_text function"""

    def test_basic_incident(self):
        """Test creating text from basic incident data"""
        incident = {
            "service": "proteus-api",
            "namespace": "proteus-dev",
            "error_type": "OOMKilled",
            "root_cause": "Memory limit too low"
        }

        text = create_incident_text(incident)

        assert "Service: proteus-api" in text
        assert "Namespace: proteus-dev" in text
        assert "Error Type: OOMKilled" in text
        assert "Root Cause: Memory limit too low" in text

    def test_incident_with_cluster(self):
        """Test including cluster in text"""
        incident = {
            "service": "test",
            "namespace": "test",
            "cluster": "dev-eks",
            "error_type": "Test"
        }

        text = create_incident_text(incident)

        assert "Cluster: dev-eks" in text

    def test_incident_with_error_message(self):
        """Test including error message"""
        incident = {
            "service": "test",
            "namespace": "test",
            "error_type": "OOMKilled",
            "error_message": "Container exceeded memory limit"
        }

        text = create_incident_text(incident)

        assert "Error Message: Container exceeded memory limit" in text

    def test_incident_with_summary(self):
        """Test including summary"""
        incident = {
            "service": "test",
            "namespace": "test",
            "error_type": "Test",
            "summary": "Pod was killed due to memory issues"
        }

        text = create_incident_text(incident)

        assert "Summary: Pod was killed due to memory issues" in text

    def test_incident_with_remediation_steps_list(self):
        """Test including remediation steps as list"""
        incident = {
            "service": "test",
            "namespace": "test",
            "error_type": "Test",
            "remediation_steps": ["Increase memory", "Add requests", "Monitor usage"]
        }

        text = create_incident_text(incident)

        assert "Resolution:" in text
        assert "Increase memory" in text
        assert "Add requests" in text
        assert "Monitor usage" in text

    def test_incident_with_remediation_steps_string(self):
        """Test handling remediation steps as string"""
        incident = {
            "service": "test",
            "namespace": "test",
            "error_type": "Test",
            "remediation_steps": "Single step as string"
        }

        text = create_incident_text(incident)

        assert "Resolution: Single step as string" in text

    def test_incident_missing_fields(self):
        """Test handling missing optional fields"""
        incident = {}

        text = create_incident_text(incident)

        assert "Service: unknown" in text
        assert "Namespace: unknown" in text
        assert "Error Type: unknown" in text


class TestCreateQueryText:
    """Tests for create_query_text function"""

    def test_basic_query(self):
        """Test creating basic query text"""
        text = create_query_text(
            service="proteus-api",
            namespace="proteus-dev",
            error_type="OOMKilled"
        )

        assert "Service: proteus-api" in text
        assert "Namespace: proteus-dev" in text
        assert "Error Type: OOMKilled" in text

    def test_query_with_error_message(self):
        """Test query with error message"""
        text = create_query_text(
            service="test",
            namespace="test",
            error_type="OOMKilled",
            error_message="Container killed: OOM"
        )

        assert "Error Message: Container killed: OOM" in text

    def test_query_with_additional_context(self):
        """Test query with additional context"""
        text = create_query_text(
            service="test",
            namespace="test",
            error_type="Test",
            additional_context="Recent deployment at 2pm"
        )

        assert "Context: Recent deployment at 2pm" in text

    def test_query_without_optional_fields(self):
        """Test query without optional fields"""
        text = create_query_text(
            service="test",
            namespace="test",
            error_type="Test"
        )

        assert "Error Message" not in text
        assert "Context" not in text


class TestExtractKeyTerms:
    """Tests for extract_key_terms function"""

    def test_extract_oomkilled(self):
        """Test extracting OOMKilled term"""
        text = "Pod was OOMKilled due to memory issues"
        terms = extract_key_terms(text)

        assert "oomkilled" in terms
        assert "memory" in terms

    def test_extract_crashloopbackoff(self):
        """Test extracting CrashLoopBackOff term"""
        text = "Container in CrashLoopBackOff state"
        terms = extract_key_terms(text)

        assert "crashloopbackoff" in terms

    def test_extract_imagepullbackoff(self):
        """Test extracting ImagePullBackOff term"""
        text = "Pod stuck in ImagePullBackOff"
        terms = extract_key_terms(text)

        assert "imagepullbackoff" in terms

    def test_extract_multiple_terms(self):
        """Test extracting multiple terms"""
        text = "OOMKilled due to memory leak, connection refused to database"
        terms = extract_key_terms(text)

        assert "oomkilled" in terms
        assert "memory" in terms
        assert "connection refused" in terms

    def test_extract_resource_terms(self):
        """Test extracting resource-related terms"""
        text = "CPU throttling and disk pressure detected"
        terms = extract_key_terms(text)

        assert "cpu" in terms
        assert "disk" in terms

    def test_extract_k8s_resource_terms(self):
        """Test extracting K8s resource terms"""
        text = "Secret not found, ConfigMap missing"
        terms = extract_key_terms(text)

        assert "secret" in terms
        assert "configmap" in terms

    def test_extract_permission_terms(self):
        """Test extracting permission terms"""
        text = "RBAC permission denied"
        terms = extract_key_terms(text)

        assert "permission" in terms
        assert "rbac" in terms

    def test_no_matching_terms(self):
        """Test with no matching terms"""
        text = "Everything is working fine"
        terms = extract_key_terms(text)

        assert terms == []

    def test_case_insensitive(self):
        """Test case insensitivity"""
        text = "OOMKILLED and Memory LEAK"
        terms = extract_key_terms(text)

        assert "oomkilled" in terms
        assert "memory" in terms
