"""
Custom Tools for OnCall Agent API
Uses direct Python libraries (kubernetes, PyGithub, boto3) instead of CLI commands

These are plain async functions (not decorated) for use with Anthropic SDK tool calling.
"""

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from github import Github
from kubernetes import client, config

from tools.datadog_integrator import DatadogIntegrator

logger = logging.getLogger(__name__)


# ============================================================
# Kubernetes Tools (using kubernetes Python library)
# ============================================================


def _get_k8s_client():
    """Get initialized Kubernetes client"""
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except Exception:
        try:
            config.load_kube_config()
            logger.info("Loaded kubeconfig from file")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes config: {e}")
            raise
    return client.CoreV1Api(), client.AppsV1Api()


async def list_namespaces(args: dict[str, Any]) -> dict[str, Any]:
    """List all namespaces in the cluster, optionally filtered by pattern."""
    pattern = args.get("pattern", "")

    try:
        v1, _ = _get_k8s_client()

        all_namespaces = v1.list_namespace()

        result = {"pattern": pattern, "namespaces": []}

        for ns in all_namespaces.items:
            ns_name = ns.metadata.name

            # If pattern provided, filter by it
            if pattern:
                if pattern.lower() in ns_name.lower():
                    result["namespaces"].append(
                        {
                            "name": ns_name,
                            "status": ns.status.phase,
                            "created": ns.metadata.creation_timestamp.isoformat(),
                        }
                    )
            else:
                result["namespaces"].append(
                    {
                        "name": ns_name,
                        "status": ns.status.phase,
                        "created": ns.metadata.creation_timestamp.isoformat(),
                    }
                )

        result["count"] = len(result["namespaces"])
        return result

    except Exception as e:
        logger.error(f"Error listing namespaces: {e}")
        return {"error": str(e), "pattern": pattern}


async def list_pods(args: dict[str, Any]) -> dict[str, Any]:
    """List pods in a Kubernetes namespace."""
    namespace = args.get("namespace")
    label_selector = args.get("label_selector", "")

    try:
        v1, _ = _get_k8s_client()

        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

        result = {"namespace": namespace, "count": len(pods.items), "pods": []}

        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "ready": sum(1 for c in pod.status.container_statuses or [] if c.ready),
                "total_containers": len(pod.spec.containers),
                "restarts": sum(c.restart_count for c in pod.status.container_statuses or []),
                "node": pod.spec.node_name,
                "created": pod.metadata.creation_timestamp.isoformat(),
            }

            # Add container status details
            if pod.status.container_statuses:
                pod_info["containers"] = []
                for container in pod.status.container_statuses:
                    container_info = {
                        "name": container.name,
                        "ready": container.ready,
                        "restarts": container.restart_count,
                        "state": {},
                    }

                    # Get current state
                    if container.state.running:
                        container_info["state"]["running"] = {
                            "started_at": container.state.running.started_at.isoformat()
                        }
                    elif container.state.waiting:
                        container_info["state"]["waiting"] = {
                            "reason": container.state.waiting.reason or "",
                            "message": container.state.waiting.message or "",
                        }
                    elif container.state.terminated:
                        container_info["state"]["terminated"] = {
                            "exit_code": container.state.terminated.exit_code,
                            "reason": container.state.terminated.reason or "",
                            "message": container.state.terminated.message or "",
                        }

                    pod_info["containers"].append(container_info)

            result["pods"].append(pod_info)

        return result

    except Exception as e:
        logger.error(f"Error listing pods: {e}")
        return {"error": str(e), "namespace": namespace}


async def get_pod_logs(args: dict[str, Any]) -> dict[str, Any]:
    """Get logs from a Kubernetes pod."""
    namespace = args.get("namespace")
    pod_name = args.get("pod_name")
    container = args.get("container", "")
    tail_lines = args.get("tail_lines", 100)

    try:
        v1, _ = _get_k8s_client()

        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container if container else None,
            tail_lines=tail_lines,
        )

        return {
            "pod": pod_name,
            "namespace": namespace,
            "container": container or "default",
            "tail_lines": tail_lines,
            "logs": logs,
        }

    except Exception as e:
        logger.error(f"Error getting pod logs: {e}")
        return {"error": str(e), "pod": pod_name, "namespace": namespace}


async def get_pod_events(args: dict[str, Any]) -> dict[str, Any]:
    """Get Kubernetes events for troubleshooting."""
    namespace = args.get("namespace")
    pod_name = args.get("pod_name", "")

    try:
        v1, _ = _get_k8s_client()

        events = v1.list_namespaced_event(namespace=namespace)

        result = {"namespace": namespace, "events": []}

        for event in events.items:
            # Filter by pod name if specified
            if pod_name and event.involved_object.name != pod_name:
                continue

            event_info = {
                "type": event.type,
                "reason": event.reason,
                "message": event.message,
                "object": {"kind": event.involved_object.kind, "name": event.involved_object.name},
                "count": event.count,
                "first_seen": event.first_timestamp.isoformat() if event.first_timestamp else None,
                "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None,
            }

            result["events"].append(event_info)

        # Sort by last seen, most recent first
        result["events"].sort(key=lambda x: x["last_seen"] or "", reverse=True)

        return result

    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return {"error": str(e), "namespace": namespace}


