# ==============================================================================
# Orchestrator Flow — Query Classification & Routing
# ==============================================================================

import concurrent.futures
import uuid

from crewai import Crew, Task
from crewai.flow.flow import Flow, start, router, listen
from pydantic import BaseModel, Field

from orchestrator.agents import create_sub_agent_delegate
from orchestrator.prompts import ROUTING_KEYWORDS
from shared.config import CREWAI_VERBOSE, SINGLE_AGENT_BYPASS
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator.flow")

# Try to import @persist for flow resilience; degrade gracefully if unavailable
try:
    from crewai.flow.persistence import persist as _persist
    _HAS_PERSIST = True
except ImportError:
    _HAS_PERSIST = False


class OrchestratorFlowState(BaseModel):
    """State that persists across all steps in the flow."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    route: str = ""
    result: str = ""


def classify_query(query: str) -> str:
    """Classify a query into a route based on keyword matching.

    Returns "sub_agent" if keywords match or SINGLE_AGENT_BYPASS is enabled.
    """
    if SINGLE_AGENT_BYPASS:
        return "sub_agent"

    query_lower = query.lower()
    matches = [kw for kw in ROUTING_KEYWORDS if kw in query_lower]
    if matches:
        logger.info(f"Keyword match: {matches[:5]} → routing to sub-agent")
    else:
        logger.info("No keyword match → defaulting to sub-agent")
    return "sub_agent"


def _build_flow_class():
    class _OrchestratorFlow(Flow[OrchestratorFlowState]):
        """Routes incoming queries to the appropriate sub-agent."""

        initial_state = OrchestratorFlowState

        @start()
        def classify(self) -> str:
            query = self.state.query
            route = classify_query(query)
            self.state.route = route
            logger.info(f"Query classified: route={route}, query={query[:80]}...")
            return route

        @router(classify)
        def route_query(self) -> str:
            return self.state.route or "sub_agent"

        @listen("sub_agent")
        def handle_sub_agent(self) -> str:
            logger.info(f"Delegating to sub-agent: {self.state.query[:100]}")
            try:
                delegate = create_sub_agent_delegate()
                task = Task(
                    description=self.state.query,
                    expected_output="A complete and helpful response to the user's query.",
                    agent=delegate,
                )
                crew = Crew(
                    agents=[delegate],
                    tasks=[task],
                    verbose=CREWAI_VERBOSE,
                    output_log_file="/tmp/crewai-logs.txt",
                )
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(crew.kickoff).result()
                raw = result.raw if hasattr(result, "raw") else str(result)
                self.state.result = raw.replace("\\n", "\n")
            except Exception as e:
                logger.error(f"Sub-agent delegation failed: {e}")
                self.state.result = f"Agent error: {e}"
            return self.state.result

    return _OrchestratorFlow


# Apply @persist if available
_FlowClass = _build_flow_class()
if _HAS_PERSIST:
    try:
        OrchestratorFlow = _persist()(_FlowClass)
        logger.info("Flow persistence enabled")
    except Exception as e:
        logger.warning(f"Failed to enable flow persistence: {e}")
        OrchestratorFlow = _FlowClass
else:
    logger.info("Flow persistence not available")
    OrchestratorFlow = _FlowClass

