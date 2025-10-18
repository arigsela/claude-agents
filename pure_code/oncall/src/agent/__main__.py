"""
Entry point for running the agent as a module.

Usage:
    python -m agent.oncall_agent --query "..."
    python -m agent.oncall_agent --incident file.json
    python -m agent.oncall_agent  # Interactive mode
"""

from .oncall_agent import main

if __name__ == "__main__":
    main()
