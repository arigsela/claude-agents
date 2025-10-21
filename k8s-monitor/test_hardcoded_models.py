#!/usr/bin/env python3
"""Test script to verify hardcoded Haiku models are configured correctly.

This tests WITHOUT running the full monitoring cycle:
1. Loads settings
2. Checks module constants
3. Verifies no Sonnet references
4. Tests Monitor initialization
5. Verifies logging output
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import Settings
from src.orchestrator.monitor import (
    ORCHESTRATOR_MODEL,
    K8S_ANALYZER_MODEL,
    ESCALATION_MANAGER_MODEL,
    SLACK_NOTIFIER_MODEL,
    GITHUB_REVIEWER_MODEL,
    Monitor,
)


def setup_test_logging():
    """Set up logging for test output."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger(__name__)


def test_hardcoded_constants():
    """Test 1: Verify all module constants are hardcoded to Haiku."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("TEST 1: Verifying Hardcoded Constants")
    logger.info("=" * 80)

    HAIKU_MODEL = "claude-haiku-4-5-20251001"
    SONNET_KEYWORDS = ["sonnet", "claude-sonnet"]

    constants = {
        "ORCHESTRATOR_MODEL": ORCHESTRATOR_MODEL,
        "K8S_ANALYZER_MODEL": K8S_ANALYZER_MODEL,
        "ESCALATION_MANAGER_MODEL": ESCALATION_MANAGER_MODEL,
        "SLACK_NOTIFIER_MODEL": SLACK_NOTIFIER_MODEL,
        "GITHUB_REVIEWER_MODEL": GITHUB_REVIEWER_MODEL,
    }

    all_passed = True
    for const_name, const_value in constants.items():
        if const_value == HAIKU_MODEL:
            logger.info(f"✅ {const_name}: {const_value}")
        else:
            logger.error(f"❌ {const_name}: {const_value} (expected {HAIKU_MODEL})")
            all_passed = False

        # Check for Sonnet
        if any(keyword in const_value.lower() for keyword in SONNET_KEYWORDS):
            logger.error(f"❌ {const_name} contains Sonnet model!")
            all_passed = False

    logger.info("=" * 80)
    return all_passed


def test_agent_files():
    """Test 2: Verify agent definition files have hardcoded models."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("TEST 2: Verifying Agent Definition Files")
    logger.info("=" * 80)

    agent_files = [
        ".claude/agents/k8s-analyzer.md",
        ".claude/agents/escalation-manager.md",
        ".claude/agents/slack-notifier.md",
        ".claude/agents/github-reviewer.md",
    ]

    HAIKU_MODEL = "claude-haiku-4-5-20251001"
    all_passed = True

    for agent_file in agent_files:
        path = Path(agent_file)
        if not path.exists():
            logger.error(f"❌ Agent file not found: {agent_file}")
            all_passed = False
            continue

        content = path.read_text()

        # Check for model line
        if "model:" in content:
            # Extract model value
            for line in content.split("\n"):
                if line.strip().startswith("model:"):
                    model_value = line.split(":", 1)[1].strip()

                    # Check if it's hardcoded Haiku
                    if model_value == HAIKU_MODEL:
                        logger.info(f"✅ {path.name}: {model_value}")
                    elif "$" in model_value:
                        logger.error(
                            f"❌ {path.name}: Still has variable {model_value}"
                        )
                        all_passed = False
                    else:
                        logger.error(
                            f"❌ {path.name}: Unexpected model {model_value}"
                        )
                        all_passed = False
                    break
        else:
            logger.error(f"❌ {path.name}: No model line found")
            all_passed = False

    logger.info("=" * 80)
    return all_passed


