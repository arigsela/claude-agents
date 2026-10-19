"""The eval harness: replay cassettes, the spend guard, scoring and memory across runs.

No test reaches the API: the "live" side of every recording is an httpx2
MockTransport, and the repository is a temp git repo behind the local fake of the
agent-docs server.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest

from docs_checker.evals.__main__ import main, summary
from docs_checker.evals.harness import (
    HarnessConfig,
    Instance,
    append_results,
    load_eval_set,
    load_instances,
    run_arm,
    run_instance,
)
from docs_checker.evals.harness import levers_spec as levers_of
from docs_checker.evals.replay import CassetteMiss, ReplayTransport
from docs_checker.evals.score import AWAITING, AwaitingAdjudication, LabelledLine, Score, score
from docs_checker.evals.spend import (
    LEDGER_ENV,
    HarnessBusy,
    SpendCapExceeded,
    SpendGuard,
    SpendLedgerUnwritable,
    ledger_path,
)
from docs_checker.levers import Levers
from docs_checker.llm import REPLAYED_HEADER
from docs_checker.state import Claim, Finding
from tests.test_llm import OVERLOADED, message_body
from tests.test_scope import make_tree

URL = "https://api.anthropic.com/v1/messages"
REQUEST = {
    "model": "claude-haiku-5-5",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "q"}],
}


def refuse(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"a replay run reached the network: {request.url}")


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch) -> Path:
    """Every test gets its own spend ledger: none may touch the real per-user one."""
    path = tmp_path / "ledger" / "spend.json"
    monkeypatch.setenv(LEDGER_ENV, str(path))
    return path


# --- replay ------------------------------------------------------------------------------


async def test_replay_returns_attempts_in_order(tmp_path):
    statuses = iter([529, 200])

    def live(request: httpx2.Request) -> httpx2.Response:
        status = next(statuses)
        if status == 529:
            headers = {"request-id": "req_529", "retry-after": "0"}
            return httpx2.Response(529, headers=headers, json=OVERLOADED)
        return httpx2.Response(200, headers={"request-id": "req_200"}, json=message_body("ok"))

    recorder = ReplayTransport(httpx2.MockTransport(live), tmp_path, "record-missing")
    async with httpx2.AsyncClient(transport=recorder) as client:
        first = await client.post(URL, json=REQUEST)
        second = await client.post(URL, json=REQUEST)
    assert [first.status_code, second.status_code] == [529, 200]
    assert REPLAYED_HEADER not in first.headers  # it went to the API: cash
    (cassette,) = tmp_path.glob("*.json")
    assert [a["status"] for a in json.loads(cassette.read_text())["attempts"]] == [529, 200]

    replay = ReplayTransport(httpx2.MockTransport(refuse), tmp_path, "replay")
    reordered = dict(reversed(list(REQUEST.items())))  # the key is the canonical body
    async with httpx2.AsyncClient(transport=replay) as client:
        again = [await client.post(URL, json=reordered), await client.post(URL, json=REQUEST)]
        with pytest.raises(CassetteMiss):  # only two attempts were recorded
            await client.post(URL, json=REQUEST)
        with pytest.raises(CassetteMiss):  # a changed prompt is a miss, never a guess
            await client.post(URL, json={**REQUEST, "max_tokens": 65})
    assert [(r.status_code, r.headers["request-id"]) for r in again] == [
        (529, "req_529"),
        (200, "req_200"),
    ]
    assert again[0].headers["retry-after"] == "0"
    assert again[1].json() == message_body("ok")
    assert {r.headers[REPLAYED_HEADER] for r in again} == {"1"}
    assert len(replay.misses) == 2

    # each run starts from the first attempt again
    fresh = ReplayTransport(httpx2.MockTransport(refuse), tmp_path, "replay")
    async with httpx2.AsyncClient(transport=fresh) as client:
        assert (await client.post(URL, json=REQUEST)).status_code == 529

    # the retry row: a synthetic 529 before each key's recordings, free and never recorded
    injected = ReplayTransport(httpx2.MockTransport(refuse), tmp_path, "replay", overloaded=1)
    async with httpx2.AsyncClient(transport=injected) as client:
        statuses = [(await client.post(URL, json=REQUEST)) for _ in range(3)]
    assert [r.status_code for r in statuses] == [529, 529, 200]
    assert {r.headers[REPLAYED_HEADER] for r in statuses} == {"1"}
    assert len(json.loads(cassette.read_text())["attempts"]) == 2


async def test_cassette_never_contains_key_or_request(tmp_path):
    api_key = "sk-ant-api03-" + "k" * 40
    prompt = "PROMPT-MARKER: is chart vault at 0.30.1?"
    leaked = "ghp_" + "x" * 36

    def live(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["x-api-key"] == api_key
        headers = {
            "request-id": "req_1",
            "anthropic-organization-id": "org-secret-id",
            "set-cookie": "session=abc",
        }
        return httpx2.Response(200, headers=headers, json=message_body(f"token {leaked} found"))

    recorder = ReplayTransport(httpx2.MockTransport(live), tmp_path, "record-missing")
    body = {**REQUEST, "messages": [{"role": "user", "content": prompt}]}
    async with httpx2.AsyncClient(transport=recorder) as client:
        response = await client.post(URL, json=body, headers={"x-api-key": api_key})
    (cassette,) = tmp_path.glob("*.json")
    text = cassette.read_text()
    for secret in (api_key, "PROMPT-MARKER", "org-secret-id", "session=abc", leaked, "x-api-key"):
        assert secret not in text, secret
    (attempt,) = json.loads(text)["attempts"]
    assert set(attempt) == {"status", "request_id", "retry_after", "content_type", "body"}
    assert attempt["request_id"] == "req_1"
    # the recording run sees exactly what a replay will: the redacted body
    assert leaked not in response.text and "[REDACTED]" in response.text


def answering(*responses: httpx2.Response) -> tuple[httpx2.MockTransport, list[int]]:
    """A live API that answers with ``responses`` in order and counts its calls."""
    queue, calls = list(responses), []

    def live(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return queue.pop(0)

    return httpx2.MockTransport(live), calls


def overloaded() -> httpx2.Response:
    return httpx2.Response(529, json=OVERLOADED)


def ok(text: str = "ok") -> httpx2.Response:
    return httpx2.Response(200, json=message_body(text))


async def post_all(transport: ReplayTransport, count: int) -> list[httpx2.Response]:
    async with httpx2.AsyncClient(transport=transport) as client:
        return [await client.post(URL, json=REQUEST) for _ in range(count)]


async def test_record_missing_rerecords_a_cassette_that_ended_in_failure(tmp_path):
    # Retries ran out: the cassette ends in 529s.
    live, _ = answering(overloaded(), overloaded(), overloaded())
    await post_all(ReplayTransport(live, tmp_path, "record-missing"), 3)
    (cassette,) = tmp_path.glob("*.json")
    assert [a["status"] for a in json.loads(cassette.read_text())["attempts"]] == [529] * 3

    # The next priced run records it again instead of replaying the failure forever.
    live, calls = answering(ok("fresh"))
    (response,) = await post_all(ReplayTransport(live, tmp_path, "record-missing"), 1)
    assert (response.status_code, len(calls)) == (200, 1)
    assert [a["status"] for a in json.loads(cassette.read_text())["attempts"]] == [200]

    # A 529 whose retry succeeded is kept, in order, and served without a call.
    cassette.unlink()
    live, _ = answering(overloaded(), ok("after retry"))
    await post_all(ReplayTransport(live, tmp_path, "record-missing"), 2)
    live, calls = answering()
    responses = await post_all(ReplayTransport(live, tmp_path, "record-missing"), 2)
    assert [r.status_code for r in responses] == [529, 200] and calls == []
    # replay mode serves whatever was recorded (it never re-records)
    (cassette,) = tmp_path.glob("*.json")
    cassette.write_text(json.dumps({"version": 1, "attempts": [{"status": 529, "body": {}}]}))
    (replayed,) = await post_all(
        ReplayTransport(httpx2.MockTransport(refuse), tmp_path, "replay"), 1
    )
    assert replayed.status_code == 529


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_non_retryable_client_errors_are_never_recorded(tmp_path, status):
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "no"}}
    live, calls = answering(httpx2.Response(status, json=error), ok())
    first, second = await post_all(ReplayTransport(live, tmp_path, "record-missing"), 2)
    assert first.status_code == status and REPLAYED_HEADER not in first.headers
    assert second.status_code == 200 and len(calls) == 2  # the retry went live again
    (cassette,) = tmp_path.glob("*.json")
    assert [a["status"] for a in json.loads(cassette.read_text())["attempts"]] == [200]

    live, _ = answering(httpx2.Response(status, json=error))
    other = tmp_path / "other"
    await post_all(ReplayTransport(live, other, "record-missing"), 1)
    assert not list(other.glob("*.json"))  # a wrong key or no credit leaves nothing behind


# --- spend -------------------------------------------------------------------------------


def test_spend_guard_reserves_and_keeps_reservation_on_crash(tmp_path):
    path = tmp_path / ".spend.json"
    guard = SpendGuard(path, cap_usd=1.0)
    with guard.lock():
        first = guard.reserve("run-1", 0.4, instance="a", levers="none")
        assert (guard.settled_usd, guard.reserved_usd) == (0.0, 0.4)
        guard.settle(first, cash_usd=0.1, workload_usd=0.3)
        assert (guard.settled_usd, guard.reserved_usd) == (0.1, 0.0)
        with pytest.raises(RuntimeError, match="crashed"):
            guard.reserve("run-2", 0.5, instance="b", levers="none")
            raise RuntimeError("the harness crashed mid-run")

    # A new process: the crashed run may have spent its whole estimate, so it still counts.
    again = SpendGuard(path, cap_usd=1.0)
    with again.lock():
        assert (again.settled_usd, again.reserved_usd) == (0.1, 0.5)
        assert again.headroom_usd == pytest.approx(0.4)
        with pytest.raises(SpendCapExceeded):
            again.reserve("run-3", 0.45, instance="c", levers="none")
        third = again.reserve("run-3", 0.4, instance="c", levers="none")  # fits exactly
        with pytest.raises(HarnessBusy), SpendGuard(path, cap_usd=1.0).lock():
            pass  # one harness at a time
        again.settle(third, cash_usd=0.0, workload_usd=0.2)
    with pytest.raises(RuntimeError, match="lock"):  # never outside the lock
        again.reserve("run-4", 0.01, instance="d", levers="none")
    # history estimates the next priced run of the same instance and levers
    assert SpendGuard(path).estimate("a", "none") == (0.3, "history")
    assert SpendGuard(path).estimate("z", "none") == (0.60, "default")
    assert SpendGuard(path).estimate("z", "all") == (0.05, "default")


# --- scoring -----------------------------------------------------------------------------


def finding(instance: str, start: int, end: int, verdict: str = "stale") -> Finding:
    claim = Claim(
        doc="base-apps/x/docs.md",
        line_start=start,
        line_end=end,
        text=f"claim on {start}-{end}",
        kind="version",
        values=["1.0"],
    )
    return Finding(
        id=claim.id,
        instance=instance,
        commit="c" * 40,
        doc=claim.doc,
        line_start=start,
        line_end=end,
        claim=claim,
        verdict=verdict,
        evidence_hash="e",
        confidence=0.9,
        old_text="old",
        replacement="new",
    )


def label(instance: str, line: int, value: str) -> LabelledLine:
    return LabelledLine(instance=instance, line=line, label=value)


def test_score_one_to_one_and_adjudication():
    labels = [
        label("a", 5, "stale"),
        label("a", 9, "missing"),
        label("a", 12, "true"),
        label("a", 14, "uncertain"),
        label("a", 20, "stale"),  # never found: FN
        label("a", 40, "stale"),
        label("a", 41, "stale"),
        label("b", 5, "stale"),  # instance a's finding on line 5 cannot match it: FN
    ]
    findings = [
        finding("a", 5, 6),  # TP
        finding("a", 5, 5),  # the same label again: one-to-one, so FP
        finding("a", 9, 9, "stale"),  # a missing line called stale: wrong class, FP
        finding("a", 12, 12),  # a line labelled true: FP
        finding("a", 14, 14),  # uncertain: neither FP nor FN
        finding("a", 30, 30),  # no label: adjudicate, not FP
        # A greedy pass gives line 40 to the first and leaves the second unmatched;
        # the maximum matching gives the first line 41 instead, so both are TP.
        finding("a", 39, 41),
        finding("a", 40, 40),
        finding("b", 9, 9, "missing"),  # a's label on line 9 is not b's
    ]
    result = score(findings, labels, workload_usd=0.6, cash_usd=0.25)

    assert (result.tp, result.fp, result.fn, result.excluded) == (3, 3, 3, 1)
    assert [(a["instance"], a["line_start"]) for a in result.to_adjudicate] == [("a", 30), ("b", 9)]
    assert result.precision == 0.5 and result.recall == 0.5
    assert (result.workload_usd, result.cash_usd) == (0.6, 0.25)
    assert result.cost_per_verified == pytest.approx(0.2)
    empty = score([], [label("a", 3, "true")])
    assert (empty.precision, empty.recall, empty.cost_per_verified) == (None, None, None)
    with pytest.raises(ValueError, match="twice"):
        score([], [label("a", 3, "true"), label("a", 3, "stale")])


PENDING = LabelledLine(
    instance="a", line=5, label="uncertain", note=AWAITING, labeller_a="stale", labeller_b="missing"
)


def test_a_disagreement_awaiting_adjudication_is_never_scored():
    """Its placeholder label (uncertain) would silently exclude the finding on it."""
    with pytest.raises(AwaitingAdjudication, match=r"1 labelled lines await .*: a line 5"):
        score([finding("a", 5, 5)], [PENDING, label("a", 9, "true")])
    decided = PENDING.model_copy(update={"label": "stale", "note": "", "adjudicated_by": "claude"})
    assert score([finding("a", 5, 5)], [decided]).tp == 1
    kept_note = PENDING.model_copy(update={"label": "stale", "adjudicated_by": "claude"})
    assert score([finding("a", 5, 5)], [kept_note]).tp == 1  # adjudicated: no longer pending
    plain = score([finding("a", 5, 5)], [label("a", 5, "uncertain")])
    assert (plain.tp, plain.fp, plain.fn, plain.excluded) == (0, 0, 0, 1)


def test_an_eval_set_holding_a_placeholder_does_not_load(tmp_path, capsys):
    evals = tmp_path / "evals"
    write_eval_set(evals, [Instance(id="a", doc=DOC, commit="c" * 40)])
    (evals / "labels").mkdir()
    (evals / "labels" / "set.json").write_text(json.dumps([PENDING.model_dump()]))
    with pytest.raises(AwaitingAdjudication, match="a line 5"):
        load_eval_set(evals)
    argv = ["run", "--instances", "a", "--levers", "none", "--evals-dir", str(evals), "--dry-run"]
    assert main(argv) == 1
    assert "await adjudication" in capsys.readouterr().err
    instances, _ = load_instances(evals)  # curation still reads the instances
    assert list(instances) == ["a"]
    decided = {**PENDING.model_dump(), "label": "stale", "adjudicated_by": "claude"}
    (evals / "labels" / "set.json").write_text(json.dumps([decided]))
    assert [lab.label for lab in load_eval_set(evals).labels] == ["stale"]


def test_results_and_the_console_show_excluded_findings(tmp_path):
    base = {
        "ts": "t1",
        "arm": "baseline",
        "kind": "instance",
        "instance": "a",
        "levers": "none",
        "mode": "replay",
        "memory_in": False,
        "status": "checked",
        "calls": 3,
        "cache_read": 0,
        "cache_write": 0,
        "workload_usd": 0.1,
        "cash_usd": 0.0,
    }
    now = Score(tp=1, fp=0, fn=0, excluded=2)
    old = {k: v for k, v in now.to_dict().items() if k != "excluded"}  # before the column
    append_results(
        tmp_path, [{**base, "score": now.to_dict()}, {**base, "arm": "older", "score": old}]
    )
    lines = (tmp_path / "results.md").read_text().splitlines()

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    column = cells(next(line for line in lines if line.startswith("| When")))
    column_index = column.index("Excluded (uncertain lines)")
    rows = {cells(line)[1]: cells(line) for line in lines if line.startswith("| t1 ")}
    assert (rows["baseline"][column_index], rows["older"][column_index]) == ("2", "0")

    run = SimpleNamespace(
        instance=SimpleNamespace(id="a"),
        status="checked",
        summary=SimpleNamespace(calls=3, workload_cost_usd=0.1),
        cash_usd=0.0,
        score=now,
    )
    assert summary(run).endswith("TP 1 FP 0 FN 0, to adjudicate 0, excluded 2")


# --- the harness on a temp repo ------------------------------------------------------------

DOC = "base-apps/vault/docs.md"
FILES = {
    "base-apps/vault/values.yaml": "chart: vault\nversion: 0.31.0\nreplicas: 1\n",
    DOC: (
        "---\nsources:\n  - base-apps/vault/values.yaml\n---\n# Vault\n"
        "Vault runs chart vault version 0.30.1.\n"
    ),
}
CLAIM_TEXT = "Vault runs chart vault version 0.30.1"
ANSWERS = {
    "extract": {
        "claims": [
            {
                "line_start": 6,
                "line_end": 6,
                "text": CLAIM_TEXT,
                "kind": "chart",
                "keys": ["chart", "version"],
                "values": ["vault", "0.30.1"],
                "source_hint": "",
            }
        ]
    },
    "judge": {"verdict": "stale", "confidence": 0.9, "reason": "0.31.0", "window_index": 0},
    "fix": {"replacement": "Vault runs chart vault version 0.31.0."},
}
EVAL_KEY = "sk-ant-api03-" + "e" * 40


def node_of(body: dict) -> str:
    properties = body["output_config"]["format"]["schema"]["properties"]
    for key, node in (("claims", "extract"), ("verdict", "judge"), ("replacement", "fix")):
        if key in properties:
            return node
    raise AssertionError(f"unexpected request: {sorted(properties)}")


class Api:
    """The Anthropic API as a MockTransport: answers each node, counts what it served.
    ``usage`` sets a node's (input, output) tokens; a node in ``hang`` never answers."""

    def __init__(self, usage: dict | None = None, hang: tuple[str, ...] = ()):
        self.nodes: list[str] = []
        self.credentials: set[tuple[str, str | None, str | None]] = set()
        self.usage = usage or {}
        self.hang = hang
        self.hanging = asyncio.Event()

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        node = node_of(json.loads(request.content))
        self.nodes.append(node)
        headers = request.headers
        self.credentials.add(
            (request.url.host, headers.get("x-api-key"), headers.get("authorization"))
        )
        if node in self.hang:
            self.hanging.set()
            await asyncio.Event().wait()
        tokens = dict(
            zip(("input_tokens", "output_tokens"), self.usage.get(node, ()), strict=False)
        )
        body = message_body(json.dumps(ANSWERS[node]), **tokens)
        return httpx2.Response(200, headers={"request-id": f"req_{len(self.nodes)}"}, json=body)


