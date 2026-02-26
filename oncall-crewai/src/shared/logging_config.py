"""Structured logging configuration for oncall-crewai.

Supports both plain text (local dev) and JSON (Kubernetes / log aggregation)
output formats, configurable via the LOG_FORMAT environment variable.
"""

import json
import logging
import sys
from datetime import UTC, datetime

from shared.config import AGENT_LOG_LEVEL, LOG_FORMAT


class JSONFormatter(logging.Formatter):
    """JSON log formatter for Kubernetes / log aggregation environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(name: str = "oncall-crewai") -> logging.Logger:
    """Set up logging with configurable level and format.

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

        if LOG_FORMAT == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

        logger.addHandler(handler)

    return logger
