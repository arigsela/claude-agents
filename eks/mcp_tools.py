"""
SDK MCP Tools for Kubernetes and GitHub operations
Uses @tool decorator for in-process MCP servers
"""
import subprocess
import json
from typing import Any
from claude_agent_sdk import tool

# ============================================================================
# Kubernetes Tools
# ============================================================================

@tool("kubernetes_pods_list", "List pods in a namespace or across all namespaces", {
    "namespace": str,
    "label_selector": str
})
async def kubernetes_pods_list(args: dict[str, Any]) -> dict[str, Any]:
    """List pods in a namespace or across all namespaces."""
    namespace = args.get("namespace")
    label_selector = args.get("label_selector")

    cmd = ["kubectl", "get", "pods", "-o", "json"]

    if namespace:
        cmd.extend(["-n", namespace])
    else:
        cmd.append("--all-namespaces")

    if label_selector:
        cmd.extend(["-l", label_selector])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except subprocess.CalledProcessError as e:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e), "stderr": e.stderr})
            }],
            "is_error": True
        }

@tool("kubernetes_pods_get", "Get details of a specific pod", {
    "name": str,
    "namespace": str
})
async def kubernetes_pods_get(args: dict[str, Any]) -> dict[str, Any]:
    """Get details of a specific pod."""
    name = args["name"]
    namespace = args["namespace"]

    cmd = ["kubectl", "get", "pod", name, "-n", namespace, "-o", "json"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except subprocess.CalledProcessError as e:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e), "stderr": e.stderr})
            }],
            "is_error": True
        }

@tool("kubernetes_pods_logs", "Get logs from a pod", {
    "name": str,
    "namespace": str,
    "tail": int,
    "previous": bool
})
async def kubernetes_pods_logs(args: dict[str, Any]) -> dict[str, Any]:
    """Get logs from a pod."""
    name = args["name"]
    namespace = args["namespace"]
    tail = args.get("tail", 100)
    previous = args.get("previous", False)

    cmd = ["kubectl", "logs", name, "-n", namespace, f"--tail={tail}"]

    if previous:
        cmd.append("--previous")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except subprocess.CalledProcessError as e:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e), "stderr": e.stderr})
            }],
            "is_error": True
        }

@tool("kubernetes_events_list", "List Kubernetes events", {
    "namespace": str
})
async def kubernetes_events_list(args: dict[str, Any]) -> dict[str, Any]:
    """List Kubernetes events."""
    namespace = args.get("namespace")

    cmd = ["kubectl", "get", "events", "-o", "json"]

    if namespace:
        cmd.extend(["-n", namespace])
    else:
        cmd.append("--all-namespaces")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except subprocess.CalledProcessError as e:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e), "stderr": e.stderr})
            }],
            "is_error": True
        }

# ============================================================================
# GitHub Tools
# ============================================================================

@tool("github_get_repo", "Get repository information", {
    "owner": str,
    "repo": str
})
async def github_get_repo(args: dict[str, Any]) -> dict[str, Any]:
    """Get repository information (demonstration)."""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "message": "GitHub MCP Tool - demonstration",
                "tool": "github_get_repo",
                "owner": args["owner"],
                "repo": args["repo"],
                "note": "This is a minimal demonstration. Full implementation would use PyGithub."
            }, indent=2)
        }]
    }

@tool("github_list_issues", "List issues in a repository", {
    "owner": str,
    "repo": str,
    "state": str
})
async def github_list_issues(args: dict[str, Any]) -> dict[str, Any]:
    """List issues in a repository (demonstration)."""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "message": "GitHub MCP Tool - demonstration",
                "tool": "github_list_issues",
                "owner": args["owner"],
                "repo": args["repo"],
                "state": args.get("state", "open"),
                "note": "This is a minimal demonstration. Full implementation would use PyGithub."
            }, indent=2)
        }]
    }
