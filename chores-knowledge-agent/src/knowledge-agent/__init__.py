# Chores Tracker Knowledge Specialist — Sub-agent for chores-knowledge-agent
#
# This is an independently deployable CrewAI agent that communicates with
# the orchestrator via the A2A (Agent-to-Agent) protocol.
#
# It has its own:
# - FastAPI server (server.py) with A2A endpoints
# - CrewAI agent with tools and knowledge (agent.py)
# - A2A executor bridge (executor.py)
# - Domain-specific tools (tools.py)
