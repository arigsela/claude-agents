"""The State: one typed dict threaded through every node of the graph.

LangGraph concept — State & reducers:
Each node receives the CURRENT state and returns a PARTIAL update (a dict
with only the keys it changes). LangGraph merges that update into the state.
HOW it merges is per-field:

- Plain fields (question, route, ...) are replaced — last writer wins.
  Safe here because exactly one node writes each of them and the v1 graph
  is strictly sequential (see graph.py).
- Fields annotated with a reducer, like `Annotated[list[str], operator.add]`,
  are MERGED with the reducer instead: operator.add concatenates lists, so
  `checked` and `drift` accumulate entries from multiple nodes without any
  node needing to read-modify-write the whole list.
"""

import operator
from typing import Annotated, Literal

from typing_extensions import TypedDict

# Where orient decided this question should go.
Route = Literal["docs", "live", "ownership"]


class AgentState(TypedDict, total=False):
    question: str  # the user's question (set once, at invoke)
    route: Route  # written by orient
    plan: str  # short rationale from orient's classifier
    doc_findings: str  # written by retrieve
    live_findings: str  # written by delegate_k8s
    drift: Annotated[list[str], operator.add]  # appended by drift_check
    answer: str  # written by synthesize
    checked: Annotated[list[str], operator.add]  # appended by retrieve/delegate_k8s
