# Shared utilities used across all services in test-retest-agent
#
# This package contains common code that both the orchestrator and sub-agents
# import. Keeping shared code here prevents duplication and ensures consistency.
#
# Modules:
#   config.py          - Environment variable configuration and constants
#   logging_config.py  - Structured logging setup (text for dev, JSON for K8s)
#   models.py          - Pydantic output models and guardrail validators
#   observability.py   - Callbacks for monitoring agent execution
#   knowledge.py       - Knowledge source auto-discovery and embedder config
