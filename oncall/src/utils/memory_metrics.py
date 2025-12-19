"""
Track memory usage and quality metrics
"""
import logging
import sys
import os
from typing import Dict, List
from datetime import datetime, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class MemoryMetrics:
    """Track memory operations and quality"""

    def __init__(self):
        self.memory = MemoryManager()

    def get_memory_stats(self) -> Dict:
        """Get overall memory statistics"""
        daemon_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon",
            agent_id="oncall-troubleshooter"
        )

        # Count by category
        category_counts = {}
        for mem in daemon_memories:
            cats = mem.get("categories", [])
            for cat in cats:
                category_counts[cat] = category_counts.get(cat, 0) + 1

        # Get timestamps if available
        timestamps = [m.get("created_at") for m in daemon_memories if m.get("created_at")]

        return {
            "total_memories": len(daemon_memories),
            "category_breakdown": category_counts,
            "oldest_memory": min(timestamps) if timestamps else None,
            "newest_memory": max(timestamps) if timestamps else None
        }

    def find_duplicate_memories(self, threshold: float = 0.95) -> List[Dict]:
        """Find near-duplicate memories that should be merged"""
        all_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon"
        )

        duplicates = []

        for i, mem1 in enumerate(all_memories):
            for mem2 in all_memories[i+1:]:
                # Simple similarity check (you could use embeddings for better accuracy)
                mem1_text = mem1.get("memory", "")
                mem2_text = mem2.get("memory", "")

                # Jaccard similarity
                words1 = set(mem1_text.lower().split())
                words2 = set(mem2_text.lower().split())

                if not words1 or not words2:
                    continue

                similarity = len(words1 & words2) / len(words1 | words2)

                if similarity >= threshold:
                    duplicates.append({
                        "memory1_id": mem1["id"],
                        "memory2_id": mem2["id"],
                        "similarity": similarity,
                        "memory1_text": mem1_text[:100],
                        "memory2_text": mem2_text[:100]
                    })

        return duplicates

    def find_stale_memories(self, days: int = 90) -> List[Dict]:
        """Find memories older than threshold that might be outdated"""
        all_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon"
        )

        cutoff_date = datetime.now() - timedelta(days=days)
        stale = []

        for mem in all_memories:
            created_at_str = mem.get("created_at", "")
            if not created_at_str:
                continue

            try:
                # Handle both ISO format with and without 'Z'
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))

                # Make cutoff_date timezone-aware if created_at is timezone-aware
                if created_at.tzinfo is not None:
                    from datetime import timezone
                    cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)

                if created_at < cutoff_date:
                    stale.append({
                        "id": mem["id"],
                        "memory": mem.get("memory", "")[:100],
                        "age_days": (datetime.now().replace(tzinfo=timezone.utc if created_at.tzinfo else None) - created_at).days,
                        "categories": mem.get("categories", [])
                    })
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse created_at for memory {mem.get('id')}: {e}")
                continue

        return stale

    def audit_memory_quality(self) -> Dict:
        """Run full memory quality audit"""
        stats = self.get_memory_stats()
        duplicates = self.find_duplicate_memories()
        stale = self.find_stale_memories()

        return {
            "stats": stats,
            "quality_issues": {
                "duplicate_count": len(duplicates),
                "duplicates": duplicates[:10],  # Top 10
                "stale_count": len(stale),
                "stale_sample": stale[:10]
            },
            "recommendations": self._generate_recommendations(stats, duplicates, stale)
        }

    def _generate_recommendations(
        self,
        stats: Dict,
        duplicates: List,
        stale: List
    ) -> List[str]:
        """Generate recommendations based on audit"""
        recommendations = []

        if stats["total_memories"] > 1000:
            recommendations.append(
                f"⚠️ High memory count ({stats['total_memories']}). "
                "Consider pruning old memories or adjusting expiration."
            )

        if len(duplicates) > 10:
            recommendations.append(
                f"⚠️ Found {len(duplicates)} duplicate memories. "
                "Review custom_instructions to improve filtering."
            )

        if len(stale) > 50:
            recommendations.append(
                f"⚠️ {len(stale)} memories older than 90 days. "
                "Consider deleting outdated incident memories."
            )

        if not recommendations:
            recommendations.append("✅ Memory quality looks good!")

        return recommendations


# CLI command for manual audits
if __name__ == "__main__":
    import json
    import sys

    # Add src to path
    sys.path.insert(0, 'src')

    metrics = MemoryMetrics()
    audit = metrics.audit_memory_quality()

    print(json.dumps(audit, indent=2, default=str))
