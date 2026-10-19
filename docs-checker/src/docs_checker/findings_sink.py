"""Findings to CloudWatch Logs, for a dashboard: nothing is posted to a PR or a chat.

One JSON event per finding (new, needs-a-look and carried) and one ``run`` event, in
stream ``<stream prefix>/<run id>`` of the findings log group. The events are built
from the same ``Report`` the A2A report is, and redacted again on the way out.

Publishing never fails a run: on any error it logs one warning and returns, and the
task still completes with its report.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from docs_checker.redact import redact_obj

logger = logging.getLogger(__name__)


def _finding_event(finding: Any, repo: str, run_id: str) -> dict:
    evidence = [finding.evidence.model_dump(mode="json")] if finding.evidence else []
    return {
        "type": "finding",
        "run_id": run_id,
        "repo": repo,
        "commit": finding.commit,
        "doc": finding.doc,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "verdict": finding.verdict,
        "confidence": finding.confidence,
        "claim": finding.claim.text,
        "old_text": finding.old_text,
        "evidence": evidence,
        "replacement": finding.replacement,
        "fix_withheld": finding.fix_withheld,
        "needs_look": finding.needs_look,
        "carried": finding.carried,
    }


def _run_event(report: Any, summary: Any, repo: str, run_id: str, findings: int) -> dict:
    return {
        "type": "run",
        "run_id": run_id,
        "repo": repo,
        "commit": report.commit,
        "docs_checked": report.counts.get("docs_checked", 0),
        "findings": findings,
        "cost_usd": summary.cost_usd_known,
        "cost_complete": summary.complete,
        "model_calls": summary.calls,
        "incomplete_docs": list(report.incomplete) + list(report.failed),
        "outcome": summary.outcome,
    }


class CloudWatchFindings:
    def __init__(self, *, log_group: str, stream_prefix: str, client: Any = None):
        self._log_group = log_group
        self._prefix = stream_prefix
        self._client = client

    async def publish(self, run_id: str, report: Any, summary: Any, *, repo: str) -> None:
        try:
            await asyncio.to_thread(self._publish, run_id, report, summary, repo)
        except Exception as error:  # noqa: BLE001 - a dashboard feed never fails the run
            logger.warning("findings not published: %s", type(error).__name__)

    def _publish(self, run_id: str, report: Any, summary: Any, repo: str) -> None:
        found = list(report.findings) + list(report.needs_look) + list(report.carried)
        bodies = [_finding_event(f, repo, run_id) for f in found]
        bodies.append(_run_event(report, summary, repo, run_id, len(found)))
        stream = f"{self._prefix}/{run_id}"
        try:
            self._client.create_log_stream(logGroupName=self._log_group, logStreamName=stream)
        except Exception as error:  # an existing stream (a resumed run) is fine
            if (
                type(error).__name__ != "ResourceAlreadyExistsException"
                and getattr(error, "response", {}).get("Error", {}).get("Code")
                != "ResourceAlreadyExistsException"
            ):
                raise
        now = int(time.time() * 1000)
        events = [
            {"timestamp": now, "message": json.dumps(redact_obj(body), sort_keys=True)}
            for body in bodies
        ]
        self._client.put_log_events(
            logGroupName=self._log_group, logStreamName=stream, logEvents=events
        )


def build_findings_sink(settings: Any) -> CloudWatchFindings | None:
    """The sink ``settings.findings_log_group`` asks for; None (no client) when unset."""
    if not settings.findings_log_group:
        return None
    import boto3

    client = boto3.client("logs", region_name=settings.aws_region or None)
    return CloudWatchFindings(
        log_group=settings.findings_log_group,
        stream_prefix=settings.repo.split("/", 1)[1],
        client=client,
    )
