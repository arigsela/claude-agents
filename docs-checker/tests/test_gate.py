import pytest

from docs_checker.gate import (
    AngleGate,
    RecordingGate,
    Thresholds,
    ToolCallContext,
    angle_degrees,
    render_action,
    render_intent,
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
