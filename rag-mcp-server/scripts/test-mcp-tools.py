#!/usr/bin/env python3
"""Integration test for RAG MCP Server tools.

Tests the complete flow: store, search, list collections.
Requires Qdrant running at localhost:6333.
"""

import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools import (
    rag_store,
    rag_search,
    rag_list_collections,
    rag_collection_stats,
    rag_delete_collection,
)


async def test_rag_tools():
    """Run integration tests for RAG tools."""
    test_collection = "test-integration"

    print("=" * 60)
    print("RAG MCP Server Integration Test")
    print("=" * 60)

    # Test 1: List collections (initial state)
    print("\n[1/6] Testing rag_list_collections...")
    result = await rag_list_collections()
    assert result["success"], f"Failed: {result}"
    print(f"  ✅ Found {result['count']} collections: {result['collections']}")

    # Test 2: Store a document
    print("\n[2/6] Testing rag_store...")
    result = await rag_store(
        content="When a Kubernetes pod is in CrashLoopBackOff, check the logs with kubectl logs <pod-name>. Common causes include OOMKilled, missing environment variables, or failing health checks.",
        collection=test_collection,
        source="playbooks/k8s-troubleshooting.md",
        title="Kubernetes Pod Troubleshooting",
        metadata={"category": "kubernetes", "severity": "high"},
    )
    assert result["success"], f"Failed: {result}"
    assert result["created"], "Document should be created"
    print(f"  ✅ Stored document: id={result['id'][:8]}...")

    # Test 3: Store another document
    print("\n[3/6] Testing rag_store (second document)...")
    result = await rag_store(
        content="For OOMKilled errors, increase memory limits in the deployment spec. Check current usage with kubectl top pods.",
        collection=test_collection,
        source="playbooks/oom-errors.md",
        title="OOM Error Resolution",
    )
    assert result["success"], f"Failed: {result}"
    print(f"  ✅ Stored document: id={result['id'][:8]}...")

    # Test 4: Search for documents
    print("\n[4/6] Testing rag_search...")
    result = await rag_search(
        query="How do I fix OOMKilled pods?",
        collection=test_collection,
        limit=3,
    )
    assert result["success"], f"Failed: {result}"
    assert result["total_found"] > 0, "Should find at least one result"
    print(f"  ✅ Found {result['total_found']} results")
    for r in result["results"]:
        print(f"    - Score: {r['score']:.4f}, Source: {r['metadata']['source']}")

    # Test 5: Get collection stats
    print("\n[5/6] Testing rag_collection_stats...")
    result = await rag_collection_stats(collection=test_collection)
    assert result["success"], f"Failed: {result}"
    print(f"  ✅ Collection stats:")
    print(f"    - Points: {result['stats']['points_count']}")
    print(f"    - Vector size: {result['stats']['vector_size']}")
    print(f"    - Status: {result['stats']['status']}")

    # Test 6: Cleanup - delete test collection
    print("\n[6/6] Testing rag_delete_collection...")
    # First without confirm
    result = await rag_delete_collection(collection=test_collection)
    assert not result["success"], "Should fail without confirm"
    print(f"  ✅ Safety check works: {result['error'][:50]}...")

    # Now with confirm
    result = await rag_delete_collection(collection=test_collection, confirm=True)
    assert result["success"], f"Failed: {result}"
    print(f"  ✅ Deleted collection: {result['message']}")

    print("\n" + "=" * 60)
    print("All tests passed! ✅")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(test_rag_tools())
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
