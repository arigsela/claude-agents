#!/usr/bin/env python3
"""
Quick test script to verify mem0 integration
Tests the memory manager operations without needing the full API server
"""
import os
import sys

# Add src to path
sys.path.insert(0, 'src')

# Set environment variables
os.environ['MEM0_API_KEY'] = 'm0-UWyVzqysJ2jJ7AMnskLwYUxRwY4S77kuopL2Wpj8'
os.environ['MEM0_ENABLED'] = 'true'
os.environ['MEM0_SEARCH_LIMIT'] = '5'

from memory.memory_manager import MemoryManager

def test_basic_operations():
    """Test basic mem0 operations"""
    print("🧪 Testing mem0 Integration\n")
    print("="*60)

    # Initialize memory manager
    print("\n1️⃣  Initializing MemoryManager...")
    memory = MemoryManager()
    print("✅ MemoryManager initialized\n")

    # Test 1: Store an API interaction
    print("2️⃣  Storing test API interaction...")
    memory.store_api_interaction(
        session_id="test-session-123",
        user_query="Why is proteus-dev pod crashing with OOMKilled?",
        agent_response="The pod is exceeding its memory limit of 512Mi. Actual usage is around 1.8Gi. Recommend increasing memory limit to 2Gi.",
        metadata={
            "cluster": "dev-eks",
            "namespace": "proteus-dev"
        }
    )
    print("✅ API interaction stored\n")

    # Test 2: Search for the interaction
    print("3️⃣  Searching for similar queries...")
    results = memory.search_session_memories(
        session_id="test-session-123",
        query="proteus memory issues",
        limit=5
    )
    print(f"✅ Found {len(results)} memories\n")

    if results:
        print("📋 Sample memory:")
        print(f"   - Memory: {results[0].get('memory', '')[:100]}...")
        print(f"   - Score: {results[0].get('score', 0):.2f}")
        print()

    # Test 3: Format memories as context
    print("4️⃣  Formatting memories as LLM context...")
    context = memory.format_memories_as_context(results)
    if context:
        print("✅ Context formatted")
        print(f"   Length: {len(context)} characters")
        print(f"   Preview: {context[:150]}...")
    else:
        print("ℹ️  No context (empty results)")

    print("\n" + "="*60)
    print("🎉 All tests passed!")
    print("\n💡 Next steps:")
    print("   1. Check mem0 dashboard: https://mem0.ai/dashboard")
    print("   2. Verify your memory appears in the dashboard")
    print("   3. Try querying the API: ./test_query.sh")
    print("="*60)

if __name__ == "__main__":
    try:
        test_basic_operations()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
