# ==============================================================================
# Orchestrator Flow — Query Classification & Routing
# ==============================================================================
#
# WHAT IS A CREWAI FLOW?
# A Flow is a deterministic state machine that orchestrates agent execution.
# Unlike a Crew (which runs tasks sequentially or hierarchically), a Flow
# gives you explicit control over the execution order via decorators:
#
#   @start()   — marks the first method to run
#   @router()  — returns a route name that determines which method runs next
#   @listen()  — runs when a specific route is selected
#
# WHY USE A FLOW INSTEAD OF A CREW?
# The orchestrator's job is routing, not reasoning. A Flow gives us:
# 1. Deterministic execution (keyword match → route → delegate)
# 2. Zero LLM calls for routing (no wasted tokens on classification)
# 3. Clear state management (OrchestratorFlowState tracks the full lifecycle)
# 4. Easy to extend (add new @listen methods for new sub-agents)
#
# EXECUTION SEQUENCE:
#   classify() → route_query() → handle_sub_agent() OR handle_no_match()
# ==============================================================================

import concurrent.futures

from crewai import Crew, Task
from crewai.flow.flow import Flow, start, router, listen
from pydantic import BaseModel

from orchestrator.agents import create_sub_agent_delegate
from orchestrator.prompts import ROUTING_KEYWORDS, NO_MATCH_RESPONSE
from shared.logging_config import setup_logging

logger = setup_logging("orchestrator.flow")


class OrchestratorFlowState(BaseModel):
    """
    State that persists across all steps in the flow.

    Each @start/@router/@listen method can read and write to this state.
    The state is created fresh for each flow.kickoff() call.
    """
    query: str = ""               # The user's original query
    route: str = ""               # Which route was selected: "sub_agent" or "no_match"
    result: str = ""              # The final response to return to the user


class OrchestratorFlow(Flow[OrchestratorFlowState]):
    """
    Routes incoming queries to the appropriate sub-agent.

    The flow uses keyword matching (not LLM) for fast, deterministic routing.
    """

    @start()
    def classify(self) -> str:
        """
        Step 1: Classify the query by checking for keyword matches.

        This is the first method that runs (marked with @start).
        It reads the query from state and checks if any routing keywords appear in it.

        Returns:
            A classification label used by the router.
        """
        query_lower = self.state.query.lower()

        # Count how many keywords match — more matches = higher confidence
        matches = [kw for kw in ROUTING_KEYWORDS if kw in query_lower]

        if matches:
            logger.info(f"Keyword match: {matches[:5]} → routing to sub-agent")
            self.state.route = "sub_agent"
            return "sub_agent"
        else:
            logger.info("No keyword match → returning fallback response")
            self.state.route = "no_match"
            return "no_match"

    @router(classify)
    def route_query(self) -> str:
        """
        Step 2: Route based on the classification result.

        Reads state.route (set by classify) and returns the route name,
        which determines which @listen method runs next.

        Returns:
            Route name: "sub_agent" or "no_match"
        """
        return self.state.route or "no_match"

    @listen("sub_agent")
    def handle_sub_agent(self) -> str:
        """
        Step 3a: Delegate the query to the sub-agent via A2A.

        This runs when route_query() returns "sub_agent".
        It creates a delegate agent and runs a single-task Crew to invoke it.

        IMPORTANT: crew.kickoff() is run in a ThreadPoolExecutor because
        flow.kickoff() already owns the event loop (via asyncio.run()),
        and crew.kickoff() also calls asyncio.run() internally. Running
        in a separate thread gives it its own event loop.
        """
        logger.info(f"Delegating to sub-agent: {self.state.query[:100]}")

        try:
            # Create the A2A delegate agent
            delegate = create_sub_agent_delegate()

            # Create a task for the delegate — it will forward to the sub-agent via A2A
            task = Task(
                description=self.state.query,
                expected_output="A complete and helpful response to the user's query.",
                agent=delegate,
            )

            # Run the crew (single agent, single task)
            crew = Crew(agents=[delegate], tasks=[task], verbose=True)

            # Run in a separate thread to avoid nested asyncio.run() conflict
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(crew.kickoff).result()

            self.state.result = result.raw if hasattr(result, "raw") else str(result)
        except Exception as e:
            logger.error(f"Sub-agent delegation failed: {e}")
            self.state.result = f"Agent error: {e}"

        return self.state.result

    @listen("no_match")
    def handle_no_match(self) -> str:
        """
        Step 3b: Return a helpful fallback when no keywords match.

        This runs when route_query() returns "no_match".
        Instead of failing, it tells the user what topics the agent can help with.
        """
        self.state.result = NO_MATCH_RESPONSE
        return self.state.result