@pytest.fixture
def eval_repo(tmp_path) -> tuple[Path, Instance]:
    repo, commit = make_tree(tmp_path, FILES)
    return repo, Instance(id="vault-stale", doc=DOC, commit=commit, split="dev", purpose="t")


def config(
    tmp_path: Path, repo: Path, mode: str, api: Api | None = None, **kwargs
) -> HarnessConfig:
    live = httpx2.MockTransport(api or refuse)
    key = EVAL_KEY if mode == "record-missing" else None
    return HarnessConfig(
        evals_dir=tmp_path / "evals", clone=repo, mode=mode, api_key=key, live=live, **kwargs
    )


LABELS = [LabelledLine(instance="vault-stale", line=6, label="stale")]


async def test_replayed_calls_cost_workload_not_cash(tmp_path, eval_repo, monkeypatch):
    repo, instance = eval_repo
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "not-for-evals")  # conftest sets the others
    api = Api()
    recorded = await run_instance(
        config(tmp_path, repo, "record-missing", api), instance, Levers.all_on(), LABELS
    )
    assert api.nodes == ["extract", "judge", "fix"]
    # the eval key only, to the API itself: never ANTHROPIC_API_KEY, _AUTH_TOKEN or _BASE_URL
    assert api.credentials == {("api.anthropic.com", EVAL_KEY, None)}
    paid = recorded.summary
    assert paid.cash_cost_usd > 0 and paid.cash_cost_usd == paid.workload_cost_usd
    assert (recorded.score.tp, recorded.score.fp, recorded.score.fn) == (1, 0, 0)

    replayed = await run_instance(
        config(tmp_path, repo, "replay"), instance, Levers.all_on(), LABELS
    )
    assert api.nodes == ["extract", "judge", "fix"]  # nothing more reached the API
    free = replayed.summary
    assert free.cash_cost_usd == 0.0
    assert free.workload_cost_usd == paid.workload_cost_usd > 0
    assert replayed.calls_by_node == recorded.calls_by_node == {"extract": 1, "judge": 1, "fix": 1}
    assert replayed.score.tp == 1 and replayed.score.cash_usd == 0.0
    assert replayed.score.cost_per_verified == pytest.approx(paid.workload_cost_usd)

    # a lever change that changes a prompt is a miss in replay mode, never a guess
    with pytest.raises(CassetteMiss):
        await run_instance(
            config(tmp_path, repo, "replay"), instance, Levers.without("cache_prefix"), LABELS
        )


