"""
Tests for input validation utilities.

Tests RFC 1123 validation for Kubernetes resource names and query sanitization.
"""

import pytest

from src.api.validation import (
    validate_k8s_name,
    validate_k8s_namespace,
    validate_k8s_pod_name,
    sanitize_query_value,
    K8S_LABEL_MAX_LENGTH,
    K8S_DNS_MAX_LENGTH,
)


class TestK8sNameValidation:
    """Tests for RFC 1123 Kubernetes name validation."""

    def test_valid_simple_name(self):
        """Valid simple name should pass."""
        assert validate_k8s_name("my-service") == "my-service"

    def test_valid_name_with_numbers(self):
        """Valid name with numbers should pass."""
        assert validate_k8s_name("my-service-123") == "my-service-123"

    def test_valid_single_character(self):
        """Single character name should pass."""
        assert validate_k8s_name("a") == "a"

    def test_valid_single_number(self):
        """Single number name should pass."""
        assert validate_k8s_name("1") == "1"

    def test_invalid_uppercase(self):
        """Uppercase characters should fail."""
        with pytest.raises(ValueError, match="must be lowercase"):
            validate_k8s_name("MyService")

    def test_invalid_starts_with_hyphen(self):
        """Name starting with hyphen should fail."""
        with pytest.raises(ValueError, match="must be lowercase alphanumeric"):
            validate_k8s_name("-my-service")

    def test_invalid_ends_with_hyphen(self):
        """Name ending with hyphen should fail."""
        with pytest.raises(ValueError, match="must be lowercase alphanumeric"):
            validate_k8s_name("my-service-")

    def test_invalid_contains_underscore(self):
        """Name containing underscore should fail."""
        with pytest.raises(ValueError, match="must be lowercase alphanumeric"):
            validate_k8s_name("my_service")

    def test_invalid_contains_dot(self):
        """Name containing dot should fail."""
        with pytest.raises(ValueError, match="must be lowercase alphanumeric"):
            validate_k8s_name("my.service")

    def test_invalid_empty(self):
        """Empty name should fail."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_k8s_name("")

    def test_invalid_too_long(self):
        """Name exceeding max length should fail."""
        long_name = "a" * (K8S_LABEL_MAX_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            validate_k8s_name(long_name)

    def test_valid_max_length(self):
        """Name at exactly max length should pass."""
        name = "a" * K8S_LABEL_MAX_LENGTH
        assert validate_k8s_name(name) == name


class TestK8sNamespaceValidation:
    """Tests for Kubernetes namespace validation."""

    def test_valid_namespace(self):
        """Valid namespace should pass."""
        assert validate_k8s_namespace("proteus-dev") == "proteus-dev"

    def test_valid_namespace_default(self):
        """Default namespace should pass."""
        assert validate_k8s_namespace("default") == "default"

    def test_valid_namespace_with_numbers(self):
        """Namespace with numbers should pass."""
        assert validate_k8s_namespace("artemis-preprod") == "artemis-preprod"

    def test_invalid_namespace_uppercase(self):
        """Uppercase namespace should fail."""
        with pytest.raises(ValueError):
            validate_k8s_namespace("Proteus-Dev")


class TestK8sPodNameValidation:
    """Tests for Kubernetes pod name validation."""

    def test_valid_pod_name(self):
        """Valid pod name should pass."""
        assert validate_k8s_pod_name("proteus-api-7b9c8d6f4-xyz12") == "proteus-api-7b9c8d6f4-xyz12"

    def test_valid_pod_name_simple(self):
        """Simple pod name should pass."""
        assert validate_k8s_pod_name("my-pod") == "my-pod"

    def test_invalid_pod_name_empty(self):
        """Empty pod name should fail."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_k8s_pod_name("")

    def test_invalid_pod_name_uppercase(self):
        """Uppercase pod name should fail."""
        with pytest.raises(ValueError):
            validate_k8s_pod_name("MyPod")

    def test_invalid_pod_name_too_long(self):
        """Pod name exceeding DNS max length should fail."""
        long_name = "a" * (K8S_DNS_MAX_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            validate_k8s_pod_name(long_name)


class TestQuerySanitization:
    """Tests for LanceDB query value sanitization."""

    def test_valid_simple_value(self):
        """Simple alphanumeric value should pass."""
        assert sanitize_query_value("OOMKilled") == "OOMKilled"

    def test_valid_value_with_hyphen(self):
        """Value with hyphen should pass."""
        assert sanitize_query_value("crash-loop") == "crash-loop"

    def test_valid_value_with_underscore(self):
        """Value with underscore should pass."""
        assert sanitize_query_value("oom_killed") == "oom_killed"

    def test_valid_value_with_dot(self):
        """Value with dot should pass."""
        assert sanitize_query_value("error.type") == "error.type"

    def test_valid_empty_value(self):
        """Empty value should pass (returns as-is)."""
        assert sanitize_query_value("") == ""

    def test_invalid_single_quote(self):
        """Value with single quote should fail (injection risk)."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value("test'injection")

    def test_invalid_double_quote(self):
        """Value with double quote should fail."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value('test"injection')

    def test_invalid_semicolon(self):
        """Value with semicolon should fail."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value("test;drop")

    def test_invalid_space(self):
        """Value with space should fail."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value("test value")

    def test_invalid_equals(self):
        """Value with equals sign should fail."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value("test=value")

    def test_invalid_sql_injection_attempt(self):
        """SQL injection attempt should fail."""
        with pytest.raises(ValueError, match="unsafe characters"):
            sanitize_query_value("'; DROP TABLE incidents; --")


class TestModelValidation:
    """Tests for validation in Pydantic models."""

    def test_query_request_valid_namespace(self):
        """QueryRequest with valid namespace should work."""
        from src.api.models import QueryRequest

        request = QueryRequest(prompt="test", namespace="proteus-dev")
        assert request.namespace == "proteus-dev"

    def test_query_request_invalid_namespace(self):
        """QueryRequest with invalid namespace should fail."""
        from src.api.models import QueryRequest

        with pytest.raises(ValueError):
            QueryRequest(prompt="test", namespace="Invalid-Namespace")

    def test_incident_request_valid_namespace_and_pod(self):
        """IncidentRequest with valid namespace and pod should work."""
        from src.api.models import IncidentRequest

        request = IncidentRequest(
            service="proteus",
            namespace="proteus-dev",
            error="CrashLoopBackOff",
            pod="proteus-api-abc123"
        )
        assert request.namespace == "proteus-dev"
        assert request.pod == "proteus-api-abc123"

    def test_incident_request_invalid_namespace(self):
        """IncidentRequest with invalid namespace should fail."""
        from src.api.models import IncidentRequest

        with pytest.raises(ValueError):
            IncidentRequest(
                service="proteus",
                namespace="INVALID",
                error="CrashLoopBackOff"
            )

    def test_incident_request_invalid_pod(self):
        """IncidentRequest with invalid pod name should fail."""
        from src.api.models import IncidentRequest

        with pytest.raises(ValueError):
            IncidentRequest(
                service="proteus",
                namespace="proteus-dev",
                error="CrashLoopBackOff",
                pod="Invalid_Pod_Name"
            )
