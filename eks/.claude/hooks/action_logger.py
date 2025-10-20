#!/usr/bin/env python3
"""
Action logger hook - Logs all tool usage to audit trail
Captures both Bash commands and MCP tool calls for compliance and debugging
"""
import sys
import json
from datetime import datetime, UTC
import os
from pathlib import Path

# Load .env file if it exists (hooks run as subprocesses, need to load config)
env_file = Path(__file__).parent.parent / '.env'
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

LOG_FILE = "/tmp/claude-k8s-agent-actions.log"

# Check if file logging is enabled (default: true)
# Set LOG_TO_FILE=false in .env to disable audit file (stdout only for Datadog)
LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'


def log_action(tool_name: str, tool_input: dict, tool_use_id: str = None):
    """Log tool action to audit file and/or stderr"""
    # Create log entry
    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool": tool_name,
        "input": tool_input,
        "tool_use_id": tool_use_id
    }

    # Optionally append to log file (disable for Datadog-only setups)
    if LOG_TO_FILE:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')


def format_log_message(tool_name: str, tool_input: dict) -> str:
    """Format log message for stderr output"""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return f"📝 Executing Bash: {cmd[:100]}"

    elif tool_name.startswith("mcp__kubernetes__"):
        # Extract operation details for Kubernetes MCP
        op = tool_name.replace("mcp__kubernetes__", "")
        namespace = tool_input.get("namespace", "default")
        name = tool_input.get("name", "")

        if name:
            return f"📝 Kubernetes MCP: {op} → {namespace}/{name}"
        else:
            return f"📝 Kubernetes MCP: {op} → namespace={namespace}"

    elif tool_name.startswith("mcp__github__"):
        # Extract operation details for GitHub MCP
        op = tool_name.replace("mcp__github__", "")
        repo = tool_input.get("repo", "")
        owner = tool_input.get("owner", "")

        if repo and owner:
            return f"📝 GitHub MCP: {op} → {owner}/{repo}"
        else:
            return f"📝 GitHub MCP: {op}"

    else:
        # Generic tool
        return f"📝 Tool: {tool_name}"


def main():
    try:
        # Read hook input from stdin (SDK passes this as JSON)
        input_data = json.loads(sys.stdin.read())

        tool_name = input_data.get("tool_name")
        tool_input = input_data.get("tool_input", {})
        tool_use_id = input_data.get("tool_use_id")

        # Log to file (audit trail) if enabled
        if LOG_TO_FILE:
            log_action(tool_name, tool_input, tool_use_id)

        # ALWAYS log to stderr for real-time visibility (Datadog captures stderr)
        # Note: stdout is reserved for hook JSON response to SDK
        log_message = format_log_message(tool_name, tool_input)
        print(log_message, file=sys.stderr, flush=True)

        # Allow the action (return empty dict to stdout for SDK)
        print("{}", flush=True)
        return 0

    except Exception as e:
        # Log error but allow operation to avoid blocking everything
        print(f"Error in action logger: {e}", file=sys.stderr)
        print("{}")  # Empty dict = allow
        return 0


if __name__ == "__main__":
    sys.exit(main())