async def test_second_run_with_memory_makes_no_extract_or_judge_calls(tmp_path, eval_repo):
    repo, instance = eval_repo
    memory = tmp_path / "memory.json"
    api = Api()
    (first,) = await run_arm(
        config(tmp_path, repo, "record-missing", api),
        [instance],
        Levers.all_on(),
        LABELS,
        arm="short_circuit cold",
        memory_out=memory,
    )
    assert first.status == "checked" and first.calls_by_node["extract"] == 1
    assert json.loads(memory.read_text())["instances"]["vault-stale"]["docs"][DOC]

    (second,) = await run_arm(
        config(tmp_path, repo, "replay"),
        [instance],
        Levers.all_on(),
        LABELS,
        arm="short_circuit warm",
        memory_in=memory,
    )
    assert second.status == "unchanged"
    assert second.calls_by_node == {}  # no extract, judge or fix call, not even replayed
    assert second.summary.workload_cost_usd == 0.0
    assert second.score.tp == 1  # the open finding is carried, not lost
    assert api.nodes == ["extract", "judge", "fix"]

    evals = tmp_path / "evals"
    records = [json.loads(line) for line in (evals / "results.jsonl").read_text().splitlines()]
    instance_rows = [r for r in records if r["kind"] == "instance"]
    assert [(r["arm"], r["memory_in"]) for r in instance_rows] == [
        ("short_circuit cold", False),
        ("short_circuit warm", True),
    ]
    table = (evals / "results.md").read_text()
    assert "short_circuit warm" in table and "vault-stale" in table
    # the priced run settled its reservation to its cash cost; the replay paid nothing
    spend = SpendGuard()
    assert spend.reserved_usd == 0.0
    assert spend.settled_usd == pytest.approx(first.summary.cash_cost_usd)


