"""GitHub/GitOps tools for the GitHub A2A agent.

Adapted from oncall-agent-api/src/api/custom_tools.py (GitHub + GitOps section).
All tools are synchronous and return JSON strings per CrewAI @tool requirements.
"""

import json
import os
import re
from datetime import UTC, datetime, timedelta

from crewai.tools import tool
from github import Github

from shared.config import (
    DOCS_REPO,
    GITHUB_TOKEN,
    GITOPS_BASE_BRANCH,
    GITOPS_BASE_PATH,
    GITOPS_REPO,
)
from shared.logging_config import setup_logging

logger = setup_logging("github-tools")


# ============================================================
# Helpers
# ============================================================


def _get_github_client() -> Github:
    """Get initialized GitHub client."""
    token = GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set")
    return Github(token)


def _get_gitops_config() -> tuple[str, str, str]:
    """Get GitOps repository configuration."""
    return (
        GITOPS_REPO or os.getenv("GITOPS_REPO", "arigsela/kubernetes"),
        GITOPS_BASE_PATH or os.getenv("GITOPS_BASE_PATH", "base-apps/"),
        GITOPS_BASE_BRANCH or os.getenv("GITOPS_BASE_BRANCH", "main"),
    )


def _validate_gitops_path(file_path: str, base_path: str) -> str | None:
    """Validate that a file path is within the allowed GitOps base path.

    Returns an error message if invalid, None if valid.
    """
    normalized = os.path.normpath(file_path)
    normalized_base = os.path.normpath(base_path)
    if not normalized.startswith(normalized_base):
        return f"Path '{file_path}' is outside allowed base path '{base_path}'"
    return None


def _apply_patches(
    original_content: str, patches: list[dict[str, str]]
) -> tuple[str, str | None]:
    """Apply find/replace patches to file content.

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
                f"Make sure it exactly matches the file content "
                f"(including whitespace and indentation). "
                f"old_string was: {repr(old_string[:200])}"
            )
        if occurrences > 1:
            return content, (
                f"Patch {i}: old_string matched {occurrences} times — must be unique. "
                f"Include more surrounding context to make it unique."
            )

        content = content.replace(old_string, new_string, 1)

    return content, None


def _build_pr_body(
    service: str,
    action_summary: str,
    reason: str,
    incident_context: str,
    changes: list[dict],
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
*Created by oncall-crewai*
"""


# ============================================================
# Tools
# ============================================================


@tool
def search_recent_deployments(
    repo_name: str, hours_back: int = 24, workflow_name: str = ""
) -> str:
    """Search for recent GitHub Actions workflow runs in a repository.

    Args:
        repo_name: Full repository name (e.g. "arigsela/kubernetes").
        hours_back: How many hours back to search (default 24).
        workflow_name: Optional workflow name filter (case-insensitive substring).

    Returns:
        JSON with recent deployment/workflow runs including status, conclusion, and branch.
    """
    try:
        gh = _get_github_client()
        repo = gh.get_repo(repo_name)

        since = datetime.now() - timedelta(hours=hours_back)
        runs = repo.get_workflow_runs(created=f">={since.isoformat()}")

        deployments = []
        for run in runs[:10]:
            if workflow_name and workflow_name.lower() not in run.name.lower():
                continue
            deployments.append({
                "id": run.id,
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "head_branch": run.head_branch,
                "head_sha": run.head_sha[:8],
                "url": run.html_url,
            })

        return json.dumps({
            "repository": repo_name,
            "hours_back": hours_back,
            "deployments": deployments,
        })

    except Exception as e:
        logger.error(f"Error searching deployments: {e}")
        return json.dumps({"error": str(e), "repository": repo_name})