async def get_deployment_status(args: dict[str, Any]) -> dict[str, Any]:
    """Get status of a Kubernetes deployment."""
    namespace = args.get("namespace")
    deployment_name = args.get("deployment_name", "")

    try:
        _, apps_v1 = _get_k8s_client()

        if deployment_name:
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            deployments = [deployment]
        else:
            deployment_list = apps_v1.list_namespaced_deployment(namespace=namespace)
            deployments = deployment_list.items

        result = {"namespace": namespace, "deployments": []}

        for dep in deployments:
            dep_info = {
                "name": dep.metadata.name,
                "replicas": {
                    "desired": dep.spec.replicas,
                    "ready": dep.status.ready_replicas or 0,
                    "available": dep.status.available_replicas or 0,
                    "unavailable": dep.status.unavailable_replicas or 0,
                },
                "conditions": [],
            }

            if dep.status.conditions:
                for condition in dep.status.conditions:
                    dep_info["conditions"].append(
                        {
                            "type": condition.type,
                            "status": condition.status,
                            "reason": condition.reason or "",
                            "message": condition.message or "",
                        }
                    )

            result["deployments"].append(dep_info)

        return result

    except Exception as e:
        logger.error(f"Error getting deployment status: {e}")
        return {"error": str(e), "namespace": namespace, "deployment": deployment_name}


async def list_services(args: dict[str, Any]) -> dict[str, Any]:
    """List Kubernetes Services with their label selectors.

    This tool retrieves Service definitions and inspects their selectors,
    which is useful for identifying services that may have issues with
    label selector configurations (e.g., using version labels).

    Args:
        namespace: Target namespace (optional - if not provided, lists across all namespaces)
        service_name: Specific service name to inspect (optional)
        check_label: Specific label key to check in selectors (e.g., "app.kubernetes.io/version")

    Returns:
        Dictionary with service information including selectors
    """
    namespace = args.get("namespace", "")
    service_name = args.get("service_name", "")
    check_label = args.get("check_label", "")

    try:
        v1, _ = _get_k8s_client()

        result = {"services": [], "total_count": 0, "filtered_count": 0}

        # Add query context to result
        if namespace:
            result["namespace"] = namespace
        else:
            result["scope"] = "all-namespaces"

        if check_label:
            result["filtered_by_label"] = check_label

        # Determine query scope
        if namespace and service_name:
            # Specific service in specific namespace
            service = v1.read_namespaced_service(name=service_name, namespace=namespace)
            services = [service]
        elif namespace:
            # All services in specific namespace
            service_list = v1.list_namespaced_service(namespace=namespace)
            services = service_list.items
        else:
            # All services across all namespaces
            service_list = v1.list_service_for_all_namespaces()
            services = service_list.items

        result["total_count"] = len(services)

        # Process each service
        for svc in services:
            service_info = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "selector": svc.spec.selector or {},
                "ports": [],
            }

            # Extract port information
            if svc.spec.ports:
                for port in svc.spec.ports:
                    service_info["ports"].append(
                        {
                            "name": port.name or "",
                            "protocol": port.protocol,
                            "port": port.port,
                            "target_port": str(port.target_port) if port.target_port else "",
                        }
                    )

            # If checking for specific label, filter results
            if check_label:
                if check_label in service_info["selector"]:
                    service_info["label_issue"] = {
                        "problematic_label": check_label,
                        "value": service_info["selector"][check_label],
                        "warning": f"Service selector uses '{check_label}' which may cause routing issues during deployments",
                    }
                    result["services"].append(service_info)
                    result["filtered_count"] += 1
            else:
                # No filter, include all services
                result["services"].append(service_info)
                result["filtered_count"] += 1

        # Add analysis summary if checking for specific label
        if check_label and result["filtered_count"] > 0:
            result["analysis"] = {
                "issue": f"Found {result['filtered_count']} service(s) using '{check_label}' in selector",
                "impact": "Services using version labels in selectors won't route traffic to new versions during rolling updates",
                "recommendation": "Update service selectors to use stable labels like 'app.kubernetes.io/name' or 'app.kubernetes.io/instance' instead",
            }
        elif check_label and result["filtered_count"] == 0:
            result["analysis"] = {
                "status": "healthy",
                "message": f"No services found using '{check_label}' in selector - good practice!",
            }

        return result

    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return {"error": str(e), "namespace": namespace or "all", "service_name": service_name}


# ============================================================
# GitHub Tools (using PyGithub)
# ============================================================


def _get_github_client():
    """Get initialized GitHub client"""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set")
    return Github(token)


async def search_recent_deployments(args: dict[str, Any]) -> dict[str, Any]:
    """Search for recent GitHub Actions deployments."""
    repo_name = args.get("repo_name")
    hours_back = args.get("hours_back", 24)
    workflow_name = args.get("workflow_name", "")

    try:
        gh = _get_github_client()
        repo = gh.get_repo(repo_name)

        since = datetime.now() - timedelta(hours=hours_back)

        runs = repo.get_workflow_runs(created=f">={since.isoformat()}")

        result = {"repository": repo_name, "hours_back": hours_back, "deployments": []}

        for run in runs[:10]:  # Limit to 10 most recent
            # Filter by workflow name if specified
            if workflow_name and workflow_name.lower() not in run.name.lower():
                continue

            run_info = {
                "id": run.id,
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "head_branch": run.head_branch,
                "head_sha": run.head_sha[:8],
                "url": run.html_url,
            }

            result["deployments"].append(run_info)

        return result

    except Exception as e:
        logger.error(f"Error searching deployments: {e}")
        return {"error": str(e), "repository": repo_name}


# ============================================================
# GitOps PR Tools (using PyGithub)
# ============================================================


def _get_gitops_config() -> tuple[str, str, str]:
    """Get GitOps repository configuration from environment."""
    repo = os.getenv("GITOPS_REPO", "arigsela/kubernetes")
    base_path = os.getenv("GITOPS_BASE_PATH", "base-apps/")
    base_branch = os.getenv("GITOPS_BASE_BRANCH", "main")
    return repo, base_path, base_branch