def test_settings_loading():
    """Test 3: Verify settings load without errors."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("TEST 3: Loading Settings")
    logger.info("=" * 80)

    try:
        settings = Settings()
        logger.info(f"✅ Settings loaded successfully")
        logger.info(f"   API Key present: {'Yes' if settings.anthropic_api_key else 'No'}")
        logger.info(f"   K3s Context: {settings.k3s_context}")
        logger.info(f"   Log Level: {settings.log_level}")
        logger.info("=" * 80)
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load settings: {e}")
        logger.info("=" * 80)
        return False


async def test_monitor_initialization():
    """Test 4: Verify Monitor can be initialized with hardcoded models."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("TEST 4: Monitor Initialization (without running cycle)")
    logger.info("=" * 80)

    try:
        settings = Settings()
        monitor = Monitor(settings)
        logger.info(f"✅ Monitor instance created successfully")
        logger.info(f"   Cycle ID: {monitor.cycle_id}")

        # Log model configuration that will be used
        logger.info("=" * 80)
        logger.info("HARDCODED MODEL CONFIGURATION:")
        logger.info("=" * 80)
        logger.info(f"🤖 ORCHESTRATOR_MODEL: {ORCHESTRATOR_MODEL}")
        logger.info(f"📊 K8S_ANALYZER_MODEL: {K8S_ANALYZER_MODEL}")
        logger.info(f"🚨 ESCALATION_MANAGER_MODEL: {ESCALATION_MANAGER_MODEL}")
        logger.info(f"💬 SLACK_NOTIFIER_MODEL: {SLACK_NOTIFIER_MODEL}")
        logger.info(f"🔍 GITHUB_REVIEWER_MODEL: {GITHUB_REVIEWER_MODEL}")
        logger.info("=" * 80)

        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize Monitor: {e}", exc_info=True)
        logger.info("=" * 80)
        return False


def test_no_sonnet_references():
    """Test 5: Verify no Sonnet references in source code."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 80)
    logger.info("TEST 5: Scanning for Sonnet References in Code")
    logger.info("=" * 80)

    sonnet_patterns = [
        "claude-sonnet",
        "SONNET",
        "setup_writable_claude_dir",
        "$K8S_ANALYZER_MODEL",
        "$ESCALATION_MANAGER_MODEL",
        "$SLACK_NOTIFIER_MODEL",
        "$GITHUB_REVIEWER_MODEL",
    ]

    files_to_check = [
        "src/orchestrator/monitor.py",
        ".claude/agents/k8s-analyzer.md",
        ".claude/agents/escalation-manager.md",
        ".claude/agents/slack-notifier.md",
        ".claude/agents/github-reviewer.md",
        ".env",
    ]

    found_issues = False

    for file_path in files_to_check:
        path = Path(file_path)
        if not path.exists():
            logger.debug(f"Skipping (not found): {file_path}")
            continue

        content = path.read_text()

        for pattern in sonnet_patterns:
            # For variable patterns, look for exact matches
            if pattern.startswith("$"):
                if pattern in content:
                    logger.error(f"❌ Found {pattern} in {file_path}")
                    found_issues = True
            # For Sonnet pattern, check case-insensitive
            elif pattern.lower() in content.lower():
                # But check actual case to avoid false positives
                if "claude-sonnet" in content.lower():
                    logger.error(f"❌ Found Sonnet reference in {file_path}")
                    found_issues = True
                elif pattern == "setup_writable_claude_dir" and pattern in content:
                    logger.error(f"❌ Found {pattern} in {file_path}")
                    found_issues = True

    if not found_issues:
        logger.info("✅ No Sonnet references found in any code files")
    else:
        logger.error("❌ Found Sonnet references - see above")

    logger.info("=" * 80)
    return not found_issues


async def main():
    """Run all tests."""
    logger = setup_test_logging()

    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " HARDCODED HAIKU - LOCAL VERIFICATION TESTS ".center(78) + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")

    results = {
        "Constants": test_hardcoded_constants(),
        "Agent Files": test_agent_files(),
        "Settings Loading": test_settings_loading(),
        "No Sonnet References": test_no_sonnet_references(),
        "Monitor Initialization": await test_monitor_initialization(),
    }

    # Summary
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " TEST SUMMARY ".center(78) + "║")
    logger.info("╠" + "=" * 78 + "╣")

    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"║ {test_name:40s}: {status:33s} ║")
        if not passed:
            all_passed = False

    logger.info("╠" + "=" * 78 + "╣")

    if all_passed:
        logger.info("║" + " ALL TESTS PASSED - READY FOR DEPLOYMENT ".center(78) + "║")
    else:
        logger.info("║" + " SOME TESTS FAILED - CHECK OUTPUT ABOVE ".center(78) + "║")

    logger.info("╚" + "=" * 78 + "╝")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