@tool
def get_gitops_file(file_path: str) -> str:
    """Read a file from the GitOps repository (arigsela/kubernetes).

    Only files under the base-apps/ path are accessible.

    Args:
        file_path: Path to the file within the repo (e.g. "base-apps/myapp/deployment.yaml").

    Returns:
        JSON with file content, SHA, and URL.
    """
    gitops_repo, base_path, base_branch = _get_gitops_config()

    path_error = _validate_gitops_path(file_path, base_path)
    if path_error:
        return json.dumps({"error": path_error})

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)
        contents = repo.get_contents(file_path, ref=base_branch)

        if isinstance(contents, list):
            return json.dumps({
                "error": f"'{file_path}' is a directory, not a file. "
                "Use list_gitops_directory instead."
            })

        return json.dumps({
            "repository": gitops_repo,
            "file_path": file_path,
            "content": contents.decoded_content.decode("utf-8"),
            "sha": contents.sha,
            "html_url": contents.html_url,
        })

    except Exception as e:
        logger.error(f"Error reading GitOps file: {e}")
        return json.dumps({
            "error": str(e),
            "file_path": file_path,
            "repository": gitops_repo,
        })


@tool
def list_gitops_directory(dir_path: str = "") -> str:
    """List files and directories in the GitOps repository.

    Args:
        dir_path: Path to the directory (defaults to base-apps/).

    Returns:
        JSON with directory entries sorted: directories first, then files.
    """
    gitops_repo, base_path, base_branch = _get_gitops_config()
    if not dir_path:
        dir_path = base_path

    path_error = _validate_gitops_path(dir_path, base_path)
    if path_error:
        return json.dumps({"error": path_error})

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)
        contents = repo.get_contents(dir_path, ref=base_branch)

        if not isinstance(contents, list):
            return json.dumps({
                "error": f"'{dir_path}' is a file, not a directory. "
                "Use get_gitops_file instead."
            })

        entries = []
        for item in contents:
            entries.append({
                "name": item.name,
                "path": item.path,
                "type": item.type,
                "size": item.size if item.type == "file" else None,
            })

        entries.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"]))

        return json.dumps({
            "repository": gitops_repo,
            "dir_path": dir_path,
            "entries": entries,
            "count": len(entries),
        })

    except Exception as e:
        logger.error(f"Error listing GitOps directory: {e}")
        return json.dumps({
            "error": str(e),
            "dir_path": dir_path,
            "repository": gitops_repo,
        })


@tool
def create_remediation_pr(
    service: str,
    action_summary: str,
    changes_json: str,
    incident_context: str = "",
    reason: str = "",
) -> str:
    """Create a PR in the GitOps repository with remediation changes.

    ONLY call this AFTER the user has explicitly confirmed the proposed changes.
    For updates, uses patch-based find/replace for surgical edits.

    Args:
        service: Service name being remediated.
        action_summary: Brief description (e.g. "scale-replicas").
        changes_json: JSON string of changes list. Each change has:
            - file_path: path in repo
            - action: "update" or "create"
            - patches: (for update) list of {old_string, new_string}
            - content: (for create) full file content
        incident_context: Description of the incident.
        reason: Why these changes are needed.

    Returns:
        JSON with pr_number, pr_url, branch, and files_changed.
    """
    if not service:
        return json.dumps({"error": "service is required"})
    if not action_summary:
        return json.dumps({"error": "action_summary is required"})

    try:
        changes = json.loads(changes_json)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Invalid changes_json: {e}"})

    if not changes:
        return json.dumps({"error": "changes list cannot be empty"})

    gitops_repo, base_path, base_branch = _get_gitops_config()

    # Validate each change
    for change in changes:
        file_path = change.get("file_path", "")
        action = change.get("action", "")

        if not file_path:
            return json.dumps({"error": "Each change requires file_path"})

        path_error = _validate_gitops_path(file_path, base_path)
        if path_error:
            return json.dumps({"error": path_error})

        if action not in ("update", "create"):
            return json.dumps({
                "error": f"Invalid action '{action}'. Must be 'update' or 'create'."
            })

        if action == "update":
            patches = change.get("patches", [])
            if not patches:
                return json.dumps({
                    "error": "Update action requires a non-empty patches list"
                })
            for i, patch in enumerate(patches):
                if not patch.get("old_string"):
                    return json.dumps({"error": f"Patch {i} requires old_string"})
                if "new_string" not in patch:
                    return json.dumps({"error": f"Patch {i} requires new_string"})
        elif action == "create":
            if not change.get("content"):
                return json.dumps({"error": "Create action requires content"})

    try:
        gh = _get_github_client()
        repo = gh.get_repo(gitops_repo)

        # Create branch
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safe_action = re.sub(r"[^a-zA-Z0-9-]", "-", action_summary.lower())[:30]
        safe_service = re.sub(r"[^a-zA-Z0-9-]", "-", service.lower())[:30]
        branch_name = f"oncall-agent/{safe_service}-{safe_action}-{timestamp}"

        base_ref = repo.get_git_ref(f"heads/{base_branch}")
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)

        # Commit each change
        files_changed = []
        for change in changes:
            file_path = change["file_path"]
            action = change["action"]

            if action == "update":
                existing = repo.get_contents(file_path, ref=branch_name)
                original_content = existing.decoded_content.decode("utf-8")

                patched_content, patch_error = _apply_patches(
                    original_content, change["patches"]
                )
                if patch_error:
                    return json.dumps({
                        "error": f"Patch failed for {file_path}: {patch_error}",
                        "service": service,
                    })

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

        # Create PR
        pr_body = _build_pr_body(
            service=service,
            action_summary=action_summary,
            reason=reason,
            incident_context=incident_context,
            changes=changes,
        )

        pr = repo.create_pull(
            title=f"[oncall-agent] {service}: {action_summary}",
            body=pr_body,
            head=branch_name,
            base=base_branch,
        )

        try:
            pr.add_to_labels("oncall-agent", "automated")
        except Exception as label_err:
            logger.warning(f"Could not add labels to PR: {label_err}")

        logger.info(f"Created PR #{pr.number}: {pr.html_url}")

        return json.dumps({
            "pr_number": pr.number,
            "pr_url": pr.html_url,
            "branch": branch_name,
            "files_changed": files_changed,
        })

    except Exception as e:
        logger.error(f"Error creating remediation PR: {e}")
        return json.dumps({
            "error": str(e),
            "service": service,
            "action_summary": action_summary,
        })


