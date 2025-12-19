#!/usr/bin/env python3
"""
Run memory quality audit with proper environment setup
"""
import os
import sys
import json

# Add src to path
sys.path.insert(0, 'src')

# Load environment from .env file manually
env_file = '.env'
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Verify API key is loaded
if not os.getenv("MEM0_API_KEY"):
    print("❌ MEM0_API_KEY not found in environment")
    print("Please ensure .env file exists with MEM0_API_KEY set")
    sys.exit(1)

# Import after environment is loaded
from utils.memory_metrics import MemoryMetrics

print("🔍 Running Memory Quality Audit...\n")
print("=" * 60)

try:
    metrics = MemoryMetrics()
    audit = metrics.audit_memory_quality()

    print("\n📊 Memory Statistics:")
    print(f"   Total Memories: {audit['stats']['total_memories']}")
    print(f"   Category Breakdown:")
    for category, count in audit['stats']['category_breakdown'].items():
        print(f"     - {category}: {count}")

    print(f"\n⚠️  Quality Issues:")
    print(f"   Duplicates Found: {audit['quality_issues']['duplicate_count']}")
    print(f"   Stale Memories: {audit['quality_issues']['stale_count']}")

    if audit['quality_issues']['duplicate_count'] > 0:
        print(f"\n   Top Duplicates:")
        for dup in audit['quality_issues']['duplicates'][:3]:
            print(f"     - Similarity: {dup['similarity']:.2f}")
            print(f"       Memory 1: {dup['memory1_text']}...")
            print(f"       Memory 2: {dup['memory2_text']}...")

    if audit['quality_issues']['stale_count'] > 0:
        print(f"\n   Sample Stale Memories:")
        for stale in audit['quality_issues']['stale_sample'][:3]:
            print(f"     - Age: {stale['age_days']} days")
            print(f"       Content: {stale['memory']}...")

    print(f"\n💡 Recommendations:")
    for rec in audit['recommendations']:
        print(f"   {rec}")

    print("\n" + "=" * 60)
    print("✅ Audit Complete!")

    # Also save full audit to file
    with open('memory_audit_latest.json', 'w') as f:
        json.dump(audit, f, indent=2, default=str)
    print("\n📄 Full audit saved to: memory_audit_latest.json")

except Exception as e:
    print(f"\n❌ Error running audit: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