# --- what a priced run may spend ------------------------------------------------------------


def only_run(guard: SpendGuard) -> dict:
    (run,) = [r for r in guard._read()["runs"] if r["mode"] != "replay"]
    return run


async def test_a_crashed_priced_run_keeps_a_reservation_for_its_whole_budget(tmp_path, eval_repo):
    repo, instance = eval_repo
    api = Api(hang=("judge",))  # extract is answered (and billed), then the judge hangs
    cfg = config(tmp_path, repo, "record-missing", api)
    arm = asyncio.ensure_future(run_arm(cfg, [instance], Levers.all_on(), LABELS, arm="crash"))
    await api.hanging.wait()
    arm.cancel()  # Ctrl-C, a timeout, a kill: the run never settles
    with pytest.raises(asyncio.CancelledError):
        await arm

    guard = SpendGuard()
    (held,) = guard.open_reservations().values()
    # not the $0.05 estimate: everything the run was allowed to spend stays counted
    assert held["amount_usd"] == cfg.run_budget_usd == 2.0
    assert held["estimate_usd"] == 0.05
    assert guard.headroom_usd == pytest.approx(18.0)


async def test_a_run_past_its_estimate_stops_at_its_run_budget(tmp_path, eval_repo):
    repo, instance = eval_repo
    levers = Levers.without("right_size")  # Sonnet everywhere: dear calls
    guard = SpendGuard()
    with guard.lock():  # history says this run costs a tenth of a cent
        guard.record(instance=instance.id, levers=levers_of(levers), workload_usd=0.001)
    api = Api(usage={"extract": (500, 4000)})  # $0.041: forty times the estimate
    cfg = config(tmp_path, repo, "record-missing", api, run_budget_usd=0.06)
    (run,) = await run_arm(cfg, [instance], levers, LABELS, arm="dear")

    assert api.nodes == ["extract"]  # the judge's reservation no longer fit the budget
    assert run.status == "skipped-budget"
    assert run.cash_usd == pytest.approx(0.041)
    settled = only_run(SpendGuard())
    assert (settled["estimate_usd"], settled["reserved_usd"]) == (0.001, 0.06)
    assert settled["cash_usd"] == pytest.approx(0.041)

    # a run is refused only when the cap's headroom is below its estimate
    full = SpendGuard(cap_usd=0.0415)
    with full.lock(), pytest.raises(SpendCapExceeded):
        full.reserve_run("next", estimate_usd=0.001, budget_usd=2.0, instance="x", levers="all")
    with full.lock():
        held = full.reserve_run(
            "next", estimate_usd=0.0001, budget_usd=2.0, instance="x", levers="all"
        )
    assert held.amount_usd == pytest.approx(0.0005)  # the headroom, not the run budget


