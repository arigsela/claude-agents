#!/usr/bin/env python3
"""
Safety validator hook - Blocks dangerous Kubernetes and GitHub operations
Validates both Bash commands and MCP tool calls
"""
import sys
import json
import re

# Dangerous Bash command patterns to block
DANGEROUS_BASH_PATTERNS = [
    r'kubectl\s+delete\s+namespace',
    r'kubectl\s+delete\s+pv\b',
    r'kubectl\s+delete.*--all-namespaces',
    r'kubectl\s+delete.*-A\b',
    r'rm\s+-rf\s+/',
]

# Protected Kubernetes namespaces
PROTECTED_NAMESPACES = ['kube-system', 'kube-public', 'kube-node-lease','artemis-preprod', 'preprod', 'artemis-prod', 'prod']

# Dangerous MCP operations (complete blocks - these are NEVER allowed)
DANGEROUS_MCP_OPERATIONS = [
    'mcp__kubernetes__namespaces_delete',  # Namespace deletion always blocked
    # Note: resources_delete is validated separately based on kind and namespace
]

# Dangerous resource types to delete
PROTECTED_RESOURCE_KINDS = [
    'Namespace',
    'PersistentVolume',
    'PersistentVolumeClaim',
    'ClusterRole',
    'ClusterRoleBinding',
]


def validate_bash_command(command: str) -> dict:
    """Validate Bash commands for dangerous patterns"""
    # Check for dangerous patterns
    for pattern in DANGEROUS_BASH_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"🚫 BLOCKED: Dangerous command pattern detected\n"
                        f"Pattern: {pattern}\n"
                        f"Command: {command}\n"
                        f"This operation could damage the cluster and is not allowed."
                    )
                }
            }

    # Extra validation for operations on protected namespaces
    for ns in PROTECTED_NAMESPACES:
        if f'-n {ns}' in command or f'--namespace={ns}' in command or f'--namespace {ns}' in command:
            if 'delete' in command.lower():
                print(
                    f"⚠️ WARNING: Delete operation on protected namespace '{ns}': {command}",
                    file=sys.stderr
                )

    return {}  # Allow


def validate_mcp_tool(tool_name: str, tool_input: dict) -> dict:
    """Validate MCP tool calls for dangerous operations"""

    # Block dangerous MCP operations entirely
    if tool_name in DANGEROUS_MCP_OPERATIONS:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"🚫 BLOCKED: Dangerous MCP operation\n"
                    f"Tool: {tool_name}\n"
                    f"This operation is not allowed by safety policy."
                )
            }
        }

    # Validate Kubernetes MCP operations
    if tool_name.startswith('mcp__kubernetes__'):
        namespace = tool_input.get('namespace', '')

        # Block all delete operations in protected namespaces
        if 'delete' in tool_name.lower() and namespace in PROTECTED_NAMESPACES:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"🚫 BLOCKED: Cannot delete resources in protected namespace\n"
                        f"Tool: {tool_name}\n"
                        f"Namespace: {namespace}\n"
                        f"Protected namespaces: {', '.join(PROTECTED_NAMESPACES)}"
                    )
                }
            }

        # Block deletion of protected resource types
        if tool_name == 'mcp__kubernetes__resources_delete':
            kind = tool_input.get('kind', '')
            if kind in PROTECTED_RESOURCE_KINDS:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"🚫 BLOCKED: Cannot delete protected resource type\n"
                            f"Resource Kind: {kind}\n"
                            f"Protected types: {', '.join(PROTECTED_RESOURCE_KINDS)}"
                        )
                    }
                }

        # Block pod deletion in protected namespaces
        if tool_name == 'mcp__kubernetes__pods_delete':
            if namespace in PROTECTED_NAMESPACES:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"🚫 BLOCKED: Cannot delete pods in protected namespace\n"
                            f"Namespace: {namespace}\n"
                            f"Use rolling restart via deployment annotation instead."
                        )
                    }
                }

        # Block operations with all_namespaces for destructive operations
        if 'delete' in tool_name.lower() and tool_input.get('all_namespaces', False):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"🚫 BLOCKED: Bulk deletion across all namespaces not allowed\n"
                        f"Tool: {tool_name}"
                    )
                }
            }

        # Warn on operations in protected namespaces (even non-destructive)
        if namespace in PROTECTED_NAMESPACES and not tool_name.endswith('_get') and not tool_name.endswith('_list'):
            print(
                f"⚠️ WARNING: Modification on protected namespace '{namespace}': {tool_name}",
                file=sys.stderr
            )

    # Validate GitHub MCP operations
    if tool_name.startswith('mcp__github__'):
        # Block operations that could expose credentials
        if tool_name in ['mcp__github__create_or_update_file', 'mcp__github__push_files']:
            files = tool_input.get('files', [])
            path = tool_input.get('path', '')

            # Check for credential file patterns
            dangerous_patterns = ['secret', 'credential', '.env', 'token', 'password', 'key']

            # Check single file path
            if path and any(pattern in path.lower() for pattern in dangerous_patterns):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"🚫 BLOCKED: Cannot commit files that may contain secrets\n"
                            f"File: {path}\n"
                            f"This could expose credentials in version control."
                        )
                    }
                }

            # Check multiple files
            for file in files:
                file_path = file.get('path', '')
                if any(pattern in file_path.lower() for pattern in dangerous_patterns):
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                f"🚫 BLOCKED: Cannot commit files that may contain secrets\n"
                                f"File: {file_path}\n"
                                f"This could expose credentials in version control."
                            )
                        }
                    }

    return {}  # Allow


def main():
    try:
        # Read hook input from stdin (SDK passes this as JSON)
        input_data = json.loads(sys.stdin.read())

        tool_name = input_data.get("tool_name")
        tool_input = input_data.get("tool_input", {})

        # Validate based on tool type
        if tool_name == "Bash":
            command = tool_input.get("command", "")
            result = validate_bash_command(command)
        elif tool_name and tool_name.startswith("mcp__"):
            result = validate_mcp_tool(tool_name, tool_input)
        else:
            # Allow other tools (Read, Write, Grep, etc.)
            result = {}

        # Print result to stdout (SDK reads this)
        print(json.dumps(result))
        return 0

    except Exception as e:
        # Log error but allow operation to avoid blocking everything
        print(f"Error in safety validator: {e}", file=sys.stderr)
        print("{}")  # Empty dict = allow
        return 0


if __name__ == "__main__":
    sys.exit(main())
