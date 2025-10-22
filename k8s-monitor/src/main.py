"""Main entry point for k8s-monitor."""

import asyncio
import logging
import sys
from pathlib import Path

from src.config import Settings
from src.orchestrator import Monitor
from src.utils import Scheduler


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Set up logging configuration.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    # Create logs directory
    Path("logs").mkdir(exist_ok=True)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # File handler
    file_handler = logging.FileHandler("logs/k8s-monitor.log")
    file_handler.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)


async def run_monitoring_cycle(monitor: Monitor) -> None:
    """Run a single monitoring cycle.

    Args:
        monitor: Monitor instance
    """
    logger = logging.getLogger(__name__)

    try:
        results = await monitor.run_monitoring_cycle()
        monitor.save_cycle_report(results)

        logger.info(f"Cycle completed: {results['status']}")

    except Exception as e:
        logger.error(f"Error during monitoring cycle: {e}", exc_info=True)


async def main() -> None:
    """Main entry point."""
    # Load settings
    try:
        settings = Settings()
        settings.validate_all()
    except Exception as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # Set up logging
    logger = setup_logging(settings.log_level)
    logger.info("K3s Monitor starting...")

    # Create monitor instance
    monitor = Monitor(settings)

    # Set up scheduler
    scheduler = Scheduler(interval_minutes=settings.monitoring_interval_minutes)
    scheduler.schedule_job(
        lambda: run_monitoring_cycle(monitor), job_name="k8s_monitoring"
    )

    try:
        # Run scheduler
        await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