def _validate_gitops_path(file_path: str, base_path: str) -> str | None:
    """Validate that a file path is within the allowed GitOps base path.

    Returns an error message if invalid, None if valid.
    """
    # Normalize path to resolve traversal sequences like ../../
    normalized = os.path.normpath(file_path)
    normalized_base = os.path.normpath(base_path)
    if not normalized.startswith(normalized_base):
        return f"Path '{file_path}' is outside allowed base path '{base_path}'"
    return None


async def get_gitops_file(args: dict[str, Any]) -> dict[str, Any]:
    """Read a file from the GitOps repository.

    Args:
        file_path: Path to the file within the repo (must be under GITOPS_BASE_PATH)

    Returns:
        Dictionary with file content, sha, and metadata
    """
    file_path = args.get("file_path", "")
    gitops_repo, base_path, base_branch = _get_gitops_config()

    # Validate path
    path_error = _validate_gitops_path(file_path, base_path)
    if path_error:
        return {"error": path_error}

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)
        contents = repo.get_contents(file_path, ref=base_branch)

        # Handle directory case
        if isinstance(contents, list):
            return {"error": f"'{file_path}' is a directory, not a file. Use list_gitops_directory instead."}

        return {
            "repository": gitops_repo,
            "file_path": file_path,
            "content": contents.decoded_content.decode("utf-8"),
            "sha": contents.sha,
            "html_url": contents.html_url,
        }

    except Exception as e:
        logger.error(f"Error reading GitOps file: {e}")
        return {"error": str(e), "file_path": file_path, "repository": gitops_repo}


async def list_gitops_directory(args: dict[str, Any]) -> dict[str, Any]:
    """List files and directories in the GitOps repository.

    Args:
        dir_path: Path to the directory (defaults to GITOPS_BASE_PATH)

    Returns:
        Dictionary with directory entries
    """
    gitops_repo, base_path, base_branch = _get_gitops_config()
    dir_path = args.get("dir_path", base_path)

    # Validate path
    path_error = _validate_gitops_path(dir_path, base_path)
    if path_error:
        return {"error": path_error}

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)
        contents = repo.get_contents(dir_path, ref=base_branch)

        if not isinstance(contents, list):
            return {"error": f"'{dir_path}' is a file, not a directory. Use get_gitops_file instead."}

        entries = []
        for item in contents:
            entries.append({
                "name": item.name,
                "path": item.path,
                "type": item.type,  # "file" or "dir"
                "size": item.size if item.type == "file" else None,
            })

        # Sort: directories first, then files, both alphabetical
        entries.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"]))

        return {
            "repository": gitops_repo,
            "dir_path": dir_path,
            "entries": entries,
            "count": len(entries),
        }

    except Exception as e:
        logger.error(f"Error listing GitOps directory: {e}")
        return {"error": str(e), "dir_path": dir_path, "repository": gitops_repo}


def _build_pr_body(
    service: str,
    action_summary: str,
    reason: str,
    incident_context: str,
    changes: list[dict[str, str]],
) -> str:
    """Build the PR description body."""
    file_list = "\n".join(
        f"- `{c['file_path']}` ({c['action']})" for c in changes
    )

    return f"""## Automated Remediation PR

**Service**: {service}
**Action**: {action_summary}
**Reason**: {reason}

### Incident Context
{incident_context}

### Files Changed
{file_list}

### Important
- This PR was created by the oncall-agent
- Review carefully before merging
- **DO NOT auto-merge** — requires human approval
- ArgoCD will sync changes after merge

---
*Created by oncall-agent-api*
"""


def _apply_patches(original_content: str, patches: list[dict[str, str]]) -> tuple[str, str | None]:
    """Apply find/replace patches to file content.

    Args:
        original_content: The original file content
        patches: List of {old_string, new_string} pairs

    Returns:
        Tuple of (patched_content, error_message_or_none)
    """
    content = original_content
    for i, patch in enumerate(patches):
        old_string = patch.get("old_string", "")
        new_string = patch.get("new_string", "")

        if not old_string:
            return content, f"Patch {i}: old_string cannot be empty"

        occurrences = content.count(old_string)
        if occurrences == 0:
            return content, (
                f"Patch {i}: old_string not found in file. "
                f"Make sure it exactly matches the file content (including whitespace and indentation). "
                f"old_string was: {repr(old_string[:200])}"
            )
        if occurrences > 1:
            return content, (
                f"Patch {i}: old_string matched {occurrences} times — must be unique. "
                f"Include more surrounding context to make it unique."
            )

        content = content.replace(old_string, new_string, 1)

    return content, None


