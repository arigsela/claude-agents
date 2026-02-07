"""
Embedding generation for incident text.

Uses ChromaDB's default embedding model (all-MiniLM-L6-v2) for simplicity.
This can be swapped to Anthropic/OpenAI embeddings later if needed for
better semantic understanding.

The key insight from Incident.io's approach is that pure vector similarity
isn't always sufficient - we combine it with deterministic filtering
(error_type, namespace) for better results.
"""

from typing import Any


def create_incident_text(incident: dict[str, Any]) -> str:
    """
    Create searchable text from incident data.

    Combines key fields into a single string optimized for embedding.
    The structure is designed to capture:
    - Identity (service, namespace)
    - Problem (error type, symptoms)
    - Solution (root cause, remediation)

    Args:
        incident: Dictionary containing incident data

    Returns:
        Combined text string for embedding

    Example:
        >>> incident = {
        ...     "service": "chores-tracker-backend",
        ...     "namespace": "chores-tracker-backend",
        ...     "error_type": "OOMKilled",
        ...     "root_cause": "Memory limit too low",
        ...     "remediation_steps": ["Increase memory"]
        ... }
        >>> text = create_incident_text(incident)
        >>> "chores-tracker-backend" in text
        True
    """
    parts = []

    # Identity section
    service = incident.get("service", "unknown")
    namespace = incident.get("namespace", "unknown")
    cluster = incident.get("cluster", "")

    parts.append(f"Service: {service}")
    parts.append(f"Namespace: {namespace}")
    if cluster:
        parts.append(f"Cluster: {cluster}")

    # Problem section
    error_type = incident.get("error_type", "unknown")
    error_message = incident.get("error_message", "")
    summary = incident.get("summary", "")

    parts.append(f"Error Type: {error_type}")
    if error_message:
        parts.append(f"Error Message: {error_message}")
    if summary:
        parts.append(f"Summary: {summary}")

    # Analysis section
    root_cause = incident.get("root_cause", "")
    if root_cause:
        parts.append(f"Root Cause: {root_cause}")

    # Resolution section
    steps = incident.get("remediation_steps", [])
    if steps:
        steps_text = "; ".join(steps) if isinstance(steps, list) else str(steps)
        parts.append(f"Resolution: {steps_text}")

    return "\n".join(parts)


def create_query_text(
    service: str,
    namespace: str,
    error_type: str,
    error_message: str = "",
    additional_context: str = "",
) -> str:
    """
    Create query text for similarity search.

    Formats the current incident information into a query string
    that can be compared against stored incidents.

    Args:
        service: Service name
        namespace: Kubernetes namespace
        error_type: Type of error (e.g., 'OOMKilled')
        error_message: Optional error message text
        additional_context: Optional additional context

    Returns:
        Formatted query string for embedding
    """
    parts = [f"Service: {service}", f"Namespace: {namespace}", f"Error Type: {error_type}"]

    if error_message:
        parts.append(f"Error Message: {error_message}")

    if additional_context:
        parts.append(f"Context: {additional_context}")

    return "\n".join(parts)


def extract_key_terms(text: str) -> list[str]:
    """
    Extract key terms from incident text for keyword boosting.

    This is used in hybrid search to boost matches that share
    specific technical terms beyond just semantic similarity.

    Args:
        text: Incident text to analyze

    Returns:
        List of key terms
    """
    # Common Kubernetes error terms to look for
    k8s_terms = [
        "oomkilled",
        "crashloopbackoff",
        "imagepullbackoff",
        "pending",
        "evicted",
        "failed",
        "error",
        "timeout",
        "connection refused",
        "memory",
        "cpu",
        "disk",
        "secret",
        "configmap",
        "permission",
        "rbac",
    ]

    text_lower = text.lower()
    found_terms = []

    for term in k8s_terms:
        if term in text_lower:
            found_terms.append(term)

    return found_terms
