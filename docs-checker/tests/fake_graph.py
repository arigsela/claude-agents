"""A minimal graph for the executor's plumbing tests. It stands in for the product graph.

    START --Send per line of the question--> worker (x1..n) -> finish -> END

- ``worker`` is a model loop. Each model reply is memoized in the task's replay
  memo (``RunDeps.replay``) under a key that survives a re-run, and every tool
  call goes through ``ToolBelt.call`` (authorize, gate, invoke) with the same
  memo. A gate "ask" pauses the branch through ``interrupt()``; on resume
  LangGraph re-runs the worker from its start and the memo replays what it
  already has, so no model call is paid twice and no tool runs twice.
- Each line of the question is one branch: a two-line question runs two
  parallel ``Send`` branches that can both pause, which the executor reports as
  one HITL request. A line ``catalog: ...`` gets the catalog tools; any other
  line (or ``docs: ...``) gets the docs tools.
- ``finish`` answers ``TEST_ANSWER``. The outcome is "verified" when every tool
  call ran and returned, else "unverified".
"""

from __future__ import annotations

import hashlib
import json
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from docs_checker.gate import render_intent
from docs_checker.graph import RunDeps
from docs_checker.llm import call_model
from docs_checker.prompts import AGENT_DESCRIPTION, system_message
from docs_checker.tools import SPECIALIST_TOOLS, ToolEvent

TEST_ANSWER = "The test graph finished every branch."
MODEL_NODE = "worker"  # tests script it as FakeModels(worker=...)
MAX_STEPS = 8


class FakeState(TypedDict, total=False):
    question: str
    events: Annotated[list[ToolEvent], operator.add]
    answer: str
    outcome: str


class Branch(TypedDict):
    question: str
    specialist: str
    task: str


def fan_out(state: FakeState) -> list[Send]:
    sends = []
    for line in (state.get("question") or "").splitlines():
        scope, sep, rest = line.partition(":")
        if sep and scope.strip() in SPECIALIST_TOOLS:
            specialist, task = scope.strip(), rest.strip()
        else:
            specialist, task = "docs", line.strip()
        if task:
            branch = Branch(question=state["question"], specialist=specialist, task=task)
            sends.append(Send("worker", branch))
    return sends


async def worker(state: Branch, runtime: Runtime[RunDeps]) -> dict:
    deps = runtime.context
    specialist = state["specialist"]
    model = deps.models.get(MODEL_NODE).bind_tools(deps.belt.tools_for(specialist))
    intent = render_intent(AGENT_DESCRIPTION, state["question"])
    ask = json.dumps({"specialist": specialist, "task": state["task"]})
    messages: list[Any] = [system_message("Plumbing test worker.", cache=True), HumanMessage(ask)]
    branch_key = hashlib.sha256(ask.encode()).hexdigest()[:16]
    events: list[ToolEvent] = []
    for step in range(MAX_STEPS):
        memo_key = f"model:{MODEL_NODE}:{branch_key}:{step}"
        reply = deps.replay.get(memo_key) if deps.replay is not None else None
        if reply is None:
            reply = await call_model(
                model,
                messages,
                node=MODEL_NODE,
                model_name=deps.models.name(MODEL_NODE),
                ledger=deps.ledger,
            )
            if deps.replay is not None:
                deps.replay[memo_key] = reply
        messages.append(reply)
        if not reply.tool_calls:
            break
        for call in reply.tool_calls:
            text, event = await deps.belt.call(
                call["name"],
                call.get("args") or {},
                specialist=specialist,
                intent=intent,
                workflow=specialist,
                memo=deps.replay,
            )
            events.append(event)
            messages.append(ToolMessage(content=text, tool_call_id=call["id"]))
    return {"events": events}


async def finish(state: FakeState) -> dict:
    ran = all(event["ok"] for event in state.get("events") or [])
    return {"answer": TEST_ANSWER, "outcome": "verified" if ran else "unverified"}


def build_test_graph(checkpointer: Any = None):
    graph = StateGraph(FakeState, context_schema=RunDeps)
    graph.add_node("worker", worker)
    graph.add_node("finish", finish)
    graph.add_conditional_edges(START, fan_out, ["worker"])
    graph.add_edge("worker", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
