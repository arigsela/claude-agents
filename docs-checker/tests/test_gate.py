import math
import sys
from types import SimpleNamespace

import pytest

from docs_checker.gate import (
    AngleGate,
    FixAction,
    FixGate,
    RecordingGate,
    Thresholds,
    ToolCallContext,
    angle_degrees,
    apply_fix,
    build_fix_gate,
    render_action,
    render_fix,
    render_intent,
)
from docs_checker.prompts import validate_replacement
from docs_checker.render import structure_refusal
from docs_checker.server import build_executor, placeholder_graph
from docs_checker.state import Claim, Finding, Window
from tests.fakes import FakeModels, fake_settings, fake_tools_by_server
from tests.markdown_cases import (
    BLIND_SPOTS,
    CONTROL,
    CONTROL_LINES,
    FLIP_IDS,
    FLIPS,
    FRONT_MATTER,
    OPEN_TAG_QUOTE,
    REPRO_COMMENT_NESTING,
    REPRO_TOGGLE,
    flip_case,
)


def test_actions_render_as_one_deterministic_sentence():
    args = {"path": "base-apps/vault/values.yaml", "repo": "kubernetes", "owner": "arigsela"}
    assert (
        render_action("get_file_contents", args)
        == "Read the file base-apps/vault/values.yaml from the arigsela/kubernetes repository."
    )
    # unknown tools: sorted keys, so the same call always gives the same sentence
    assert render_action("x", {"b": 1, "a": 2}) == render_action("x", {"a": 2, "b": 1})
    assert (
        render_intent("Answers questions.", " What runs? ") == "Answers questions. Task: What runs?"
    )


def test_angle_between_vectors():
    assert angle_degrees([1, 0], [1, 0]) == pytest.approx(0.0)
    assert angle_degrees([1, 0], [0, 1]) == pytest.approx(90.0)
    assert angle_degrees([1, 0], [-1, 0]) == pytest.approx(180.0)
    assert angle_degrees([0, 0], [1, 0]) == 180.0


@pytest.mark.parametrize(
    ("angle", "decision"),
    [(37.4, "allow"), (56.0, "ask"), (73.3, "refuse"), (45.0, "ask"), (70.0, "refuse")],
)
def test_demo_thresholds(angle, decision):
    assert Thresholds(ask_at=45, refuse_at=70).decide(angle) == decision


class StubEmbedder:
    """Maps texts to fixed vectors; the real one is an embedding model (no LLM)."""

    def __init__(self, vectors):
        self.vectors = vectors

    async def embed(self, texts):
        return [self.vectors[t] for t in texts]


def call(action, workflow="docs"):
    return ToolCallContext(intent="intent", action=action, tool="t", args={}, workflow=workflow)


async def test_angle_gate_uses_per_workflow_thresholds():
    import math

    def at(deg):
        return [math.cos(math.radians(deg)), math.sin(math.radians(deg))]

    embedder = StubEmbedder({"intent": [1.0, 0.0], "near": at(30), "far": at(80), "mid": at(50)})
    gate = AngleGate(
        embedder,
        thresholds={"catalog": Thresholds(ask_at=60, refuse_at=90)},
        default=Thresholds(ask_at=45, refuse_at=70),
    )
    assert (await gate.check(call("near"))).decision == "allow"
    assert (await gate.check(call("mid"))).decision == "ask"
    assert (await gate.check(call("far"))).decision == "refuse"
    # a looser, open-ended workflow allows the same angle
    assert (await gate.check(call("mid", workflow="catalog"))).decision == "allow"
    result = await gate.check(call("far"))
    assert result.angle_deg == pytest.approx(80.0)


async def test_recording_gate_allows_and_keeps_the_calibration_data():
    gate = RecordingGate()
    result = await gate.check(call("Read the file x."))
    assert result.decision == "allow"
    assert gate.seen[0].action == "Read the file x."


# --- the fix gate ------------------------------------------------------------------

DOC_PATH = "base-apps/vault/docs.md"
DOC = FRONT_MATTER + [
    "# Vault",  # 5
    "",
    "Vault runs chart 0.30.1, see [the docs](https://developer.hashicorp.com/vault).",  # 7
    "",
    "Sessions live in the redis cache.",  # 9
    "",
    "Images come from <https://hub.docker.com> and www.docker.com.",  # 11
]
VERSION_LINE = DOC[6]
VERSION_FIX = "Vault runs chart 0.31.0, see [the docs](https://developer.hashicorp.com/vault)."
# The comment line is not evidence: 0.32.0 and evilredis appear only there.
EVIDENCE = Window(
    source="base-apps/vault/values.yaml",
    start=1,
    end=4,
    text="chart: vault\nversion: 0.31.0\ncache: valkey\n# was: evilredis 0.32.0",
)
INTENT = "Correct the stale chart version on line 7 of base-apps/vault/docs.md."


