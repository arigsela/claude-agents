# ==============================================================================
# Structured Logging Configuration
# ==============================================================================
#
# WHY TWO FORMATS?
# - "text" format: Human-readable logs for local development.
#   Example: 2026-03-01 10:30:45 INFO [orchestrator] Starting server on port 8000
#
# - "json" format: Machine-parseable logs for Kubernetes/production.
#   Example: {"timestamp":"2026-03-01T10:30:45Z","level":"INFO","service":"orchestrator","message":"Starting server"}
#   Log aggregators (Loki, CloudWatch, Datadog) can parse JSON automatically,
#   enabling filtering, searching, and alerting on structured fields.
#
# HOW TO USE:
#   from shared.logging_config import setup_logging
#   logger = setup_logging("my-service")
#   logger.info("Something happened", extra={"key": "value"})
# ==============================================================================

import logging
import json
import sys
from datetime import datetime, timezone

from shared.config import LOG_FORMAT, LOG_LEVEL


class JSONFormatter(logging.Formatter):
    """
    Formats log records as JSON objects — one per line.

    Kubernetes log collectors (Fluentd, Promtail, Vector) parse JSON logs
    automatically, so you can filter by level, service, or any extra field
    in your log aggregator's query language.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "message": record.getMessage(),
        }
        # Include any extra fields passed via logger.info("msg", extra={...})
        if hasattr(record, "plugin"):
            log_entry["plugin"] = record.plugin
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


class TextFormatter(logging.Formatter):
    """
    Human-readable format for local development.
    Includes timestamp, level, service name, and the message.
    """

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging(service_name: str) -> logging.Logger:
    """
    Create and configure a logger for the given service.

    Args:
        service_name: Identifier shown in log output (e.g., "orchestrator", "knowledge-agent")

    Returns:
        A configured logging.Logger instance.

    Usage:
        logger = setup_logging("orchestrator")
        logger.info("Server started on port 8000")
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)

        if LOG_FORMAT == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(TextFormatter())

        logger.addHandler(handler)

    return logger

