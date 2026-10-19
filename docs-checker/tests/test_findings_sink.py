import dataclasses
import logging

import pytest
from a2a.types import a2a_pb2
from botocore.exceptions import EndpointConnectionError

from docs_checker.findings_sink import CloudWatchFindings
from docs_checker.ledger import CostLedger
from docs_checker.report import Report
from docs_checker.state import Claim, Finding, Window
from tests.fakes import fake_settings
from tests.test_executor import a2a_message, docs_executor, docs_repo, send  # noqa: F401
from tests.test_graph import VAULT_DOC

GITHUB_PAT = "ghp_" + "A" * 36


class FakeLogs:
    def __init__(self, fail_with: Exception | None = None):
        self.streams: list[tuple[str, str]] = []
        self.events: list[dict] = []
        self.fail_with = fail_with

    def create_log_stream(self, logGroupName, logStreamName):
        self.streams.append((logGroupName, logStreamName))

    def put_log_events(self, logGroupName, logStreamName, logEvents):
        if self.fail_with is not None:
            raise self.fail_with
        self.events.extend(logEvents)


def finding(line: int, evidence: str = "version = 1") -> Finding:
    claim = Claim(
        doc="docs/USAGE.md",
        line_start=line,
        line_end=line,
        text="version 0",
        kind="version",
        keys=["version"],
        values=["0"],
        source_hint="variables.tf",
    )
    return Finding(
        id=claim.id,
        instance="run-1",
        commit="c" * 40,
        doc=claim.doc,
        line_start=line,
        line_end=line,
        claim=claim,
        verdict="stale",
        evidence=Window(source="variables.tf", start=1, end=2, text=evidence),
        evidence_hash="h",
        confidence=0.9,
        old_text="version 0",
        replacement="version 1",
    )


def summary():
    return CostLedger("run-1", "ctx-1", emit=False).summary("verified")


async def test_one_event_per_finding_plus_run():
    import json

    logs = FakeLogs()
    sink = CloudWatchFindings(
        log_group="/docs-checker/findings", stream_prefix="chg-infra-opentofu-bedrock", client=logs
    )
    report = Report(run_id="run-1", commit="c" * 40, findings=[finding(1), finding(2), finding(3)])
    await sink.publish("run-1", report, summary(), repo="chghealthcare/chg-infra-opentofu-bedrock")
    assert logs.streams == [("/docs-checker/findings", "chg-infra-opentofu-bedrock/run-1")]
    events = [json.loads(e["message"]) for e in logs.events]
    assert [e["type"] for e in events] == ["finding", "finding", "finding", "run"]
    first = events[0]
    assert first["repo"] == "chghealthcare/chg-infra-opentofu-bedrock"
    assert (first["doc"], first["line_start"], first["verdict"]) == ("docs/USAGE.md", 1, "stale")
    assert first["evidence"][0]["source"] == "variables.tf"
    assert events[-1]["findings"] == 3 and "cost_usd" in events[-1]
    assert [e["timestamp"] for e in logs.events] == sorted(e["timestamp"] for e in logs.events)


async def test_events_are_redacted():
    logs = FakeLogs()
    sink = CloudWatchFindings(log_group="/g", stream_prefix="p", client=logs)
    report = Report(run_id="r", commit="c" * 40, findings=[finding(1, f"token = {GITHUB_PAT}")])
    await sink.publish("r", report, summary(), repo="o/r")
    assert GITHUB_PAT not in "".join(e["message"] for e in logs.events)


async def test_publish_failure_logs_one_warning(caplog):
    logs = FakeLogs(fail_with=EndpointConnectionError(endpoint_url="https://logs"))
    sink = CloudWatchFindings(log_group="/g", stream_prefix="p", client=logs)
    report = Report(run_id="r", commit="c" * 40, findings=[finding(1)])
    with caplog.at_level(logging.WARNING):
        await sink.publish("r", report, summary(), repo="o/r")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "findings not published: EndpointConnectionError" in warnings[0].getMessage()


async def test_publish_failure_does_not_fail_task(docs_repo, caplog):  # noqa: F811
    """Review Focus 5: CloudWatch unreachable, the run still completes with its report."""
    repo, commit = docs_repo
    logs = FakeLogs(fail_with=EndpointConnectionError(endpoint_url="https://logs"))
    executor = docs_executor(repo, commit)
    executor._findings = CloudWatchFindings(log_group="/g", stream_prefix="p", client=logs)
    queue = await send(executor, a2a_message("", {"scope": [VAULT_DOC], "mode": "interactive"}))
    assert queue.states()[-1] == a2a_pb2.TaskState.TASK_STATE_COMPLETED
    assert "findings not published" in caplog.text


async def test_completed_run_publishes(docs_repo):  # noqa: F811
    repo, commit = docs_repo
    logs = FakeLogs()
    executor = docs_executor(repo, commit)
    executor._findings = CloudWatchFindings(log_group="/g", stream_prefix="p", client=logs)
    await send(executor, a2a_message("", {"scope": [VAULT_DOC], "mode": "interactive"}))
    assert logs.events and '"type": "run"' in logs.events[-1]["message"]


def test_sink_off_by_default(monkeypatch, docs_repo):  # noqa: F811
    import boto3

    def no_client(*args, **kwargs):
        raise AssertionError("a CloudWatch client was built")

    monkeypatch.setattr(boto3, "client", no_client)
    repo, commit = docs_repo
    assert docs_executor(repo, commit)._findings is None


def test_settings_turn_the_sink_on(monkeypatch, docs_repo):  # noqa: F811
    built = []
    monkeypatch.setattr(
        "boto3.client", lambda service, **kwargs: built.append((service, kwargs)) or FakeLogs()
    )
    settings = dataclasses.replace(
        fake_settings(), findings_log_group="/docs-checker/findings", aws_region="us-west-2"
    )
    repo, commit = docs_repo
    executor = docs_executor(repo, commit, settings=settings)
    assert executor._findings is not None
    assert built == [("logs", {"region_name": "us-west-2"})]


@pytest.mark.parametrize("value", ["", "/docs-checker/findings"])
def test_findings_log_group_setting(value):
    from docs_checker.config import load_settings

    env = {"DOCS_CHECKER_FINDINGS_LOG_GROUP": value} if value else {}
    assert load_settings(env).findings_log_group == value