def make_claim(line_start=7, line_end=None, *, doc=DOC_PATH, kind="version", values=("0.30.1",)):
    return Claim(
        doc=doc,
        line_start=line_start,
        line_end=line_start if line_end is None else line_end,
        text="Vault runs chart 0.30.1",
        kind=kind,
        values=list(values),
    )


def make_finding(claim, replacement, *, doc_lines=DOC, **changes):
    old = "\n".join(doc_lines[claim.line_start - 1 : claim.line_end])
    data = {
        "id": "f1",
        "instance": "test",
        "commit": "c0ffee",
        "doc": claim.doc,
        "line_start": claim.line_start,
        "line_end": claim.line_end,
        "claim": claim,
        "verdict": "stale",
        "evidence": EVIDENCE,
        "evidence_hash": "h",
        "confidence": 0.9,
        "old_text": old,
        "replacement": replacement,
    }
    data.update(changes)
    return Finding(**data)


def fix(replacement=VERSION_FIX, *, claim=None, doc_lines=DOC, **changes) -> FixAction:
    claim = claim or make_claim()
    finding = make_finding(claim, replacement, doc_lines=doc_lines, **changes)
    return FixAction(finding=finding, claim=claim, doc_lines=list(doc_lines))


async def decide(action, gate=None) -> str:
    return (await (gate or FixGate()).check(INTENT, action)).decision


async def test_a_fix_inside_the_claim_with_evidence_is_allowed():
    result = await FixGate().check(INTENT, fix())
    assert result.decision == "allow" and result.angle_deg is None


REPEATED = DOC + ["", VERSION_LINE]  # line 13 repeats the claim's line 7


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (13, 13),  # another line with the same text
        (7, 8),  # the claim's line and the next one
        (6, 7),
    ],
)
async def test_a_fix_that_changes_another_range_is_refused(start, end):
    # The old text is the claim's own line and the new text passes every other rule:
    # only the range ties the fix to the claim's lines.
    assert await decide(fix(doc_lines=REPEATED, line_start=start, line_end=end)) == "refuse"
    assert await decide(fix(doc_lines=REPEATED)) == "allow"


LAST_LINE_FIX = "Images come from <https://hub.docker.com> and www.docker.com today."


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (11, 12),  # past the end: the slice is still line 11
        (0, 11),  # from line 0: the slice wraps round to line 11
        (40, 40),
        (9, 7),
    ],
)
async def test_a_claim_range_outside_the_doc_is_refused(start, end):
    assert len(DOC) == 11
    claim = make_claim(start, end)
    assert await decide(fix(LAST_LINE_FIX, claim=claim)) == "refuse"
    assert await decide(fix(LAST_LINE_FIX, claim=make_claim(11))) == "allow"


async def test_a_fix_for_another_doc_or_claim_is_refused():
    assert await decide(fix(doc="base-apps/redis/docs.md")) == "refuse"
    # The finding carries another claim (same range, another kind): the kind decides
    # which rules apply, so it must be the claim the gate checks against.
    claim = make_claim()
    finding = make_finding(claim, VERSION_FIX).model_copy(
        update={"claim": make_claim(kind="config")}
    )
    assert await decide(FixAction(finding=finding, claim=claim, doc_lines=list(DOC))) == "refuse"


@pytest.mark.parametrize(
    "old_text",
    [
        # what a model says the line was (another version), so its fix looks like a change
        "Vault runs chart 0.29.0, see [the docs](https://developer.hashicorp.com/vault).",
        VERSION_LINE + "\n",
        VERSION_LINE.replace(" ", "  ", 1),
        "",
    ],
)
async def test_old_text_must_match_the_doc(old_text):
    assert await decide(fix(old_text=old_text)) == "refuse"


@pytest.mark.parametrize(
    "replacement",
    [
        "Vault runs chart 0.31.0, see [the docs](https://evil.example/vault).",  # a new URL
        "Vault runs chart 0.32.0, see [the docs](https://developer.hashicorp.com/vault).",
        "",  # no fix
        VERSION_FIX + "\n",  # not what the rule would hand on (it strips the newline)
    ],
)
async def test_a_replacement_the_rule_rejects_is_refused(replacement):
    # 0.32.0 is only in a comment line of the evidence: comments are never evidence.
    assert await decide(fix(replacement)) == "refuse"


