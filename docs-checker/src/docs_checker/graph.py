"""What every graph run gets from the executor: its dependencies and its run config.

The docs-checker graph itself is not built yet; until it is, the server serves a
placeholder that refuses every request (``server.placeholder_graph``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docs_checker.gate import FixGate
from docs_checker.ledger import CostLedger
from docs_checker.models import ModelSet
from docs_checker.tools import ToolBelt


@dataclass
class RunDeps:
    """Per-run dependencies, passed as LangGraph runtime context (never checkpointed)."""

    models: ModelSet
    belt: ToolBelt
    ledger: CostLedger
    # One A2A task's memo of completed model replies and tool results. LangGraph
    # re-runs an interrupted node from its start on resume; with the memo the
    # re-run replays that work instead of paying for it (or running a tool)
    # again. None turns it off (each re-run is fresh).
    replay: dict[str, Any] | None = None
    # The last check on every proposed fix (``FixGate.check``) before it reaches the
    # report or a person. The executor passes the one production builds
    # (``gate.build_fix_gate``); left out, it is still the rules gate, never none.
    fix_gate: FixGate = field(default_factory=FixGate)


def run_config(task_id: str, recursion_limit: int) -> dict:
    """One checkpointer thread per A2A task, not per conversation.

    Nothing in a thread should outlive its task: a per-conversation thread would
    carry the last run's state into this one. A HITL resume continues the same
    task, so it finds its paused thread.
    """
    return {"configurable": {"thread_id": task_id}, "recursion_limit": recursion_limit}
