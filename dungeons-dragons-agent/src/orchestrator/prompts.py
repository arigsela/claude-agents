# ==============================================================================
# Orchestrator Prompts & Routing Keywords
# ==============================================================================

# Keywords that trigger routing to the sub-agent.
# These are matched case-insensitively against the user's query.
ROUTING_KEYWORDS = [
    k.strip().lower()
    for k in "dnd,dungeons,dragons, quest,character,journey,npc,campaign".split(",")
    if k.strip()
]

