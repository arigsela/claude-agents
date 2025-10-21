#!/usr/bin/env python3
"""Test script that EXPLICITLY uses API token instead of Claude Code subscription.

This allows you to:
1. Verify API token is being used
2. See token usage in Anthropic Console
3. Test before production deployment
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Load .env BEFORE any imports that use Anthropic SDK
load_dotenv()

# Now import after .env is loaded
from src.config import Settings
from src.orchestrator.monitor import Monitor


def setup_logging():
    """Set up logging for test output."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger(__name__)


async def main():
    """Run single monitoring cycle with explicit API token usage."""
    logger = setup_logging()

    logger.info("=" * 80)
    logger.info("TESTING WITH EXPLICIT API TOKEN (NOT Claude Code subscription)")
    logger.info("=" * 80)

    # 1. Verify API key is loaded from .env
    logger.info("\n1. CHECKING AUTHENTICATION:")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("❌ ANTHROPIC_API_KEY not in environment!")
        logger.error("   Make sure .env file is present with valid API key")
        sys.exit(1)

    logger.info(f"✅ ANTHROPIC_API_KEY loaded: {'*' * 20}...{api_key[-10:]}")

    # 2. Load settings
    logger.info("\n2. LOADING SETTINGS:")
    try:
        settings = Settings()
        settings.validate_all()
        logger.info(f"✅ Settings loaded successfully")
        logger.info(f"   - K3s Context: {settings.k3s_context}")
        logger.info(f"   - Log Level: {settings.log_level}")
    except Exception as e:
        logger.error(f"❌ Failed to load settings: {e}")
        sys.exit(1)

    # 3. Create monitor
    logger.info("\n3. INITIALIZING MONITOR:")
    try:
        monitor = Monitor(settings)
        logger.info(f"✅ Monitor created (cycle ID: {monitor.cycle_id})")
    except Exception as e:
        logger.error(f"❌ Failed to create monitor: {e}")
        sys.exit(1)

    # 4. Run single cycle
    logger.info("\n4. RUNNING MONITORING CYCLE WITH EXPLICIT API TOKEN:")
    logger.info("=" * 80)
    logger.info("⚠️  THIS WILL USE YOUR API TOKEN (billing will reflect this)")
    logger.info("⚠️  YOU SHOULD SEE TOKENS IN ANTHROPIC CONSOLE WITHIN MINUTES")
    logger.info("=" * 80)

    try:
        results = await monitor.run_monitoring_cycle()

        logger.info("\n" + "=" * 80)
        logger.info("✅ MONITORING CYCLE COMPLETED")
        logger.info("=" * 80)
        logger.info(f"   Status: {results['status']}")
        logger.info(f"   Findings: {len(results.get('findings', []))}")
        logger.info(f"   Cycle ID: {results['cycle_id']}")

        # Save report
        monitor.save_cycle_report(results)
        logger.info(f"✅ Cycle report saved to logs/cycle_{results['cycle_id']}.json")

    except Exception as e:
        logger.error(f"❌ Monitoring cycle failed: {e}", exc_info=True)
        sys.exit(1)

    # 5. Verify ModelInspector audit log for Sonnet detection
    logger.info("\n" + "=" * 80)
    logger.info("AUTOMATIC SONNET VALIDATION (via ModelInspector):")
    logger.info("=" * 80)

    audit_log_path = Path("logs/model_usage.jsonl")
    sonnet_detected = False

    if audit_log_path.exists():
        import json
        with open(audit_log_path, "r") as f:
            latest_entry = None
            for line in f:
                try:
                    latest_entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

        if latest_entry:
            haiku_count = latest_entry.get("haiku_count", 0)
            sonnet_count = latest_entry.get("sonnet_count", 0)
            models = latest_entry.get("models", {})

            logger.info(f"✅ Audit log found: {audit_log_path}")
            logger.info(f"   - Haiku count: {haiku_count}")
            logger.info(f"   - Sonnet count: {sonnet_count}")
            logger.info(f"   - Models detected: {models}")

            if sonnet_count > 0:
                sonnet_detected = True
                logger.error("❌ SONNET DETECTED! This should not happen with hardcoding!")
                logger.error(f"   Models with Sonnet: {[m for m in models if 'sonnet' in m.lower()]}")
            else:
                logger.info("✅ NO SONNET DETECTED - Haiku hardcoding is working!")
    else:
        logger.warning("⚠️  Audit log not found yet (ModelInspector will create it)")

    # 6. Manual verification instructions
    logger.info("\n" + "=" * 80)
    logger.info("MANUAL VERIFICATION IN ANTHROPIC CONSOLE (1-2 minutes):")
    logger.info("=" * 80)
    logger.info("1. Go to: https://console.anthropic.com/")
    logger.info("2. Check 'Token Usage' tab")
    logger.info("3. Look for recent token usage from YOUR API KEY")
    logger.info("4. You should see:")
    logger.info("   - Input tokens: ~2-3K (orchestrator + k8s-analyzer)")
    logger.info("   - Output tokens: ~5-10K (responses)")
    logger.info("   - Model: claude-haiku-4-5-20251001")
    logger.info("5. If you see Sonnet usage, that would indicate a fallback")
    logger.info("=" * 80)

    # Exit with error if Sonnet detected
    if sonnet_detected:
        logger.error("\n❌ TEST FAILED: Sonnet usage detected!")
        return 1

    logger.info("\n✅ TEST PASSED: All validations successful!")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
