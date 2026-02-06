"""
Input validation utilities for Kubernetes resource names.

Provides RFC 1123 compliant validation for namespace, pod, and service names.
Keep validation simple - regex patterns only, no over-engineering.
"""

import re

# RFC 1123 DNS label pattern for Kubernetes names
# Must: start/end with alphanumeric, contain only lowercase alphanumeric and hyphens
# Length: 1-63 characters for labels, 1-253 for full DNS names
K8S_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

# Maximum lengths per Kubernetes spec
K8S_LABEL_MAX_LENGTH = 63  # Single label (e.g., namespace name)
K8S_DNS_MAX_LENGTH = 253  # Full DNS name (e.g., pod name)

# Pattern for sanitizing LanceDB query values (allow only safe characters)
SAFE_QUERY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def validate_k8s_name(name: str, max_length: int = K8S_LABEL_MAX_LENGTH) -> str:
    """
    Validate a Kubernetes resource name against RFC 1123.

    Args:
        name: The name to validate
        max_length: Maximum allowed length (default 63 for labels)

    Returns:
        The validated name (unchanged if valid)

    Raises:
        ValueError: If name is invalid
    """
    if not name:
        raise ValueError("Kubernetes name cannot be empty")

    if len(name) > max_length:
        raise ValueError(f"Kubernetes name too long: {len(name)} > {max_length}")

    if not K8S_NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid Kubernetes name '{name}': must be lowercase alphanumeric "
            "with hyphens, starting and ending with alphanumeric"
        )

    return name


def validate_k8s_namespace(namespace: str) -> str:
    """
    Validate a Kubernetes namespace name.

    Args:
        namespace: The namespace name to validate

    Returns:
        The validated namespace name

    Raises:
        ValueError: If namespace is invalid
    """
    return validate_k8s_name(namespace, K8S_LABEL_MAX_LENGTH)


def validate_k8s_pod_name(pod_name: str) -> str:
    """
    Validate a Kubernetes pod name.

    Pod names can be longer (up to 253 chars) but each segment must be valid.

    Args:
        pod_name: The pod name to validate

    Returns:
        The validated pod name

    Raises:
        ValueError: If pod name is invalid
    """
    if not pod_name:
        raise ValueError("Pod name cannot be empty")

    if len(pod_name) > K8S_DNS_MAX_LENGTH:
        raise ValueError(f"Pod name too long: {len(pod_name)} > {K8S_DNS_MAX_LENGTH}")

    # Pod names follow same pattern as labels
    if not K8S_NAME_PATTERN.match(pod_name):
        raise ValueError(
            f"Invalid pod name '{pod_name}': must be lowercase alphanumeric "
            "with hyphens, starting and ending with alphanumeric"
        )

    return pod_name


def sanitize_query_value(value: str, field_name: str = "value") -> str:
    """
    Sanitize a value for use in LanceDB queries.

    Prevents injection by only allowing safe characters.

    Args:
        value: The value to sanitize
        field_name: Name of the field (for error messages)

    Returns:
        The sanitized value

    Raises:
        ValueError: If value contains unsafe characters
    """
    if not value:
        return value

    if not SAFE_QUERY_PATTERN.match(value):
        raise ValueError(
            f"Invalid {field_name}: contains unsafe characters. "
            "Only alphanumeric, underscore, hyphen, and dot allowed."
        )

    return value
