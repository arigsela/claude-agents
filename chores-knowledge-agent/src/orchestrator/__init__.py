# Orchestrator service for chores-knowledge-agent
#
# The orchestrator is the "front door" — it receives user queries via its
# FastAPI API and routes them to the appropriate sub-agent using the A2A
# (Agent-to-Agent) protocol. It does NOT process queries itself; it delegates.
