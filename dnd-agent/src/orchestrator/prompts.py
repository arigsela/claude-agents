# ==============================================================================
# Orchestrator Prompts & Routing Keywords
# ==============================================================================
#
# HOW ROUTING WORKS:
# Instead of using an LLM to classify queries (expensive, slow, non-deterministic),
# we use simple keyword matching. This is the "80/20 rule" — keyword matching
# handles 80% of routing correctly with zero latency and zero cost.
#
# The orchestrator checks if the user's query contains any of the keywords below.
# If it does, the query is routed to the sub-agent. If not, the orchestrator
# returns a helpful message explaining what it can help with.
#
# WHY NOT LLM-BASED ROUTING?
# 1. Zero extra API calls (saves money and latency)
# 2. Deterministic — same input always routes the same way
# 3. Easy to debug — just check which keywords matched
# 4. Easy to extend — just add more keywords to the list
#
# The keywords below were populated from your template parameters.
# Add or remove keywords as you discover new routing patterns.
# ==============================================================================

# Keywords that trigger routing to the sub-agent.
# These are matched case-insensitively against the user's query.
# Populated from template parameter: routingKeywords
ROUTING_KEYWORDS = [
    k.strip().lower()
    for k in "dungeons,dragons,dnd,dm,adventurer,guild".split(",")
    if k.strip()
]

# Fallback message when no keywords match.
# This tells the user what the agent CAN help with, reducing confusion.
NO_MATCH_RESPONSE = (
    "I'm not sure how to help with that specific request. "
    "I'm specialized in topics related to: "
    f"{', '.join(ROUTING_KEYWORDS[:10])}. "
    "Could you rephrase your question or ask about one of these topics?"
)