async def create_remediation_pr(args: dict[str, Any]) -> dict[str, Any]:
    """Create a PR in the GitOps repository with remediation changes.

    ONLY call this AFTER the user has explicitly confirmed the proposed changes.

    For updates, uses patch-based find/replace to make surgical edits to existing files.
    This prevents accidental rewrites of unrelated content.

    Args:
        service: Service name being remediated
        action_summary: Brief description of the action (e.g., "scale-replicas")
        changes: List of file changes. For updates: file_path, patches [{old_string, new_string}].
                 For creates: file_path, content.
        incident_context: Description of the incident being remediated
        reason: Why these changes are needed

    Returns:
        Dictionary with PR number, URL, branch name, and files changed
    """
    service = args.get("service", "")
    action_summary = args.get("action_summary", "")
    changes = args.get("changes", [])
    incident_context = args.get("incident_context", "")
    reason = args.get("reason", "")

    gitops_repo, base_path, base_branch = _get_gitops_config()

    # Validate inputs
    if not service:
        return {"error": "service is required"}
    if not action_summary:
        return {"error": "action_summary is required"}
    if not changes:
        return {"error": "changes list cannot be empty"}

    # Validate each change
    for change in changes:
        file_path = change.get("file_path", "")
        action = change.get("action", "")

        if not file_path:
            return {"error": "Each change requires file_path"}

        # Validate path
        path_error = _validate_gitops_path(file_path, base_path)
        if path_error:
            return {"error": path_error}

        # Validate action
        if action not in ("update", "create"):
            return {"error": f"Invalid action '{action}'. Must be 'update' or 'create'."}

        # Validate action-specific fields
        if action == "update":
            patches = change.get("patches", [])
            if not patches:
                return {"error": "Update action requires a non-empty patches list"}
            for i, patch in enumerate(patches):
                if not patch.get("old_string"):
                    return {"error": f"Patch {i} requires old_string"}
                if "new_string" not in patch:
                    return {"error": f"Patch {i} requires new_string"}
        elif action == "create":
            if not change.get("content"):
                return {"error": "Create action requires content"}

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)

        # Create branch name with timestamp
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        # Sanitize action_summary for branch name
        safe_action = re.sub(r"[^a-zA-Z0-9-]", "-", action_summary.lower())[:30]
        safe_service = re.sub(r"[^a-zA-Z0-9-]", "-", service.lower())[:30]
        branch_name = f"oncall-agent/{safe_service}-{safe_action}-{timestamp}"

        # Get the base branch ref
        base_ref = repo.get_git_ref(f"heads/{base_branch}")
        base_sha = base_ref.object.sha

        # Create the new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)

        # Commit each file change
        files_changed = []
        for change in changes:
            file_path = change["file_path"]
            action = change["action"]

            if action == "update":
                # Read the current file from the branch
                existing = repo.get_contents(file_path, ref=branch_name)
                original_content = existing.decoded_content.decode("utf-8")

                # Apply patches
                patched_content, patch_error = _apply_patches(
                    original_content, change["patches"]
                )
                if patch_error:
                    return {
                        "error": f"Patch failed for {file_path}: {patch_error}",
                        "service": service,
                        "action_summary": action_summary,
                    }

                repo.update_file(
                    path=file_path,
                    message=f"oncall-agent: {action_summary} - {file_path}",
                    content=patched_content,
                    sha=existing.sha,
                    branch=branch_name,
                )
            elif action == "create":
                repo.create_file(
                    path=file_path,
                    message=f"oncall-agent: {action_summary} - {file_path}",
                    content=change["content"],
                    branch=branch_name,
                )

            files_changed.append(file_path)

        # Build PR body
        pr_body = _build_pr_body(
            service=service,
            action_summary=action_summary,
            reason=reason,
            incident_context=incident_context,
            changes=changes,
        )

        # Create PR
        pr = repo.create_pull(
            title=f"[oncall-agent] {service}: {action_summary}",
            body=pr_body,
            head=branch_name,
            base=base_branch,
        )

        # Add labels
        try:
            pr.add_to_labels("oncall-agent", "automated")
        except Exception as label_err:
            logger.warning(f"Could not add labels to PR: {label_err}")

        logger.info(f"Created PR #{pr.number}: {pr.html_url}")

        return {
            "pr_number": pr.number,
            "pr_url": pr.html_url,
            "branch": branch_name,
            "files_changed": files_changed,
        }

    except Exception as e:
        logger.error(f"Error creating remediation PR: {e}")
        return {"error": str(e), "service": service, "action_summary": action_summary}


# ============================================================
# Document PR Tools (using PyGithub)
# ============================================================


async def create_document_pr(args: dict[str, Any]) -> dict[str, Any]:
    """Create a PR in the docs repo to save a markdown document.

    Use this to persist any document, guide, runbook, or reference material
    the agent generates. Files are saved under docs/ in the claude-agents repo.

    Args:
        filename: Markdown filename (e.g., 'kubernetes-interview-questions.md')
        content: Full markdown content to save
        description: Brief description for PR title and commit message

    Returns:
        Dictionary with pr_number, pr_url, branch, and file_path
    """
    filename = args.get("filename", "")
    content = args.get("content", "")
    description = args.get("description", "")

    # Validate required fields
    if not filename:
        return {"error": "filename is required"}
    if not content:
        return {"error": "content is required"}
    if not description:
        return {"error": "description is required"}

    # Reject path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return {"error": f"Invalid filename '{filename}': must be a plain filename without path separators or '..'"}

    # Ensure .md extension
    if not filename.endswith(".md"):
        filename = f"{filename}.md"

    # Build file path under docs/
    file_path = f"docs/{filename}"

    # Get repo configuration
    docs_repo = os.getenv("DOCS_REPO", "arigsela/claude-agents")

    try:
        gh = _get_github_client()
        repo = gh.get_repo(docs_repo)

        # Create branch name with timestamp
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^a-zA-Z0-9-]", "-", filename.replace(".md", "").lower())[:40]
        branch_name = f"oncall-agent/docs-{safe_name}-{timestamp}"

        # Get the base branch ref
        default_branch = repo.default_branch
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        base_sha = base_ref.object.sha

        # Create the new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)

        # Create the file on the new branch
        repo.create_file(
            path=file_path,
            message=f"oncall-agent: add {filename} - {description}",
            content=content,
            branch=branch_name,
        )

        # Create PR
        pr = repo.create_pull(
            title=f"[oncall-agent] docs: {description}",
            body=f"## Document PR\n\n**File**: `{file_path}`\n**Description**: {description}\n\n---\n*Created by oncall-agent-api*",
            head=branch_name,
            base=default_branch,
        )

        # Add labels
        try:
            pr.add_to_labels("oncall-agent", "docs")
        except Exception as label_err:
            logger.warning(f"Could not add labels to PR: {label_err}")

        logger.info(f"Created document PR #{pr.number}: {pr.html_url}")

        return {
            "pr_number": pr.number,
            "pr_url": pr.html_url,
            "branch": branch_name,
            "file_path": file_path,
        }

    except Exception as e:
        logger.error(f"Error creating document PR: {e}")
        return {"error": str(e), "filename": filename}


