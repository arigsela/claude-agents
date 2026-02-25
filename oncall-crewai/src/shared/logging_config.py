"""Structured logging configuration for oncall-crewai."""

import logging
import sys

from shared.config import AGENT_LOG_LEVEL


def setup_logging(name: str = "oncall-crewai") -> logging.Logger:
    """Set up structured logging with configurable level.

    Args:
        name: Logger name (typically the agent/service name).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    level = getattr(logging, AGENT_LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
