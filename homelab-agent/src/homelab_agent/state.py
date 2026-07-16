"""The State: one typed dict threaded through every node of the graph.

LangGraph concept — State & reducers:
Each node receives the CURRENT state and returns a PARTIAL update (a dict
with only the keys it changes). LangGraph merges that update into the state.
HOW it merges is per-field:

- Plain fields (question, route, ...) are replaced — last writer wins.
  Safe here because exactly one node writes each of them and the v1 graph
  is strictly sequential (see graph.py).
- Fields annotated with a reducer, like `Annotated[list[str], accumulate]`,
  are MERGED with the reducer instead. A reducer is ANY two-arg merge
  function, not just operator.add — `accumulate` below concatenates lists
  like operator.add does, but also understands `None` as a reset sentinel
  (see its docstring). `checked` and `drift` use it so multiple nodes can
  append to the same field without read-modify-write, AND so a persisted
  checkpointer thread doesn't leak one turn's entries into the next.
"""

from typing import Annotated, Literal

from typing_extensions import TypedDict

# Where orient decided this question should go.
Route = Literal["docs", "live", "ownership"]


def accumulate(old: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for per-turn accumulator fields.

    LangGraph concept — a reducer is ANY two-arg merge function, not just
    operator.add. `None` is our reset sentinel: orient (always the first
    node of a turn) emits it to clear last turn's entries from the thread's
    persisted state, so `checked`/`drift` accumulate within one turn but
    never leak across turns on the same checkpointer thread.
    """
    if new is None:
        return []
    return (old or []) + new


class AgentState(TypedDict, total=False):
    question: str  # the user's question (set once, at invoke)
    route: Route  # written by orient
    plan: str  # short rationale from orient's classifier
    doc_findings: str  # written by retrieve
    live_findings: str  # written by delegate_k8s
    drift: Annotated[list[str], accumulate]  # appended by drift_check
    answer: str  # written by synthesize
    checked: Annotated[list[str], accumulate]  # appended by retrieve/delegate_k8s