# ============================================================
# Analysis Tools (combining multiple data sources)
# ============================================================


async def analyze_service_health(args: dict[str, Any]) -> dict[str, Any]:
    """Comprehensive health analysis of a Kubernetes service."""
    service_name = args.get("service_name")
    namespace = args.get("namespace")

    try:
        result = {
            "service": service_name,
            "namespace": namespace,
            "timestamp": datetime.now().isoformat(),
            "health_score": "unknown",
            "issues": [],
        }

        # 1. Check pods
        pods_data = await list_pods(
            {"namespace": namespace, "label_selector": f"app={service_name}"}
        )
        result["pods"] = pods_data

        # 2. Check deployment
        deployment_data = await get_deployment_status(
            {"namespace": namespace, "deployment_name": service_name}
        )
        result["deployment"] = deployment_data

        # 3. Check events for issues
        events_data = await get_pod_events({"namespace": namespace, "pod_name": ""})

        # Filter events related to this service
        service_events = [
            e
            for e in events_data.get("events", [])
            if service_name in e.get("object", {}).get("name", "")
        ]
        result["recent_events"] = service_events[:10]

        # 4. Analyze health
        if pods_data.get("error"):
            result["health_score"] = "error"
            result["issues"].append(f"Failed to query pods: {pods_data['error']}")
        else:
            # Check for unhealthy pods
            total_pods = pods_data.get("count", 0)
            unhealthy_pods = [
                p
                for p in pods_data.get("pods", [])
                if p["status"] != "Running" or p["ready"] < p["total_containers"]
            ]

            if unhealthy_pods:
                result["health_score"] = "unhealthy"
                result["issues"].append(f"{len(unhealthy_pods)}/{total_pods} pods unhealthy")
            else:
                result["health_score"] = "healthy"

        # Check for high restart counts
        high_restart_pods = [p for p in pods_data.get("pods", []) if p.get("restarts", 0) > 3]

        if high_restart_pods:
            result["issues"].append(f"{len(high_restart_pods)} pods with high restart counts")

        # Check for warning events
        warning_events = [e for e in service_events if e.get("type") == "Warning"]
        if warning_events:
            result["issues"].append(f"{len(warning_events)} warning events in last 10 minutes")

        return result

    except Exception as e:
        logger.error(f"Error analyzing service health: {e}")
        return {"error": str(e), "service": service_name, "namespace": namespace}


# ============================================================
# NAT Gateway Tools (using boto3 CloudWatch + NATGatewayAnalyzer)
# ============================================================


async def check_nat_gateway_metrics(args: dict[str, Any]) -> dict[str, Any]:
    """
    Check AWS NAT gateway traffic metrics for recent spikes or historical analysis.

    Supports multiple NAT gateways (multi-AZ deployments). When NAT_GATEWAY_IDS
    contains multiple comma-separated IDs, fetches and aggregates metrics from all.

    Use this when user asks about:
    - NAT gateway traffic or spikes
    - Network bandwidth usage
    - Datadog NAT alerts
    - Why NAT egress is high

    Args:
        time_window_hours: Hours to look back (1-168, default: 1)
        nat_gateway_id: Specific NAT gateway ID (optional - if not provided, queries all configured gateways)
        all_gateways: If true, always query all configured gateways (default: true when multiple configured)

    Returns:
        Traffic metrics with spike detection and human-readable summary
    """
    from tools.nat_gateway_analyzer import get_analyzer, DEFAULT_NAT_GATEWAY_IDS

    time_window_hours = args.get("time_window_hours", 1)
    specific_gateway = args.get("nat_gateway_id")
    query_all = args.get("all_gateways", len(DEFAULT_NAT_GATEWAY_IDS) > 1)

    try:
        analyzer = get_analyzer()

        # If specific gateway requested or only one configured, use single-gateway mode
        if specific_gateway or (not query_all and len(DEFAULT_NAT_GATEWAY_IDS) == 1):
            gateway_id = specific_gateway or DEFAULT_NAT_GATEWAY_IDS[0] if DEFAULT_NAT_GATEWAY_IDS else ""
            if not gateway_id:
                return {
                    "error": "No NAT gateway ID configured. Set NAT_GATEWAY_IDS environment variable.",
                    "time_window_hours": time_window_hours,
                }

            metrics = analyzer.fetch_nat_metrics(
                nat_gateway_id=gateway_id, time_window_hours=time_window_hours
            )
            summary = analyzer.format_metrics_for_llm(metrics)

            return {
                "summary": summary,
                "metrics": metrics.to_dict(),
                "spikes_count": len(metrics.spikes_detected),
                "total_egress_gb": round(metrics.total_bytes_out / (1024**3), 3),
                "mode": "single_gateway",
            }

        # Multi-gateway mode - fetch and aggregate from all configured gateways
        aggregated = analyzer.fetch_all_nat_metrics(time_window_hours=time_window_hours)
        summary = analyzer.format_aggregated_metrics_for_llm(aggregated)

        return {
            "summary": summary,
            "metrics": aggregated.to_dict(),
            "spikes_count": len(aggregated.all_spikes),
            "total_egress_gb": round(aggregated.total_bytes_out / (1024**3), 3),
            "gateway_count": len(aggregated.nat_gateway_ids),
            "mode": "multi_gateway",
        }

    except ValueError as e:
        logger.warning(f"Validation error in NAT metrics query: {e}")
        return {
            "error": str(e),
            "time_window_hours": time_window_hours,
        }
    except Exception as e:
        logger.error(f"Error fetching NAT metrics: {e}")
        return {
            "error": f"Failed to fetch NAT gateway metrics: {str(e)}",
        }


