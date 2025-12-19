"""
mem0 configuration for oncall agent
Defines categories and custom instructions for memory filtering
"""

# Custom categories for incident memories
MEMORY_CATEGORIES = [
    {
        "name": "incidents",
        "description": "Kubernetes incidents, root causes, and resolutions"
    },
    {
        "name": "aws_resources",
        "description": "AWS resource relationships and dependencies"
    },
    {
        "name": "github_deploys",
        "description": "GitHub deployment correlations and impact patterns"
    },
    {
        "name": "troubleshooting",
        "description": "Investigation patterns and successful diagnostic steps"
    }
]

# Custom instructions - what to extract from conversations
CUSTOM_INSTRUCTIONS = """
Extract and remember from oncall troubleshooting conversations:

1. **Incident patterns:**
   - Pod crash loops with identified root causes
   - OOMKilled events and actual memory requirements needed
   - ImagePullBackOff issues and registry/secret problems
   - Deployment failures and configuration errors
   - Service degradation patterns and correlations

2. **AWS resource relationships:**
   - Load Balancer -> Target Group -> Pod mappings
   - EBS volume attachment issues
   - IAM role permission problems
   - Security group blocking patterns

3. **GitHub deployment impacts:**
   - Deployments that caused incidents
   - Config changes that resolved issues
   - Correlation between code changes and pod behavior

4. **Successful troubleshooting patterns:**
   - Diagnostic commands that revealed root cause
   - Log patterns that indicated specific issues
   - Resolution steps that worked
   - Time-to-resolution for different incident types

5. **Service dependencies:**
   - Which services depend on each other
   - Critical path services (must stay up)
   - Known recurring issues per service

**EXCLUDE from memory:**
- Health check queries when all systems green
- Generic "status" or "how do I" questions
- Test queries during development (contains "test" keyword)
- Casual conversation or greetings
- Temporary network blips lasting < 1 minute
- Expected pod restarts during normal deployments
- Informational queries about documentation

**Memory expiration rules:**
- Incident investigations: Keep for 90 days
- Temporary issues (networking blips): Keep for 7 days
- Permanent patterns (service dependencies): No expiration
"""

# Memory search filters by context
SEARCH_FILTERS = {
    "incident": {
        "categories": {"in": ["incidents", "troubleshooting"]}
    },
    "aws": {
        "categories": {"in": ["aws_resources"]}
    },
    "deployment": {
        "categories": {"in": ["github_deploys"]}
    },
    "all": {}  # No filters, search everything
}

# Expiration periods (in days)
EXPIRATION_PERIODS = {
    "incident": 90,        # Keep incident memories for 3 months
    "temporary": 7,        # Short-lived issues expire quickly
    "permanent": None,     # Service dependencies never expire
}