async def test_a_run_that_fails_before_any_request_settles_to_zero(tmp_path, eval_repo):
    repo, instance = eval_repo
    gone = instance.model_copy(update={"commit": "f" * 40})  # not in the clone
    with pytest.raises(ValueError, match="names no commit"):
        await run_arm(
            config(tmp_path, repo, "record-missing", Api()),
            [gone],
            Levers.all_on(),
            LABELS,
            arm="x",
        )
    guard = SpendGuard()
    assert guard.open_reservations() == {}
    assert only_run(guard)["cash_usd"] == 0.0 and guard.settled_usd == 0.0


# --- the spend ledger is per user ------------------------------------------------------------


async def test_the_spend_ledger_is_per_user_not_per_checkout(
    tmp_path, eval_repo, monkeypatch, ledger
):
    repo, instance = eval_repo
    # two checkouts (evals dirs) share one ledger: a fresh one does not start at $0
    first = config(tmp_path / "one", repo, "record-missing", Api())
    second = config(tmp_path / "two", repo, "record-missing", Api())
    await run_arm(first, [instance], Levers.all_on(), LABELS, arm="a")
    paid = SpendGuard().settled_usd
    assert paid > 0 and ledger.exists()
    await run_arm(second, [instance], Levers.without("cache_prefix"), LABELS, arm="b")
    assert SpendGuard().settled_usd > paid
    assert not list((tmp_path / "one" / "evals").glob(".spend*"))

    # the default is a fixed per-user path; the env override is for tests
    monkeypatch.delenv(LEDGER_ENV)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert ledger_path() == tmp_path / "home" / ".cache" / "docs-checker" / "spend.json"

    # a ledger that cannot be written stops a priced run before anything is spent
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setenv(LEDGER_ENV, str(blocker / "spend.json"))
    api = Api()
    with pytest.raises(SpendLedgerUnwritable):
        await run_arm(
            config(tmp_path, repo, "record-missing", api),
            [instance],
            Levers.all_on(),
            LABELS,
            arm="c",
        )
    assert api.nodes == []