# ============================================================
# Datadog Tools (using datadog-api-client)
# ============================================================


async def query_datadog_metrics(params: dict[str, Any]) -> dict[str, Any]:
    """
    Query Datadog metrics for Kubernetes resources.

    Use this when user asks about:
    - Historical performance metrics (CPU, memory over time)
    - Resource usage trends
    - Performance before/after deployments
    - Gradual degradation patterns

    Args:
        params: {
            "metric": str,  # e.g., "kubernetes.cpu.usage", "kubernetes.memory.rss"
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 1),
            "aggregation": str (default: "avg")  # avg, max, min, sum
        }

    Returns:
        Timeseries data with timestamps and values

    Example usage:
        query_datadog_metrics({
            "metric": "kubernetes.cpu.usage",
            "namespace": "proteus-dev",
            "time_window_hours": 24
        })
    """
    try:
        integrator = DatadogIntegrator()

        metric = params.get("metric")
        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 1)
        aggregation = params.get("aggregation", "avg")

        if not metric or not namespace:
            return {
                "error": "metric and namespace are required parameters",
                "usage": "query_datadog_metrics(metric='kubernetes.cpu.usage', namespace='proteus-dev')",
                "available_metrics": [
                    "kubernetes.cpu.usage",
                    "kubernetes.memory.rss",
                    "kubernetes.memory.working_set",
                    "kubernetes.network.tx_bytes",
                    "kubernetes.network.rx_bytes",
                ],
            }

        logger.info(
            f"Querying Datadog: {metric} in {namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        result = await integrator.query_pod_metrics(
            metric=metric,
            namespace=namespace,
            pod_name=pod_name,
            hours_back=hours,
            aggregation=aggregation,
        )

        # Add human-readable summary
        if result.get("series"):
            total_points = sum(len(s.get("pointlist", [])) for s in result["series"])
            summary = {
                "metric": metric,
                "namespace": namespace,
                "pod_name": pod_name or "all pods",
                "time_window": f"Last {hours} hour(s)",
                "aggregation": aggregation,
                "data_points": total_points,
                "series_count": len(result["series"]),
            }
            result["summary"] = summary
            logger.info(
                f"✓ Retrieved {total_points} data points across {len(result['series'])} series"
            )
        elif result.get("error"):
            logger.warning(f"Datadog query failed: {result['error']}")
        else:
            result["summary"] = {
                "metric": metric,
                "namespace": namespace,
                "message": "No data available for this query",
            }

        return result

    except Exception as e:
        logger.error(f"Error querying Datadog metrics: {e}", exc_info=True)
        return {
            "error": str(e),
            "metric": params.get("metric"),
            "namespace": params.get("namespace"),
        }


