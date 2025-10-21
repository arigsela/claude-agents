"""Scheduler for running monitoring cycles on a schedule."""

import asyncio
import logging
import signal
from typing import Awaitable, Callable

import schedule


class Scheduler:
    """Manages scheduled execution of monitoring cycles."""

    def __init__(self, interval_hours: int = 1):
        """Initialize scheduler.

        Args:
            interval_hours: Hours between monitoring cycles (default: 1)
        """
        self.interval_hours = interval_hours
        self.logger = logging.getLogger(__name__)
        self.is_running = False
        self._job = None

    def schedule_job(
        self, func: Callable[[], Awaitable[None]], job_name: str = "monitoring", run_immediately: bool = True
    ) -> None:
        """Schedule a job to run on interval.

        Args:
            func: Async function to execute on schedule
            job_name: Human-readable name for the job
            run_immediately: If True, run the job immediately on startup before waiting for interval
        """
        self.logger.info(
            f"Scheduling {job_name} to run every {self.interval_hours} hour(s)"
        )

        # Schedule the job
        self._job = schedule.every(self.interval_hours).hours.do(
            self._run_async, func=func, job_name=job_name
        )

        # Store the function for immediate execution if requested
        if run_immediately:
            self._immediate_func = (func, job_name)
        else:
            self._immediate_func = None

    def _run_async(
        self, func: Callable[[], Awaitable[None]], job_name: str
    ) -> None:
        """Run an async function from the synchronous scheduler.

        Args:
            func: Async function to execute
            job_name: Name of the job for logging
        """
        self.logger.info(f"Running scheduled job: {job_name}")
        try:
            asyncio.run(func())
        except Exception as e:
            self.logger.error(f"Error in scheduled job {job_name}: {e}", exc_info=True)

    async def run_forever(self) -> None:
        """Run the scheduler in an async loop.

        This blocks until interrupted (Ctrl+C) or stop() is called.
        Runs the immediate job first if configured, then continues with scheduled jobs.
        """
        self.is_running = True
        self.logger.info("Scheduler starting")

        # Run immediate job if configured
        if hasattr(self, '_immediate_func') and self._immediate_func:
            func, job_name = self._immediate_func
            self.logger.info(f"Running immediate startup job: {job_name}")
            await func()

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()

        def handle_shutdown(sig):
            self.logger.info(f"Received signal {sig}, shutting down gracefully")
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_shutdown, sig)

        try:
            while self.is_running:
                # Run pending jobs
                schedule.run_pending()
                # Sleep briefly to avoid busy-waiting
                await asyncio.sleep(1)
        except Exception as e:
            self.logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            raise
        finally:
            self.logger.info("Scheduler stopped")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self.is_running = False
        self.logger.info("Stop signal received")

    def clear(self) -> None:
        """Clear all scheduled jobs."""
        schedule.clear()
        self._job = None
        self.logger.info("All jobs cleared")
