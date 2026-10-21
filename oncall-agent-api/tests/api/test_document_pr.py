"""
Tests for create_document_pr tool
"""

import pytest
from unittest.mock import Mock, patch

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.custom_tools import create_document_pr


@pytest.fixture
def mock_github():
    """Create a mock GitHub client and repo."""
    mock_gh = Mock()
    mock_repo = Mock()
    mock_gh.get_repo.return_value = mock_repo
    mock_repo.default_branch = "main"
    return mock_gh, mock_repo


@pytest.fixture
def docs_env(monkeypatch):
    """Set environment variables for document PR tests."""
    monkeypatch.setenv("DOCS_REPO", "arigsela/claude-agents")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")


# ============================================================
# Validation tests
# ============================================================


@pytest.mark.asyncio
async def test_missing_filename():
    """Test that missing filename returns error."""
    result = await create_document_pr({
        "content": "# Hello",
        "description": "test doc",
    })
    assert "error" in result
    assert "filename" in result["error"]


@pytest.mark.asyncio
async def test_missing_content():
    """Test that missing content returns error."""
    result = await create_document_pr({
        "filename": "test.md",
        "description": "test doc",
    })
    assert "error" in result
    assert "content" in result["error"]


@pytest.mark.asyncio
async def test_missing_description():
    """Test that missing description returns error."""
    result = await create_document_pr({
        "filename": "test.md",
        "content": "# Hello",
    })
    assert "error" in result
    assert "description" in result["error"]


# ============================================================
# Path traversal / security tests
# ============================================================


@pytest.mark.asyncio
async def test_path_traversal_rejected():
    """Test that path traversal in filename is rejected."""
    result = await create_document_pr({
        "filename": "../../etc/passwd",
        "content": "malicious",
        "description": "hack attempt",
    })
    assert "error" in result
    assert "Invalid filename" in result["error"]


@pytest.mark.asyncio
async def test_slash_in_filename_rejected():
    """Test that forward slashes in filename are rejected."""
    result = await create_document_pr({
        "filename": "subdir/file.md",
        "content": "# Hello",
        "description": "test doc",
    })
    assert "error" in result
    assert "Invalid filename" in result["error"]


@pytest.mark.asyncio
async def test_backslash_in_filename_rejected():
    """Test that backslashes in filename are rejected."""
    result = await create_document_pr({
        "filename": "subdir\\file.md",
        "content": "# Hello",
        "description": "test doc",
    })
    assert "error" in result
    assert "Invalid filename" in result["error"]


# ============================================================
# .md extension auto-append test
# ============================================================


@pytest.mark.asyncio
async def test_md_extension_appended(mock_github, docs_env):
    """Test that .md extension is appended if missing."""
    mock_gh, mock_repo = mock_github

    # Mock branch ref
    mock_ref = Mock()
    mock_ref.object.sha = "base-sha-123"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref.return_value = Mock()
    mock_repo.create_file.return_value = Mock()

    # Mock PR
    mock_pr = Mock()
    mock_pr.number = 10
    mock_pr.html_url = "https://github.com/arigsela/claude-agents/pull/10"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_document_pr({
            "filename": "my-document",
            "content": "# My Document",
            "description": "test doc",
        })

    assert "error" not in result
    assert result["file_path"] == "docs/my-document.md"


# ============================================================
# Successful PR creation test
# ============================================================


@pytest.mark.asyncio
async def test_successful_pr_creation(mock_github, docs_env):
    """Test successful document PR creation returns expected fields."""
    mock_gh, mock_repo = mock_github

    # Mock branch ref
    mock_ref = Mock()
    mock_ref.object.sha = "base-sha-123"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref.return_value = Mock()
    mock_repo.create_file.return_value = Mock()

    # Mock PR
    mock_pr = Mock()
    mock_pr.number = 42
    mock_pr.html_url = "https://github.com/arigsela/claude-agents/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_document_pr({
            "filename": "kubernetes-interview-questions.md",
            "content": "# Kubernetes Interview Questions\n\n1. What is a Pod?",
            "description": "Add K8s interview questions",
        })

    assert "error" not in result
    assert result["pr_number"] == 42
    assert "pull/42" in result["pr_url"]
    assert result["file_path"] == "docs/kubernetes-interview-questions.md"
    assert result["branch"].startswith("oncall-agent/docs-")

    # Verify create_file was called with correct path
    create_call = mock_repo.create_file.call_args
    assert create_call[1]["path"] == "docs/kubernetes-interview-questions.md"
    assert "Kubernetes Interview Questions" in create_call[1]["content"]

    # Verify PR was created against the default branch
    pr_call = mock_repo.create_pull.call_args[1]
    assert pr_call["base"] == "main"
    assert "oncall-agent" in pr_call["title"]

    # Verify labels were added
    mock_pr.add_to_labels.assert_called_once_with("oncall-agent", "docs")


# ============================================================
# Default repo fallback test
# ============================================================


@pytest.mark.asyncio
async def test_default_repo_fallback(mock_github, monkeypatch):
    """Test that DOCS_REPO defaults to arigsela/claude-agents when not set."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.delenv("DOCS_REPO", raising=False)

    mock_gh, mock_repo = mock_github

    mock_ref = Mock()
    mock_ref.object.sha = "base-sha"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref.return_value = Mock()
    mock_repo.create_file.return_value = Mock()

    mock_pr = Mock()
    mock_pr.number = 1
    mock_pr.html_url = "https://github.com/arigsela/claude-agents/pull/1"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_document_pr({
            "filename": "test.md",
            "content": "# Test",
            "description": "test",
        })

    assert "error" not in result
    # Verify it used the default repo
    mock_gh.get_repo.assert_called_with("arigsela/claude-agents")


# ============================================================
# Branch naming test
# ============================================================


@pytest.mark.asyncio
async def test_branch_naming_pattern(mock_github, docs_env):
    """Test that branch names follow the expected pattern."""
    mock_gh, mock_repo = mock_github

    mock_ref = Mock()
    mock_ref.object.sha = "base-sha"
    mock_repo.get_git_ref.return_value = mock_ref
    mock_repo.create_git_ref.return_value = Mock()
    mock_repo.create_file.return_value = Mock()

    mock_pr = Mock()
    mock_pr.number = 1
    mock_pr.html_url = "https://github.com/arigsela/claude-agents/pull/1"
    mock_repo.create_pull.return_value = mock_pr

    with patch("src.api.custom_tools._get_github_client", return_value=mock_gh):
        result = await create_document_pr({
            "filename": "k8s-runbook.md",
            "content": "# Runbook",
            "description": "K8s runbook",
        })

    assert "error" not in result
    branch = result["branch"]
    assert branch.startswith("oncall-agent/docs-")
    assert "k8s-runbook" in branch