# --- the command line --------------------------------------------------------------------


def write_eval_set(evals: Path, instances: list[Instance]) -> None:
    evals.mkdir(parents=True, exist_ok=True)
    data = {
        "instances": [i.model_dump() for i in instances],
        "sets": {"lever": [instances[0].id]},
    }
    (evals / "instances.json").write_text(json.dumps(data))


def test_dry_run_prints_a_spend_table_without_a_call(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY", raising=False)
    evals = tmp_path / "evals"
    instances = [
        Instance(id="one", doc=DOC, commit="a" * 40),
        Instance(id="two", doc=DOC, commit="b" * 40, split="holdout"),
    ]
    write_eval_set(evals, instances)
    guard = SpendGuard()
    with guard.lock():
        guard.record(instance="one", levers="none", workload_usd=0.42, mode="replay")

    code = main(
        ["run", "--instances", "all", "--levers", "none", "--dry-run", "--evals-dir", str(evals)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "one" in out and "0.4200" in out and "history" in out
    assert "two" in out and "0.6000" in out and "default" in out
    assert "1.0200" in out  # the total
    assert not (evals / "results.jsonl").exists()


def test_record_missing_refuses_to_start_without_the_eval_key(
    tmp_path, capsys, monkeypatch, ledger
):
    monkeypatch.delenv("DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY", raising=False)
    evals = tmp_path / "evals"
    write_eval_set(evals, [Instance(id="one", doc=DOC, commit="a" * 40)])
    args = ["run", "--instances", "lever", "--levers", "all", "--mode", "record-missing"]
    code = main([*args, "--evals-dir", str(evals), "--clone", str(tmp_path)])
    assert code == 2
    assert "DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not ledger.exists()


def test_record_missing_refuses_an_unwritable_ledger(tmp_path, capsys, monkeypatch, eval_repo):
    repo, instance = eval_repo
    monkeypatch.setenv("DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY", EVAL_KEY)
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.setenv(LEDGER_ENV, str(blocker / "spend.json"))
    evals = tmp_path / "evals"
    write_eval_set(evals, [instance])
    args = ["run", "--instances", "lever", "--levers", "all", "--mode", "record-missing"]
    code = main([*args, "--evals-dir", str(evals), "--clone", str(repo)])
    assert code == 2
    assert "spend ledger" in capsys.readouterr().err
