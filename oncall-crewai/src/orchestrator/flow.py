"""Orchestrator Flow -- routes queries to specialist agents.

Uses CrewAI Flow with @start, @router, and @listen for deterministic
routing based on keyword classification. Delegates to K8s and GitHub
agents via A2A protocol through delegate agents.

Includes @persist for crash recovery and enriched delegate tasks.
"""

import concurrent.futures
import uuid

from crewai import Crew, Task
from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, Field

from orchestrator.agents import create_github_delegate, create_k8s_delegate
from orchestrator.prompts import GITHUB_KEYWORDS, K8S_KEYWORDS
from shared.config import CREWAI_VERBOSE
from shared.logging_config import setup_logging
from shared.observability import log_token_usage, task_completion_callback

logger = setup_logging("orchestrator-flow")

# Try to import @persist for flow resilience; degrade gracefully if unavailable
try:
    from crewai.flow.persistence import persist as _persist

    _HAS_PERSIST = True
except ImportError:
    _HAS_PERSIST = False


class OncallFlowState(BaseModel):
    """State tracked across the flow."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str = ""
    route: str = ""
    k8s_result: str = ""
    github_result: str = ""
    final_result: str = ""


def classify_query(query: str) -> str:
    """Classify a query into a route based on keyword matching.

    Returns one of: "k8s", "github", "combined", "k8s" (default).
    """
    query_lower = query.lower()

    k8s_score = sum(1 for kw in K8S_KEYWORDS if kw in query_lower)
    github_score = sum(1 for kw in GITHUB_KEYWORDS if kw in query_lower)

    if k8s_score > 0 and github_score > 0:
        return "combined"
    elif github_score > 0:
        return "github"
    else:
        # Default to K8s for unclassified queries (most oncall queries are K8s)
        return "k8s"


# Build the Flow class -- apply @persist decorator if available
def _build_flow_class():
    class _OncallFlow(Flow[OncallFlowState]):
        """Main orchestrator flow that routes to specialist agents."""

        initial_state = OncallFlowState

        @start()
        def classify(self):
            """Classify the incoming query and determine routing."""
            query = self.state.query
            route = classify_query(query)
            self.state.route = route
            logger.info(f"Query classified: route={route}, query={query[:80]}...")
            return route

        @router(classify)
        def route_query(self):
            """Route to the appropriate handler based on classification."""
            return self.state.route

        @listen("k8s")
        def handle_k8s(self):
            """Handle K8s-only queries."""
            logger.info("Routing to K8s agent")
            result = self._invoke_k8s(self.state.query)
            self.state.k8s_result = result
            self.state.final_result = result
            return result

        @listen("github")
        def handle_github(self):
            """Handle GitHub-only queries."""
            logger.info("Routing to GitHub agent")
            result = self._invoke_github(self.state.query)
            self.state.github_result = result
            self.state.final_result = result
            return result

        @listen("combined")
        def handle_combined(self):
            """Handle queries requiring both K8s and GitHub investigation."""
            logger.info("Routing to both K8s and GitHub agents")

            # K8s first for diagnostics
            k8s_result = self._invoke_k8s(self.state.query)
            self.state.k8s_result = k8s_result

            # GitHub with K8s context
            combined_query = (
                f"{self.state.query}\n\n"
                f"K8s investigation results:\n{k8s_result}"
            )
            github_result = self._invoke_github(combined_query)
            self.state.github_result = github_result

            # Synthesize
            self.state.final_result = (
                f"## K8s Diagnostics\n{k8s_result}\n\n"
                f"## GitOps Analysis\n{github_result}"
            )
            return self.state.final_result

        def _invoke_k8s(self, query: str) -> str:
            """Invoke the K8s delegate agent via A2A."""
            try:
                agent = create_k8s_delegate()
                task = Task(
                    description=(
                        f"Delegate the following Kubernetes investigation to the "
                        f"remote K8s specialist agent and return their complete "
                        f"findings:\n\n{query}\n\n"
                        f"Ensure the response includes: service identification, "
                        f"current state, root cause analysis, priority level, "
                        f"and remediation steps."
                    ),
                    expected_output=(
                        "A structured diagnosis with: service/namespace identified, "
                        "pod status and errors, root cause analysis, P0/P1/P2 priority, "
                        "and actionable remediation commands."
                    ),
                    agent=agent,
                )
                crew = Crew(
                    agents=[agent],
                    tasks=[task],
                    verbose=CREWAI_VERBOSE,
                    output_log_file=True,
                    task_callback=task_completion_callback,
                )
                # Run in a separate thread -- flow.kickoff() already owns the event
                # loop, and crew.kickoff() needs its own via asyncio.run().
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(crew.kickoff).result()
                log_token_usage(result, agent_name="k8s-delegate")
                return result.raw if hasattr(result, "raw") else str(result)
            except Exception as e:
                logger.error(f"K8s delegation failed: {e}")
                return f"K8s agent error: {e}"

        def _invoke_github(self, query: str) -> str:
            """Invoke the GitHub delegate agent via A2A."""
            try:
                agent = create_github_delegate()
                task = Task(
                    description=(
                        f"Delegate the following GitOps request to the remote "
                        f"GitHub specialist agent and return their complete "
                        f"findings:\n\n{query}\n\n"
                        f"Ensure the response includes: specific file paths or "
                        f"deployment details found, any proposed changes with "
                        f"YAML diffs, and clear next steps."
                    ),
                    expected_output=(
                        "A detailed GitOps analysis with: manifest content or "
                        "directory listings, deployment history if relevant, "
                        "proposed changes with YAML diffs for PR creation, "
                        "and actionable next steps."
                    ),
                    agent=agent,
                )
                crew = Crew(
                    agents=[agent],
                    tasks=[task],
                    verbose=CREWAI_VERBOSE,
                    output_log_file=True,
                    task_callback=task_completion_callback,
                )
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(crew.kickoff).result()
                log_token_usage(result, agent_name="github-delegate")
                return result.raw if hasattr(result, "raw") else str(result)
            except Exception as e:
                logger.error(f"GitHub delegation failed: {e}")
                return f"GitHub agent error: {e}"

    return _OncallFlow


# Apply @persist if available, otherwise use the plain class
_FlowClass = _build_flow_class()
if _HAS_PERSIST:
    try:
        OncallFlow = _persist()(_FlowClass)
        logger.info("Flow persistence enabled")
    except Exception as e:
        logger.warning(f"Failed to enable flow persistence: {e}")
        OncallFlow = _FlowClass
else:
    logger.info("Flow persistence not available (crewai.flow.persistence not found)")
    OncallFlow = _FlowClass
