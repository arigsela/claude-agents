#!/usr/bin/env python3
"""
Microsoft Teams notifier hook - Sends notifications for critical Kubernetes events
Alerts team about cluster operations via Microsoft Teams webhooks
"""
import sys
import json
import os
import requests
from datetime import datetime

TEAMS_WEBHOOK = os.getenv('TEAMS_WEBHOOK_URL', '')
TEAMS_ENABLED = os.getenv('TEAMS_NOTIFICATIONS_ENABLED', 'true').lower() == 'true'


def send_teams_notification(title: str, message: str, severity: str = "info"):
    """Send notification to Microsoft Teams channel"""
    if not TEAMS_WEBHOOK or not TEAMS_ENABLED:
        return

    # Teams uses themeColor for message styling
    colors = {
        "critical": "FF0000",  # Red
        "warning": "FFA500",   # Orange
        "info": "36A64F",      # Green
        "success": "36A64F"    # Green
    }

    # Microsoft Teams Adaptive Card format
    payload = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": colors.get(severity, colors["info"]),
        "title": f"🤖 EKS Monitoring Agent - {title}",
        "text": message,
        "potentialAction": []
    }

    try:
        response = requests.post(TEAMS_WEBHOOK, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Teams notification: {e}", file=sys.stderr)


def format_kubernetes_operation(tool_name: str, tool_input: dict) -> tuple[str, str, str]:
    """
    Format Kubernetes MCP operation for Teams notification
    Returns: (title, message, severity)
    """
    op = tool_name.replace("mcp__kubernetes__", "")
    namespace = tool_input.get("namespace", "N/A")
    name = tool_input.get("name", "")
    kind = tool_input.get("kind", "")

    if "delete" in op.lower():
        if name:
            title = "🗑️ Resource Deletion"
            message = f"**Operation:** {op}\n\n**Resource:** {kind} `{namespace}/{name}`"
            severity = "warning"
        else:
            title = "🗑️ Bulk Deletion"
            message = f"**Operation:** {op}\n\n**Namespace:** `{namespace}`"
            severity = "critical"

    elif op == "resources_create_or_update":
        # Check if this is a rolling restart (restart annotation)
        resource_yaml = tool_input.get("resource", "")
        if "kubectl.kubernetes.io/restartedAt" in resource_yaml:
            title = "🔄 Deployment Restart"
            # Try to extract deployment name from YAML
            import re
            name_match = re.search(r'name:\s*(\S+)', resource_yaml)
            ns_match = re.search(r'namespace:\s*(\S+)', resource_yaml)
            dep_name = name_match.group(1) if name_match else "unknown"
            dep_ns = ns_match.group(1) if ns_match else namespace
            message = f"**Deployment:** `{dep_ns}/{dep_name}`\n\n**Action:** Rolling restart via annotation patch\n\n**Impact:** Zero-downtime rolling update"
            severity = "warning"
        else:
            title = "⚙️ Resource Update"
            message = f"**Operation:** {op}\n\n**Namespace:** `{namespace}`"
            severity = "info"

    elif op == "pods_exec":
        title = "⚡ Pod Exec"
        command = tool_input.get("command", [])
        message = f"**Pod:** `{namespace}/{name}`\n\n**Command:** `{' '.join(command)}`"
        severity = "warning"

    elif (op.startswith("resources_list") or
          op.startswith("pods_list") or
          op.startswith("nodes_list") or
          op.startswith("events_list") or
          op.startswith("pods_top") or
          op.startswith("pods_log") or
          op.endswith("_get") or
          op.endswith("_list")):
        # Read-only operations - don't notify (monitoring/diagnostics)
        return None, None, None

    else:
        title = f"🔧 Cluster Operation"
        message = f"**Operation:** {op}\n\n**Namespace:** `{namespace}`"
        severity = "info"

    return title, message, severity


def format_github_operation(tool_name: str, tool_input: dict) -> tuple[str, str, str]:
    """
    Format GitHub MCP operation for Teams notification
    Returns: (title, message, severity)
    """
    op = tool_name.replace("mcp__github__", "")
    owner = tool_input.get("owner", "")
    repo = tool_input.get("repo", "")

    if op == "create_issue":
        title = "🐛 GitHub Issue Created"
        issue_title = tool_input.get("title", "N/A")
        labels = tool_input.get("labels", [])
        message = f"**Repository:** `{owner}/{repo}`\n\n**Issue:** {issue_title}\n\n**Labels:** {', '.join(labels) if labels else 'None'}"
        severity = "info"

    elif op == "create_pull_request":
        title = "🔀 Pull Request Created"
        pr_title = tool_input.get("title", "N/A")
        head = tool_input.get("head", "")
        base = tool_input.get("base", "main")
        message = f"**Repository:** `{owner}/{repo}`\n\n**PR:** {pr_title}\n\n**Branch:** `{head}` → `{base}`"
        severity = "info"

    elif op == "update_issue":
        state = tool_input.get("state", "")
        if state == "closed":
            title = "✅ Issue Closed"
            issue_num = tool_input.get("issue_number", "N/A")
            message = f"**Repository:** `{owner}/{repo}`\n\n**Issue:** #{issue_num}\n\n**Status:** Closed"
            severity = "success"
        else:
            return None, None, None

    elif (op.startswith("list_") or
          op.startswith("get_") or
          op.startswith("search_") or
          op.endswith("_list") or
          op.endswith("_get")):
        # Read-only operations - don't notify (queries/searches)
        return None, None, None

    else:
        title = f"📝 GitHub Operation"
        message = f"**Operation:** {op}\n\n**Repository:** `{owner}/{repo}`"
        severity = "info"

    return title, message, severity


def main():
    try:
        # Read hook input from stdin (SDK passes this as JSON)
        input_data = json.loads(sys.stdin.read())

        tool_name = input_data.get("tool_name")
        tool_input = input_data.get("tool_input", {})

        # Process based on tool type
        title = message = severity = None

        if tool_name == "Bash":
            cmd = tool_input.get("command", "")

            # Notify on specific Kubernetes operations
            if "kubectl delete" in cmd:
                title = "🗑️ Kubectl Deletion"
                message = f"**Command:**\n```\n{cmd}\n```"
                severity = "warning"

            elif "kubectl scale" in cmd:
                title = "📊 Kubectl Scaling"
                message = f"**Command:**\n```\n{cmd}\n```"
                severity = "info"

            elif "kubectl rollout restart" in cmd:
                title = "🔄 Kubectl Restart"
                message = f"**Command:**\n```\n{cmd}\n```"
                severity = "warning"

        elif tool_name.startswith("mcp__kubernetes__"):
            title, message, severity = format_kubernetes_operation(tool_name, tool_input)

        elif tool_name.startswith("mcp__github__"):
            title, message, severity = format_github_operation(tool_name, tool_input)

        elif tool_name.startswith("mcp__atlassian__"):
            # Only notify on Jira ticket creation/updates, not searches
            op = tool_name.replace("mcp__atlassian__", "")
            if op == "jira_create_issue":
                title = "🎫 Jira Ticket Created"
                summary = tool_input.get("summary", "N/A")
                message = f"**Summary:** {summary}\n\n**Project:** {tool_input.get('project_key', 'N/A')}"
                severity = "info"
            elif op == "jira_add_comment":
                # Skip comment notifications (too noisy)
                title, message, severity = None, None, None
            elif op.startswith("jira_search") or op.startswith("jira_get"):
                # Read-only operations - don't notify
                title, message, severity = None, None, None
            else:
                # Other Jira operations (transitions, updates)
                title, message, severity = None, None, None

        # Send notification if applicable
        if title and message and severity:
            send_teams_notification(title, message, severity)

        # Always allow the action (return empty dict)
        print("{}")
        return 0

    except Exception as e:
        # Log error but allow operation to avoid blocking everything
        print(f"Error in teams notifier: {e}", file=sys.stderr)
        print("{}")  # Empty dict = allow
        return 0


if __name__ == "__main__":
    sys.exit(main())