async def test_a_stale_finding_must_change_its_lines():
    assert await decide(fix(VERSION_LINE)) == "refuse"
    # A missing finding carries its lines unchanged.
    assert await decide(fix(VERSION_LINE, verdict="missing")) == "allow"


@pytest.mark.parametrize("kind", ["name", "image", "host", "namespace"])
async def test_a_new_word_in_a_name_claim_must_come_from_the_evidence(kind):
    claim = make_claim(9, kind=kind, values=("redis",))
    # Ruling G1: a letters-only word may change freely elsewhere, so here it must be in
    # the evidence's code (evilredis is only in a comment line).
    assert await decide(fix("Sessions live in the evilredis cache.", claim=claim)) == "refuse"
    assert await decide(fix("Sessions live in the valkey cache.", claim=claim)) == "allow"


async def test_other_claim_kinds_keep_the_plain_word_rule():
    claim = make_claim(9, kind="config", values=("redis",))
    assert await decide(fix("Sessions live in the evilredis cache.", claim=claim)) == "allow"


class AngleEmbedder:
    """The intent along x; every other text at ``angle`` degrees. Records its calls."""

    def __init__(self, angle: float):
        self.angle = angle
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        rad = math.radians(self.angle)
        return [[1.0, 0.0]] + [[math.cos(rad), math.sin(rad)] for _ in texts[1:]]


DEMO = Thresholds(ask_at=45, refuse_at=70)


async def test_angle_never_overrides_a_refusal():
    embedder = AngleEmbedder(0.0)  # the angle alone would allow
    gate = FixGate(embedder=embedder, thresholds=DEMO)
    refused = fix(old_text="Vault runs chart 0.29.0")
    assert await decide(refused, gate) == "refuse"
    assert await decide(fix(), gate) == "allow"


@pytest.mark.parametrize(("angle", "decision"), [(10.0, "allow"), (50.0, "ask"), (80.0, "refuse")])
async def test_the_angle_can_add_an_ask_or_a_refusal(angle, decision):
    embedder = AngleEmbedder(angle)
    action = fix()
    result = await FixGate(embedder=embedder, thresholds=DEMO).check(INTENT, action)
    assert result.decision == decision
    assert result.angle_deg == pytest.approx(angle)
    assert embedder.calls == [[INTENT, render_fix(action)]]


def test_threshold_order_is_validated():
    with pytest.raises(ValueError):
        Thresholds(ask_at=70, refuse_at=45)
    for bad in (
        SimpleNamespace(ask_at=70, refuse_at=45),
        SimpleNamespace(ask_at=45, refuse_at=45),
        SimpleNamespace(ask_at=float("nan"), refuse_at=45),
    ):
        with pytest.raises(ValueError):
            FixGate(thresholds=bad)
    with pytest.raises(ValueError):
        FixGate(embedder=AngleEmbedder(0.0))  # an angle needs its thresholds
    FixGate()
    FixGate(thresholds=DEMO)


def test_the_fix_renders_as_one_deterministic_sentence():
    assert render_fix(fix()) == render_fix(fix())
    sentence = render_fix(fix())
    assert DOC_PATH in sentence and "0.30.1" in sentence and "0.31.0" in sentence


async def _tools():
    return fake_tools_by_server()


async def test_production_factory_uses_the_rules_gate():
    bad = fix("Vault runs chart 0.31.0, see [the docs](https://evil.example/vault).")
    gate = build_fix_gate(fake_settings())
    assert isinstance(gate, FixGate)
    assert await decide(bad, gate) == "refuse"
    assert await decide(fix(), gate) == "allow"

    # What production builds (server.serve passes no gate): the run's dependencies
    # carry the rules gate.
    executor = build_executor(
        fake_settings(), graph=placeholder_graph(), models=FakeModels(), tools=_tools
    )
    deps = await executor._deps(executor._new_ledger("task-1", "ctx-1"), {})
    assert isinstance(deps.fix_gate, FixGate)
    assert await decide(bad, deps.fix_gate) == "refuse"
    assert await decide(fix(), deps.fix_gate) == "allow"


# --- the render check through the whole gate (rulings G4 and G5) --------------------


async def decide_case(case, kind="version") -> str:
    lines, start, end, new = case
    claim = make_claim(start, end, kind=kind)
    return await decide(fix(new, claim=claim, doc_lines=lines))


def passes_line_rules(case) -> bool:
    lines, start, end, new = case
    old = "\n".join(lines[start - 1 : end])
    return validate_replacement(old, new, EVIDENCE.text) == new