@tool
def create_document_pr(filename: str, content: str, description: str) -> str:
    """Create a PR to save a markdown document to the docs repo.

    Saves files under docs/ in the claude-agents repository.

    Args:
        filename: Markdown filename (e.g. "kubernetes-runbook.md").
        content: Full markdown content to save.
        description: Brief description for PR title and commit message.

    Returns:
        JSON with pr_number, pr_url, branch, and file_path.
    """
    if not filename:
        return json.dumps({"error": "filename is required"})
    if not content:
        return json.dumps({"error": "content is required"})
    if not description:
        return json.dumps({"error": "description is required"})

    if ".." in filename or "/" in filename or "\\" in filename:
        return json.dumps({
            "error": f"Invalid filename '{filename}': must be a plain filename "
            "without path separators or '..'"
        })

    if not filename.endswith(".md"):
        filename = f"{filename}.md"

    file_path = f"docs/{filename}"
    docs_repo = DOCS_REPO or os.getenv("DOCS_REPO", "arigsela/claude-agents")

    try:
        gh = _get_github_client()
        repo = gh.get_repo(docs_repo)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(
            r"[^a-zA-Z0-9-]", "-", filename.replace(".md", "").lower()
        )[:40]
        branch_name = f"oncall-agent/docs-{safe_name}-{timestamp}"

        default_branch = repo.default_branch
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha
        )

        repo.create_file(
            path=file_path,
            message=f"oncall-agent: add {filename} - {description}",
            content=content,
            branch=branch_name,
        )

        pr = repo.create_pull(
            title=f"[oncall-agent] docs: {description}",
            body=(
                f"## Document PR\n\n"
                f"**File**: `{file_path}`\n"
                f"**Description**: {description}\n\n"
                f"---\n*Created by oncall-crewai*"
            ),
            head=branch_name,
            base=default_branch,
        )

        try:
            pr.add_to_labels("oncall-agent", "docs")
        except Exception as label_err:
            logger.warning(f"Could not add labels to PR: {label_err}")

        logger.info(f"Created document PR #{pr.number}: {pr.html_url}")

        return json.dumps({
            "pr_number": pr.number,
            "pr_url": pr.html_url,
            "branch": branch_name,
            "file_path": file_path,
        })

    except Exception as e:
        logger.error(f"Error creating document PR: {e}")
        return json.dumps({"error": str(e), "filename": filename})