async def get_resource_usage_trends(params: dict[str, Any]) -> dict[str, Any]:
    """
    Get CPU and memory usage trends for a service over time.

    Useful for identifying:
    - Memory leaks (gradual memory increase)
    - Resource exhaustion patterns
    - Performance degradation over time
    - Pre/post deployment resource changes

    Args:
        params: {
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 24)
        }

    Returns:
        Combined CPU and memory trends with analysis

    Example usage:
        get_resource_usage_trends({
            "namespace": "artemis-auth-dev",
            "time_window_hours": 168  # 1 week
        })
    """
    try:
        integrator = DatadogIntegrator()

        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 24)

        if not namespace:
            return {
                "error": "namespace is required",
                "usage": "get_resource_usage_trends(namespace='proteus-dev', time_window_hours=24)",
            }

        logger.info(
            f"Getting resource usage trends for namespace={namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        # Get both CPU and memory metrics
        result = await integrator.query_container_metrics(
            namespace=namespace, container_name=pod_name, hours_back=hours
        )

        # Add analysis summary
        analysis = {
            "namespace": namespace,
            "pod_name": pod_name or "all pods",
            "time_window": f"Last {hours} hour(s)",
            "metrics_retrieved": list(result.keys()),
            "timestamp": datetime.now().isoformat(),
        }

        # Check if we have data for trend analysis
        has_data = any(
            r.get("series") and len(r.get("series", [])) > 0
            for r in result.values()
            if isinstance(r, dict)
        )

        if has_data:
            analysis["data_availability"] = "Metrics available for trend analysis"
            logger.info(f"✓ Resource trends available for {namespace}")
        else:
            analysis["data_availability"] = (
                "No metrics data available - check if Datadog agent is collecting from this namespace"
            )
            logger.warning(f"No resource trend data for {namespace}")

        result["analysis"] = analysis

        return result

    except Exception as e:
        logger.error(f"Error getting resource trends: {e}", exc_info=True)
        return {"error": str(e), "namespace": params.get("namespace")}


async def check_network_traffic(params: dict[str, Any]) -> dict[str, Any]:
    """
    Check network traffic patterns for pods.

    Useful for:
    - Identifying traffic spikes
    - Correlating with NAT gateway usage
    - Network error investigation
    - Bandwidth analysis

    Args:
        params: {
            "namespace": str,
            "pod_name": str (optional),
            "time_window_hours": int (default: 1)
        }

    Returns:
        Network TX/RX metrics and error rates

    Example usage:
        check_network_traffic({
            "namespace": "zeus-dev",
            "time_window_hours": 2
        })
    """
    try:
        integrator = DatadogIntegrator()

        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        hours = params.get("time_window_hours", 1)

        if not namespace:
            return {
                "error": "namespace is required",
                "usage": "check_network_traffic(namespace='zeus-dev', time_window_hours=2)",
            }

        logger.info(
            f"Checking network traffic for namespace={namespace}, pod={pod_name or 'all'}, hours={hours}"
        )

        result = await integrator.query_network_metrics(
            namespace=namespace, pod_name=pod_name, hours_back=hours
        )

        # Add summary
        summary = {
            "namespace": namespace,
            "pod_name": pod_name or "all pods",
            "time_window": f"Last {hours} hour(s)",
            "metrics": list(result.keys()),
            "timestamp": datetime.now().isoformat(),
        }

        # Calculate totals if data available
        total_tx_bytes = 0
        total_rx_bytes = 0

        for metric_name, metric_data in result.items():
            if isinstance(metric_data, dict) and metric_data.get("series"):
                for series in metric_data["series"]:
                    pointlist = series.get("pointlist", [])
                    if pointlist and "tx_bytes" in metric_name:
                        # Sum of last values for TX (ensure numeric conversion)
                        for point in pointlist:
                            if point[1]:
                                try:
                                    total_tx_bytes += float(point[1])
                                except (ValueError, TypeError):
                                    continue
                    elif pointlist and "rx_bytes" in metric_name:
                        # Sum of last values for RX (ensure numeric conversion)
                        for point in pointlist:
                            if point[1]:
                                try:
                                    total_rx_bytes += float(point[1])
                                except (ValueError, TypeError):
                                    continue

        if total_tx_bytes > 0 or total_rx_bytes > 0:
            summary["totals"] = {
                "tx_gb": round(total_tx_bytes / (1024**3), 3),
                "rx_gb": round(total_rx_bytes / (1024**3), 3),
                "total_gb": round((total_tx_bytes + total_rx_bytes) / (1024**3), 3),
            }
            logger.info(
                f"✓ Network traffic: TX={summary['totals']['tx_gb']} GB, RX={summary['totals']['rx_gb']} GB"
            )
        else:
            summary["message"] = "No network traffic data available"
            logger.warning(f"No network traffic data for {namespace}")

        result["summary"] = summary

        return result

    except Exception as e:
        logger.error(f"Error checking network traffic: {e}", exc_info=True)
        return {"error": str(e), "namespace": params.get("namespace")}


# ============================================================
# Zeus Refresh Job Analysis Tools (using Zeus Analyzer)
# ============================================================


async def analyze_zeus_refreshes(args: dict[str, Any]) -> dict[str, Any]:
    """
    Comprehensive analysis of Zeus refresh jobs combining Kubernetes + Datadog logs + metrics.

    This tool provides detailed information about Zeus data refresh jobs including:
    - Job status and duration
    - Client names and refresh types (extracted from logs)
    - Databricks job IDs and execution details
    - Resource usage (CPU, memory, network)
    - Error messages and failures

    Args:
        hours_back: Number of hours to look back (default: 1)
        client_name: Optional filter by client name
        status: Optional filter by status (Running, Succeeded, Failed)
        include_logs: Whether to enrich with Datadog logs (default: True)
        include_metrics: Whether to enrich with Datadog metrics (default: True)

    Returns:
        Dictionary with comprehensive Zeus job analysis
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    hours_back = args.get("hours_back", 1)
    client_name = args.get("client_name")
    status = args.get("status")
    include_logs = args.get("include_logs", True)
    include_metrics = args.get("include_metrics", True)

    try:
        analyzer = ZeusAnalyzer()

        result = await analyzer.analyze_zeus_refreshes(
            hours_back=hours_back,
            client_name=client_name,
            status=status,
            include_logs=include_logs,
            include_metrics=include_metrics,
        )

        return result

    except Exception as e:
        logger.error(f"Error analyzing Zeus refreshes: {e}", exc_info=True)
        return {
            "error": str(e),
            "hours_back": hours_back,
            "client_name": client_name,
            "status": status,
        }


async def get_zeus_job_details(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get detailed information about a specific Zeus refresh job.

    Args:
        job_name: Name of the Zeus job (e.g., "zeus-refresh-abc-12345")
        namespace: Namespace where the job runs (e.g., "qa", "devmatt")
        include_logs: Whether to include Datadog logs (default: True)
        include_metrics: Whether to include metrics (default: True)

    Returns:
        Dictionary with detailed job information
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    job_name = args.get("job_name")
    namespace = args.get("namespace")
    include_logs = args.get("include_logs", True)
    include_metrics = args.get("include_metrics", True)

    if not job_name or not namespace:
        return {
            "error": "Both job_name and namespace are required",
            "job_name": job_name,
            "namespace": namespace,
        }

    try:
        analyzer = ZeusAnalyzer()

        # Find the specific job
        from datetime import datetime, timedelta

        start_time = datetime.now(UTC) - timedelta(days=7)  # Look back 7 days

        jobs = analyzer.find_zeus_jobs(start_time=start_time)

        # Filter to the specific job
        target_job = None
        for job in jobs:
            if job.job_name == job_name and job.namespace == namespace:
                target_job = job
                break

        if not target_job:
            return {
                "error": f"Job {job_name} not found in namespace {namespace}",
                "job_name": job_name,
                "namespace": namespace,
            }

        # Enrich with logs and metrics
        if include_logs:
            jobs_with_logs = analyzer.enrich_with_logs([target_job])
            target_job = jobs_with_logs[0] if jobs_with_logs else target_job

        if include_metrics:
            jobs_with_metrics = await analyzer.enrich_with_metrics([target_job])
            target_job = jobs_with_metrics[0] if jobs_with_metrics else target_job

        # Convert to dict
        from dataclasses import asdict

        return {"job": asdict(target_job), "job_name": job_name, "namespace": namespace}

    except Exception as e:
        logger.error(f"Error getting Zeus job details: {e}", exc_info=True)
        return {"error": str(e), "job_name": job_name, "namespace": namespace}


async def find_zeus_jobs_by_client(args: dict[str, Any]) -> dict[str, Any]:
    """
    Find all Zeus refresh jobs for a specific client.

    Args:
        client_name: Client name to search for (e.g., "ABC Corp", "acme")
        hours_back: Number of hours to look back (default: 24)
        status: Optional filter by status (Running, Succeeded, Failed)

    Returns:
        Dictionary with matching Zeus jobs
    """
    from tools.zeus_analyzer import ZeusAnalyzer

    client_name = args.get("client_name")
    hours_back = args.get("hours_back", 24)
    status = args.get("status")

    if not client_name:
        return {"error": "client_name is required", "client_name": client_name}

    try:
        analyzer = ZeusAnalyzer()

        result = await analyzer.analyze_zeus_refreshes(
            hours_back=hours_back,
            client_name=client_name,
            status=status,
            include_logs=True,  # Need logs to extract client names
            include_metrics=True,
        )

        return result

    except Exception as e:
        logger.error(f"Error finding Zeus jobs by client: {e}", exc_info=True)
        return {"error": str(e), "client_name": client_name, "hours_back": hours_back}


# ============================================================
# AWS Cost Explorer Tools
# ============================================================


async def get_cost_anomalies(args: dict[str, Any]) -> dict[str, Any]:
    """
    Detect AWS cost anomalies using AWS Cost Anomaly Detection service.

    Args:
        days_back: Number of days to look back (1-90, default: 7)
        min_impact: Minimum dollar impact threshold (default: 10.0)
        max_results: Maximum anomalies to return (1-100, default: 50)

    Returns:
        Dictionary with detected cost anomalies and analysis
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 7)
    min_impact = args.get("min_impact", 10.0)
    max_results = args.get("max_results", 50)

    try:
        cost_explorer = AWSCostExplorer()

        anomalies = await cost_explorer.get_cost_anomalies(
            days_back=days_back, min_impact=min_impact, max_results=max_results
        )

        # Calculate total impact
        total_impact = sum(a.get("impact_amount", 0) for a in anomalies)

        return {
            "status": "success",
            "anomalies": anomalies,
            "total_impact": total_impact,
            "anomaly_count": len(anomalies),
            "days_back": days_back,
            "min_impact": min_impact,
        }

    except Exception as e:
        logger.error(f"Error getting cost anomalies: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "min_impact": min_impact}


async def get_daily_costs(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get daily cost breakdown by service or other dimension.

    Args:
        days_back: Number of days to analyze (1-365, default: 30)
        group_by: Dimension to group by (SERVICE, LINKED_ACCOUNT, REGION, USAGE_TYPE)
        granularity: Time granularity (DAILY or MONTHLY, default: DAILY)

    Returns:
        Dictionary with daily cost breakdown and top services
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 30)
    group_by = args.get("group_by", "SERVICE")
    granularity = args.get("granularity", "DAILY")

    try:
        cost_explorer = AWSCostExplorer()

        result = await cost_explorer.get_daily_costs(
            days_back=days_back, group_by=group_by, granularity=granularity
        )

        return {
            "status": "success",
            **result,
            "days_back": days_back,
            "group_by": group_by,
            "granularity": granularity,
        }

    except Exception as e:
        logger.error(f"Error getting daily costs: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "group_by": group_by}


async def get_ec2_costs_by_tags(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get EC2 costs broken down by specific tags like node groups, Karpenter pools, and Databricks workers.

    Args:
        days_back: Number of days to analyze (1-365, default: 7)
        tag_keys: List of tag keys to group by (default: ['karpenter.sh/nodepool', 'eks:nodegroup-name', 'Refresh-Id'])
        service_filter: AWS service to filter (default: EC2 compute)
        max_tag_values: Maximum tag values to return per tag (default: 10)

    Returns:
        Dictionary with EC2 costs grouped by tags and top cost sources (limited to prevent context overflow)
    """
    from tools.aws_cost_explorer import AWSCostExplorer

    days_back = args.get("days_back", 7)
    tag_keys = args.get("tag_keys", ["karpenter.sh/nodepool", "eks:nodegroup-name", "Refresh-Id"])
    service_filter = args.get("service_filter", "Amazon Elastic Compute Cloud - Compute")
    max_tag_values = args.get("max_tag_values", 10)

    try:
        cost_explorer = AWSCostExplorer()

        result = await cost_explorer.get_ec2_costs_by_tags(
            days_back=days_back,
            tag_keys=tag_keys,
            service_filter=service_filter,
            max_tag_values=max_tag_values,
        )

        # Calculate summary statistics
        total_cost = result.get("total_ec2_cost", 0)
        top_sources = result.get("top_cost_sources", [])
        tag_breakdown = result.get("tag_breakdown", {})

        # Count unique tag values
        total_tag_values = sum(len(values) for values in tag_breakdown.values())

        return {
            "status": "success",
            **result,
            "summary": {
                "total_ec2_cost": total_cost,
                "total_tag_values": total_tag_values,
                "top_3_sources": top_sources[:3] if top_sources else [],
            },
            "days_back": days_back,
            "tag_keys": tag_keys,
        }

    except Exception as e:
        logger.error(f"Error getting EC2 costs by tags: {e}", exc_info=True)
        return {"error": str(e), "days_back": days_back, "tag_keys": tag_keys}