@pytest.mark.parametrize(("name", "old", "new"), FLIPS, ids=FLIP_IDS)
async def test_a_block_kind_flip_that_makes_a_link_live_is_refused(name, old, new):
    assert await decide_case(flip_case(old, new)) == "refuse"


async def test_review_repro_comment_closed_over_deep_nesting_is_refused():
    # Passes every per-line rule: only the render check refuses it.
    assert passes_line_rules(REPRO_COMMENT_NESTING)
    assert await decide_case(REPRO_COMMENT_NESTING) == "refuse"


@pytest.mark.parametrize("name", list(REPRO_TOGGLE))
async def test_review_repro_fence_toggled_by_a_moved_backtick_is_refused(name):
    # Refused twice over: the backtick moved lines (per-line markup runs, G5) and the
    # structure changed.
    assert not passes_line_rules(REPRO_TOGGLE[name])
    assert await decide_case(REPRO_TOGGLE[name]) == "refuse"


@pytest.mark.parametrize("name", list(BLIND_SPOTS))
async def test_each_parser_blind_spot_is_refused(name):
    assert await decide_case(BLIND_SPOTS[name]) == "refuse"


async def test_an_underscore_host_is_refused_by_the_line_rule_inside_the_claim():
    # GitHub autolinks https://get_vault.evil.example/..., linkify-it does not, so as
    # plain text inside the claim's line it leaves the structure alone: the replacement
    # rule refuses it (a URL the old line does not have). Outside the claim's lines it
    # only goes live through a flip, which the structure check refuses (BLIND_SPOTS,
    # REPRO_TOGGLE["underscore host"]).
    lines = FRONT_MATTER + ["", "Install chart 0.30.1 from the registry.", "", "End."]
    new = "Install chart 0.31.0 from https://get_vault.evil.example/install.sh"
    assert structure_refusal(lines, apply_fix(lines, 6, 6, new)) is None
    assert not passes_line_rules((lines, 6, 6, new))
    assert await decide_case((lines, 6, 6, new)) == "refuse"


async def test_a_text_only_fix_after_raw_html_left_open_is_refused():
    assert passes_line_rules(OPEN_TAG_QUOTE)
    assert await decide_case(OPEN_TAG_QUOTE) == "refuse"


@pytest.mark.parametrize("line", CONTROL_LINES)
async def test_a_version_fix_in_ordinary_markdown_is_allowed(line):
    new = CONTROL[line - 1].replace("0.30.1", "0.31.0")
    assert await decide_case((CONTROL, line, line, new)) == "allow"


@pytest.mark.parametrize("limit", [1000, 2500], ids=["python-default", "kagent-core"])
@pytest.mark.parametrize("deep", [">" * 1200 + " Install it", "- " * 600 + "Install it"])
async def test_very_deep_nesting_is_refused_not_crashed(monkeypatch, limit, deep):
    # Past the nesting limit, or past Python's recursion limit (kagent.core raises it
    # to 2500 in the image): a refusal either way, in the worker thread, no crash.
    before = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        result = await FixGate().check(INTENT, fix(doc_lines=DOC + ["", deep]))
    finally:
        sys.setrecursionlimit(before)
    assert result.decision == "refuse"
    assert "RecursionError" in result.reason or "nests deeper" in result.reason


@pytest.mark.parametrize(
    "target",
    [
        "docs_checker.gate.validate_replacement",
        "docs_checker.gate.structure_refusal",
        "docs_checker.gate.apply_fix",
        "docs_checker.evidence.code_only",
    ],
)
async def test_anything_the_rules_raise_is_a_refusal(monkeypatch, target):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(target, broken)
    result = await FixGate().check(INTENT, fix())
    assert result.decision == "refuse" and "RuntimeError" in result.reason


async def test_a_refusal_says_whether_the_target_or_the_fix_is_wrong():
    # Ruling F1: the graph drops a finding whose fix targets other lines or another
    # doc, and keeps (fix withheld) one whose fix itself is unsafe.
    for action in (
        fix(doc="base-apps/redis/docs.md"),
        fix(doc_lines=REPEATED, line_start=13, line_end=13),
        fix(old_text=""),
    ):
        result = await FixGate().check(INTENT, action)
        assert (result.decision, result.kind) == ("refuse", "target")
    for action in (fix(""), fix(VERSION_LINE), fix(VERSION_FIX + "\n")):
        result = await FixGate().check(INTENT, action)
        assert (result.decision, result.kind) == ("refuse", "containment")
    assert (await FixGate().check(INTENT, fix())).kind is None
