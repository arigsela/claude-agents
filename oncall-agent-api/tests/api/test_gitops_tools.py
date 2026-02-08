"""
Tests for GitOps PR tools (get_gitops_file, list_gitops_directory, create_remediation_pr)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.custom_tools import (
    get_gitops_file,
    list_gitops_directory,
    create_remediation_pr,
)


@pytest.fixture
def mock_github():
    """Create a mock GitHub client and repo."""
    mock_gh = Mock()
    mock_repo = Mock()
    mock_gh.get_repo.return_value = mock_repo
    return mock_gh, mock_repo


@pytest.fixture
def gitops_env(monkeypatch):
    """Set GitOps environment variables."""
    monkeypatch.setenv("GITOPS_REPO", "arigsela/kubernetes")
    monkeypatch.setenv("GITOPS_BASE_PATH", "base-apps/")
    monkeypatch.setenv("GITOPS_BASE_BRANCH", "main")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")


# ============================================================
# get_gitops_file tests
# ============================================================


@pytest.mark.asyncio
async def test_get_gitops_file_valid_path(mock_github, gitops_env):
    """Test reading a valid file from the GitOps repo."""
    mock_gh, mock_repo = mock_github

    # Mock file contents
    mock_content = Mock()
    mock_content.decoded_content = b"apiVersion: apps/v1\nkind: Deployment\n"
    mock_content.sha = "abc123"
    mock_content.html_url = "https://github.com/arigsela/kubernetes/blob/main/base-apps/myapp/deployment.yaml"
    mock_repo.get_contents.return_value = mock_content

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await get_gitops_file({"file_path": "base-apps/myapp/deployment.yaml"})

    assert "error" not in result
    assert result["repository"] == "arigsela/kubernetes"
    assert result["file_path"] == "base-apps/myapp/deployment.yaml"
    assert "apiVersion: apps/v1" in result["content"]
    assert result["sha"] == "abc123"
    assert "html_url" in result


@pytest.mark.asyncio
async def test_get_gitops_file_blocked_path(gitops_env):
    """Test that paths outside base-apps/ are rejected."""
    result = await get_gitops_file({"file_path": "some-other-dir/secret.yaml"})

    assert "error" in result
    assert "outside allowed base path" in result["error"]


@pytest.mark.asyncio
async def test_get_gitops_file_path_traversal(gitops_env):
    """Test that path traversal attempts are blocked."""
    result = await get_gitops_file({"file_path": "base-apps/../../etc/passwd"})

    assert "error" in result


# ============================================================
# list_gitops_directory tests
# ============================================================


@pytest.mark.asyncio
async def test_list_gitops_directory_valid(mock_github, gitops_env):
    """Test listing a valid directory in the GitOps repo."""
    mock_gh, mock_repo = mock_github

    # Mock directory contents
    mock_dir = Mock()
    mock_dir.name = "chores-tracker-backend"
    mock_dir.path = "base-apps/chores-tracker-backend"
    mock_dir.type = "dir"
    mock_dir.size = 0

    mock_file = Mock()
    mock_file.name = "kustomization.yaml"
    mock_file.path = "base-apps/kustomization.yaml"
    mock_file.type = "file"
    mock_file.size = 256

    mock_repo.get_contents.return_value = [mock_file, mock_dir]

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await list_gitops_directory({"dir_path": "base-apps/"})

    assert "error" not in result
    assert result["repository"] == "arigsela/kubernetes"
    assert result["count"] == 2
    # Directories should come first
    assert result["entries"][0]["type"] == "dir"
    assert result["entries"][1]["type"] == "file"


@pytest.mark.asyncio
async def test_list_gitops_directory_blocked_path(gitops_env):
    """Test that paths outside base-apps/ are rejected."""
    result = await list_gitops_directory({"dir_path": "other-dir/"})

    assert "error" in result
    assert "outside allowed base path" in result["error"]


# ============================================================
# create_remediation_pr tests
# ============================================================


@pytest.mark.asyncio
async def test_create_pr_success(mock_github, gitops_env):
    """Test successful PR creation."""
    mock_gh, mock_repo = mock_github

    # Mock branch ref
    mock_ref = Mock()
    mock_ref.object.sha = "base-sha-123"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref.return_value = Mock()

    # Mock existing file for update
    mock_existing = Mock()
    mock_existing.sha = "file-sha-456"
    mock_repo.get_contents.return_value = mock_existing
    mock_repo.update_file.return_value = Mock()

    # Mock PR creation
    mock_pr = Mock()
    mock_pr.number = 42
    mock_pr.html_url = "https://github.com/arigsela/kubernetes/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_remediation_pr({
            "service": "chores-tracker-backend",
            "action_summary": "scale-replicas",
            "changes": [
                {
                    "file_path": "base-apps/chores-tracker-backend/deployment.yaml",
                    "content": "apiVersion: apps/v1\nkind: Deployment\nspec:\n  replicas: 2\n",
                    "action": "update",
                },
            ],
            "incident_context": "Service is under high load",
            "reason": "Scale from 1 to 2 replicas",
        })

    assert "error" not in result
    assert result["pr_number"] == 42
    assert "pull/42" in result["pr_url"]
    assert "oncall-agent/" in result["branch"]
    assert len(result["files_changed"]) == 1

    # Verify branch was created
    mock_repo.create_git_ref.assert_called_once()
    branch_ref = mock_repo.create_git_ref.call_args[1]["ref"]
    assert branch_ref.startswith("refs/heads/oncall-agent/chores-tracker-backend-scale-replicas-")

    # Verify PR was created with correct target
    mock_repo.create_pull.assert_called_once()
    call_kwargs = mock_repo.create_pull.call_args[1]
    assert call_kwargs["base"] == "main"
    assert "oncall-agent" in call_kwargs["title"]


@pytest.mark.asyncio
async def test_create_pr_blocked_path(gitops_env):
    """Test that file paths outside base-apps/ are rejected."""
    result = await create_remediation_pr({
        "service": "myservice",
        "action_summary": "update-config",
        "changes": [
            {
                "file_path": "some-other-dir/config.yaml",
                "content": "key: value",
                "action": "update",
            },
        ],
        "incident_context": "test",
        "reason": "test",
    })

    assert "error" in result
    assert "outside allowed base path" in result["error"]


@pytest.mark.asyncio
async def test_create_pr_invalid_action(gitops_env):
    """Test that invalid actions (like delete) are rejected."""
    result = await create_remediation_pr({
        "service": "myservice",
        "action_summary": "delete-config",
        "changes": [
            {
                "file_path": "base-apps/myservice/config.yaml",
                "content": "some content",
                "action": "delete",
            },
        ],
        "incident_context": "test",
        "reason": "test",
    })

    assert "error" in result
    assert "Invalid action" in result["error"]


@pytest.mark.asyncio
async def test_create_pr_empty_changes(gitops_env):
    """Test that empty changes list is rejected."""
    result = await create_remediation_pr({
        "service": "myservice",
        "action_summary": "do-nothing",
        "changes": [],
        "incident_context": "test",
        "reason": "test",
    })

    assert "error" in result
    assert "empty" in result["error"]


@pytest.mark.asyncio
async def test_create_pr_branch_naming(mock_github, gitops_env):
    """Test that branch names follow the expected pattern."""
    mock_gh, mock_repo = mock_github

    mock_ref = Mock()
    mock_ref.object.sha = "base-sha"
    mock_repo.get_git_ref.return_value = mock_ref

    mock_existing = Mock()
    mock_existing.sha = "file-sha"
    mock_repo.get_contents.return_value = mock_existing

    mock_pr = Mock()
    mock_pr.number = 1
    mock_pr.html_url = "https://github.com/arigsela/kubernetes/pull/1"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_remediation_pr({
            "service": "chores-tracker-backend",
            "action_summary": "increase-memory-limit",
            "changes": [
                {
                    "file_path": "base-apps/chores-tracker-backend/deployment.yaml",
                    "content": "content",
                    "action": "update",
                },
            ],
            "incident_context": "OOMKilled",
            "reason": "Increase memory limit",
        })

    assert "error" not in result
    branch = result["branch"]
    assert branch.startswith("oncall-agent/")
    assert "chores-tracker-backend" in branch
    assert "increase-memory-limit" in branch
    # Should have a timestamp suffix (YYYYMMDD-HHMMSS)
    parts = branch.split("-")
    assert len(parts) >= 4  # Has enough parts for the timestamp
