#!/usr/bin/env python3
"""
List all memories across all user_ids
"""
import os
import sys

# Add src to path
sys.path.insert(0, 'src')

# Load environment
env_file = '.env'
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

from memory.mem0_client import Mem0ClientWrapper

print("📋 Fetching all memories...\n")

client = Mem0ClientWrapper()

# Try different user_ids
user_ids = [
    "oncall-daemon",
    "api-session-test-session-123",
    "test-user"
]

for user_id in user_ids:
    print(f"\n🔍 Searching memories for user_id: {user_id}")
    memories = client.get_all_memories(user_id=user_id, agent_id="oncall-troubleshooter")
    print(f"   Found: {len(memories)} memories")

    if memories:
        for i, mem in enumerate(memories[:3], 1):
            print(f"\n   Memory {i}:")
            print(f"     ID: {mem.get('id', 'N/A')}")
            print(f"     Memory: {mem.get('memory', 'N/A')[:100]}...")
            print(f"     Categories: {mem.get('categories', [])}")
            print(f"     Created: {mem.get('created_at', 'N/A')}")
