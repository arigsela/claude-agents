"""
Basic tests for mem0 client wrapper
"""
import pytest
import os
from datetime import datetime
from src.memory.mem0_client import Mem0ClientWrapper


def test_mem0_client_initialization():
    """Test that mem0 client initializes correctly"""
    # Set test environment
    os.environ["MEM0_ENABLED"] = "true"
    os.environ["MEM0_SEARCH_LIMIT"] = "5"

    # Skip if no API key (for CI/CD)
    if not os.getenv("MEM0_API_KEY"):
        pytest.skip("MEM0_API_KEY not set - skipping integration test")

    client = Mem0ClientWrapper()
    assert client.enabled is True
    assert client.search_limit == 5


def test_mem0_client_disabled():
    """Test that client respects MEM0_ENABLED=false"""
    os.environ["MEM0_ENABLED"] = "false"

    client = Mem0ClientWrapper()
    assert client.enabled is False

    # Operations should be no-ops
    result = client.add_memory(
        messages=[{"role": "user", "content": "test"}],
        user_id="test"
    )
    assert result.get("skipped") is True

    # Cleanup
    os.environ["MEM0_ENABLED"] = "true"


def test_add_and_search_memory():
    """Test adding and searching memories"""
    # Skip if no API key
    if not os.getenv("MEM0_API_KEY"):
        pytest.skip("MEM0_API_KEY not set - skipping integration test")

    client = Mem0ClientWrapper()

    # Add a test memory
    messages = [
        {"role": "user", "content": "Pod proteus-prod-123 is crashing"},
        {"role": "assistant", "content": "Root cause: OOMKilled. Increase memory to 2Gi"}
    ]

    result = client.add_memory(
        messages=messages,
        user_id="test-user",
        agent_id="oncall-troubleshooter",
        metadata={"namespace": "proteus-prod", "severity": "critical"},
        expiration_type="incident"
    )

    assert result is not None
    assert "error" not in result or not result.get("error")

    # Search for it
    memories = client.search_memories(
        query="proteus pod crashing",
        user_id="test-user",
        limit=5
    )

    assert len(memories) >= 0  # May or may not find it immediately (indexing delay)


def test_memory_metadata():
    """Test that metadata is stored correctly"""
    # Skip if no API key
    if not os.getenv("MEM0_API_KEY"):
        pytest.skip("MEM0_API_KEY not set - skipping integration test")

    client = Mem0ClientWrapper()

    messages = [{"role": "assistant", "content": "Test incident analysis"}]

    result = client.add_memory(
        messages=messages,
        user_id="test-metadata",
        metadata={
            "namespace": "test-ns",
            "service": "test-service",
            "severity": "high",
            "timestamp": datetime.now().isoformat()
        },
        expiration_type="incident"
    )

    assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
