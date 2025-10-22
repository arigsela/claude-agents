"""Test script to verify cycle memory functionality."""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

from src.utils.cycle_history import CycleHistory
from src.models import Finding

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_mock_cycle_report(
    cycle_id: str, findings: list[dict], status: str = "completed"
) -> dict:
    """Create a mock cycle report for testing."""
    return {
        "cycle_id": cycle_id,
        "cycle_number": 1,
        "status": status,
        "findings": findings,
        "escalation_decision": {
            "severity": "SEV-2",
            "should_notify": True,
        },
    }


def test_cycle_history():
    """Test cycle history loading and trend detection."""
    logger.info("=" * 80)
    logger.info("TESTING CYCLE HISTORY FUNCTIONALITY")
    logger.info("=" * 80)

    # Create test directory
    test_dir = Path("logs/test_cycles")
    test_dir.mkdir(parents=True, exist_ok=True)

    # Create mock cycle reports
    now = datetime.now()

    # Cycle 1: MySQL issue (2 hours ago)
    cycle1_time = now - timedelta(hours=2)
    cycle1 = create_mock_cycle_report(
        cycle_id=cycle1_time.strftime("%Y%m%d_%H%M%S"),
        findings=[
            {
                "service": "mysql",
                "severity": "P1",
                "description": "Pod in CrashLoopBackOff",
                "namespace": "mysql",
            }
        ],
    )
    cycle1_file = test_dir / f"cycle_{cycle1['cycle_id']}.json"
    with open(cycle1_file, "w") as f:
        json.dump(cycle1, f, indent=2)
    logger.info(f"✅ Created cycle 1: MySQL issue")

    # Cycle 2: MySQL + PostgreSQL issues (1 hour ago)
    cycle2_time = now - timedelta(hours=1)
    cycle2 = create_mock_cycle_report(
        cycle_id=cycle2_time.strftime("%Y%m%d_%H%M%S"),
        findings=[
            {
                "service": "mysql",
                "severity": "P1",
                "description": "Pod still in CrashLoopBackOff",
                "namespace": "mysql",
            },
            {
                "service": "postgresql",
                "severity": "P2",
                "description": "High memory usage",
                "namespace": "postgresql",
            },
        ],
    )
    cycle2_file = test_dir / f"cycle_{cycle2['cycle_id']}.json"
    with open(cycle2_file, "w") as f:
        json.dump(cycle2, f, indent=2)
    logger.info(f"✅ Created cycle 2: MySQL (recurring) + PostgreSQL (new)")

    # Cycle 3: Only PostgreSQL + Redis (30 min ago)
    cycle3_time = now - timedelta(minutes=30)
    cycle3 = create_mock_cycle_report(
        cycle_id=cycle3_time.strftime("%Y%m%d_%H%M%S"),
        findings=[
            {
                "service": "postgresql",
                "severity": "P2",
                "description": "Memory still high",
                "namespace": "postgresql",
            },
            {
                "service": "redis",
                "severity": "P3",
                "description": "Connection timeout",
                "namespace": "redis",
            },
        ],
    )
    cycle3_file = test_dir / f"cycle_{cycle3['cycle_id']}.json"
    with open(cycle3_file, "w") as f:
        json.dump(cycle3, f, indent=2)
    logger.info(f"✅ Created cycle 3: PostgreSQL (recurring) + Redis (new), MySQL resolved")

    # Initialize CycleHistory
    history = CycleHistory(history_dir=test_dir, max_history_cycles=5)

    # Test 1: Load recent cycles
    logger.info("\n" + "=" * 80)
    logger.info("TEST 1: Load Recent Cycles")
    logger.info("=" * 80)
    recent_cycles = history.load_recent_cycles()
    logger.info(f"✅ Loaded {len(recent_cycles)} cycles")
    assert len(recent_cycles) == 3, f"Expected 3 cycles, got {len(recent_cycles)}"

    # Test 2: Format history summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Format History Summary")
    logger.info("=" * 80)
    summary = history.format_history_summary(recent_cycles)
    logger.info(f"\n{summary}\n")
    assert "Cycle 1" in summary
    assert "Cycle 2" in summary
    assert "Cycle 3" in summary

    # Test 3: Detect recurring issues
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: Detect Recurring Issues")
    logger.info("=" * 80)

    # Current findings: MongoDB (new), PostgreSQL (recurring)
    current_findings = [
        Finding(
            service="mongodb",
            severity="critical",
            description="New database issue",
            namespace="mongodb",
        ),
        Finding(
            service="postgresql",
            severity="high",
            description="Still having issues",
            namespace="postgresql",
        ),
    ]

    analysis = history.detect_recurring_issues(current_findings, recent_cycles)

    logger.info(f"🆕 New Issues: {analysis['new_issues']}")
    logger.info(f"🔁 Recurring Issues: {analysis['recurring_issues']}")
    logger.info(f"✅ Resolved Issues: {analysis['resolved_issues']}")
    logger.info(f"⚠️ Worsening Trends: {analysis['worsening_trends']}")

    # Assertions
    assert "mongodb" in analysis["new_issues"], "MongoDB should be a new issue"
    assert "postgresql" in analysis["recurring_issues"], "PostgreSQL should be recurring"
    assert "mysql" in analysis["resolved_issues"], "MySQL should be resolved"
    assert "redis" in analysis["resolved_issues"], "Redis should be resolved"
    assert "postgresql" in analysis["worsening_trends"], "PostgreSQL should be worsening"

    # Test 4: Get service history
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Get Service History")
    logger.info("=" * 80)

    mysql_history = history.get_service_history("mysql", recent_cycles)
    logger.info(f"MySQL appeared in {len(mysql_history)} cycles:")
    for entry in mysql_history:
        logger.info(f"  - Cycle {entry['cycle_id']}: {entry['severity']} - {entry['description']}")

    assert len(mysql_history) == 2, f"Expected MySQL in 2 cycles, got {len(mysql_history)}"

    postgresql_history = history.get_service_history("postgresql", recent_cycles)
    logger.info(f"PostgreSQL appeared in {len(postgresql_history)} cycles:")
    for entry in postgresql_history:
        logger.info(f"  - Cycle {entry['cycle_id']}: {entry['severity']} - {entry['description']}")

    assert len(postgresql_history) == 2, f"Expected PostgreSQL in 2 cycles, got {len(postgresql_history)}"

    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL TESTS PASSED!")
    logger.info("=" * 80)
    logger.info("\nCycle memory is working correctly:")
    logger.info("  1. Loads recent cycle reports from disk")
    logger.info("  2. Formats history into readable summaries")
    logger.info("  3. Detects new, recurring, resolved, and worsening issues")
    logger.info("  4. Tracks service history across cycles")
    logger.info("\nThe k8s-monitor will now have memory across cycles!")


if __name__ == "__main__":
    try:
        test_cycle_history()
    except AssertionError as e:
        logger.error(f"❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"❌ TEST ERROR: {e}", exc_info=True)
        exit(1)
