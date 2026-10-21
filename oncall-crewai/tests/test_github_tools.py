"""Tests for GitHub agent tools (CrewAI @tool format).

Each tool is tested with:
- Positive cases using mocked PyGithub responses
- Error/validation cases
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture(autouse=True)
def github_env(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITOPS_REPO", "arigsela/kubernetes")
    monkeypatch.setenv("GITOPS_BASE_PATH", "base-apps/")
    monkeypatch.setenv("GITOPS_BASE_BRANCH", "main")
    monkeypatch.setenv("DOCS_REPO", "arigsela/claude-agents")


@pytest.fixture
def mock_github():
    """Create a mock GitHub client and repo."""
    mock_gh = MagicMock()
    mock_repo = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    return mock_gh, mock_repo


# ============================================================
# Helper tests
# ============================================================


class TestHelpers:
    def test_validate_gitops_path_valid(self):
        from github_agent.tools import _validate_gitops_path

        assert _validate_gitops_path("base-apps/myapp/deploy.yaml", "base-apps/") is None

    def test_validate_gitops_path_traversal(self):
        from github_agent.tools import _validate_gitops_path

        result = _validate_gitops_path("base-apps/../../etc/passwd", "base-apps/")
        assert result is not None
        assert "outside allowed base path" in result

    def test_validate_gitops_path_outside(self):
        from github_agent.tools import _validate_gitops_path

        result = _validate_gitops_path("other-dir/file.yaml", "base-apps/")
        assert result is not None

    def test_apply_patches_success(self):
        from github_agent.tools import _apply_patches

        content = "replicas: 1\nimage: nginx:latest"
        patches = [{"old_string": "replicas: 1", "new_string": "replicas: 3"}]
        result, error = _apply_patches(content, patches)
        assert error is None
        assert "replicas: 3" in result

    def test_apply_patches_not_found(self):
        from github_agent.tools import _apply_patches

        content = "replicas: 1"
        patches = [{"old_string": "replicas: 5", "new_string": "replicas: 3"}]
        _, error = _apply_patches(content, patches)
        assert error is not None
        assert "not found" in error

    def test_apply_patches_multiple_matches(self):
        from github_agent.tools import _apply_patches

        content = "replicas: 1\nreplicas: 1"
        patches = [{"old_string": "replicas: 1", "new_string": "replicas: 3"}]
        _, error = _apply_patches(content, patches)
        assert error is not None
        assert "matched 2 times" in error

    def test_apply_patches_empty_old_string(self):
        from github_agent.tools import _apply_patches

        content = "replicas: 1"
        patches = [{"old_string": "", "new_string": "replicas: 3"}]
        _, error = _apply_patches(content, patches)
        assert error is not None
        assert "cannot be empty" in error


# ============================================================
# search_recent_deployments
# ============================================================


class TestSearchRecentDeployments:
    def test_returns_deployments(self, mock_github):
        from github_agent.tools import search_recent_deployments

        mock_gh, mock_repo = mock_github
        run = MagicMock()
        run.id = 123
        run.name = "Deploy"
        run.status = "completed"
        run.conclusion = "success"
        run.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        run.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        run.head_branch = "main"
        run.head_sha = "abc12345def"
        run.html_url = "https://github.com/repo/actions/runs/123"
        mock_repo.get_workflow_runs.return_value = [run]

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                search_recent_deployments.run(repo_name="arigsela/kubernetes")
            )

        assert len(result["deployments"]) == 1
        assert result["deployments"][0]["name"] == "Deploy"
        assert result["deployments"][0]["conclusion"] == "success"

    def test_filters_by_workflow_name(self, mock_github):
        from github_agent.tools import search_recent_deployments

        mock_gh, mock_repo = mock_github
        run1 = MagicMock()
        run1.id, run1.name, run1.status, run1.conclusion = 1, "Deploy", "completed", "success"
        run1.created_at = run1.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        run1.head_branch, run1.head_sha, run1.html_url = "main", "abc12345", "http://url"

        run2 = MagicMock()
        run2.id, run2.name, run2.status, run2.conclusion = 2, "Lint", "completed", "success"
        run2.created_at = run2.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        run2.head_branch, run2.head_sha, run2.html_url = "main", "def12345", "http://url2"

        mock_repo.get_workflow_runs.return_value = [run1, run2]

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                search_recent_deployments.run(
                    repo_name="arigsela/kubernetes", workflow_name="Deploy"
                )
            )

        assert len(result["deployments"]) == 1
        assert result["deployments"][0]["name"] == "Deploy"

    def test_error_returns_json(self, mock_github):
        from github_agent.tools import search_recent_deployments

        mock_gh, _ = mock_github
        mock_gh.get_repo.side_effect = Exception("Repo not found")

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                search_recent_deployments.run(repo_name="bad/repo")
            )

        assert "error" in result


# ============================================================
# get_gitops_file
# ============================================================


class TestGetGitopsFile:
    def test_returns_file_content(self, mock_github):
        from github_agent.tools import get_gitops_file

        mock_gh, mock_repo = mock_github
        mock_content = MagicMock()
        mock_content.decoded_content = b"apiVersion: apps/v1\nkind: Deployment\n"
        mock_content.sha = "abc123"
        mock_content.html_url = "https://github.com/repo/blob/main/base-apps/myapp/deploy.yaml"
        mock_repo.get_contents.return_value = mock_content

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                get_gitops_file.run(file_path="base-apps/myapp/deploy.yaml")
            )

        assert "error" not in result
        assert "apiVersion: apps/v1" in result["content"]
        assert result["sha"] == "abc123"

    def test_blocked_path(self):
        from github_agent.tools import get_gitops_file

        result = json.loads(
            get_gitops_file.run(file_path="other-dir/secret.yaml")
        )

        assert "error" in result
        assert "outside allowed base path" in result["error"]

    def test_path_traversal(self):
        from github_agent.tools import get_gitops_file

        result = json.loads(
            get_gitops_file.run(file_path="base-apps/../../etc/passwd")
        )

        assert "error" in result
        assert "outside allowed base path" in result["error"]

    def test_directory_returns_error(self, mock_github):
        from github_agent.tools import get_gitops_file

        mock_gh, mock_repo = mock_github
        mock_repo.get_contents.return_value = [MagicMock(), MagicMock()]

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                get_gitops_file.run(file_path="base-apps/myapp")
            )

        assert "error" in result
        assert "directory" in result["error"].lower()


# ============================================================
# list_gitops_directory
# ============================================================


class TestListGitopsDirectory:
    def test_returns_entries(self, mock_github):
        from github_agent.tools import list_gitops_directory

        mock_gh, mock_repo = mock_github
        dir_item = MagicMock()
        dir_item.name = "myapp"
        dir_item.path = "base-apps/myapp"
        dir_item.type = "dir"
        dir_item.size = 0

        file_item = MagicMock()
        file_item.name = "kustomization.yaml"
        file_item.path = "base-apps/kustomization.yaml"
        file_item.type = "file"
        file_item.size = 256

        mock_repo.get_contents.return_value = [file_item, dir_item]

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                list_gitops_directory.run(dir_path="base-apps/")
            )

        assert result["count"] == 2
        # Directories should come first
        assert result["entries"][0]["type"] == "dir"
        assert result["entries"][1]["type"] == "file"

    def test_blocked_path(self):
        from github_agent.tools import list_gitops_directory

        result = json.loads(
            list_gitops_directory.run(dir_path="secret-dir/")
        )

        assert "error" in result

    def test_error_returns_json(self, mock_github):
        from github_agent.tools import list_gitops_directory

        mock_gh, mock_repo = mock_github
        mock_repo.get_contents.side_effect = Exception("Not found")

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                list_gitops_directory.run(dir_path="base-apps/nonexistent")
            )

        assert "error" in result


# ============================================================
# create_remediation_pr
# ============================================================


class TestCreateRemediationPr:
    def test_validation_missing_service(self):
        from github_agent.tools import create_remediation_pr

        result = json.loads(
            create_remediation_pr.run(
                service="",
                action_summary="test",
                changes_json="[]",
            )
        )
        assert "error" in result
        assert "service" in result["error"]

    def test_validation_invalid_json(self):
        from github_agent.tools import create_remediation_pr

        result = json.loads(
            create_remediation_pr.run(
                service="myapp",
                action_summary="test",
                changes_json="not-json",
            )
        )
        assert "error" in result
        assert "Invalid changes_json" in result["error"]

    def test_validation_path_traversal(self):
        from github_agent.tools import create_remediation_pr

        changes = json.dumps([{
            "file_path": "../../etc/passwd",
            "action": "update",
            "patches": [{"old_string": "x", "new_string": "y"}],
        }])

        result = json.loads(
            create_remediation_pr.run(
                service="myapp",
                action_summary="test",
                changes_json=changes,
            )
        )
        assert "error" in result
        assert "outside allowed base path" in result["error"]

    def test_validation_invalid_action(self):
        from github_agent.tools import create_remediation_pr

        changes = json.dumps([{
            "file_path": "base-apps/myapp/deploy.yaml",
            "action": "delete",
        }])

        result = json.loads(
            create_remediation_pr.run(
                service="myapp",
                action_summary="test",
                changes_json=changes,
            )
        )
        assert "error" in result
        assert "delete" in result["error"]

    def test_successful_pr_creation(self, mock_github):
        from github_agent.tools import create_remediation_pr

        mock_gh, mock_repo = mock_github

        # Mock branch creation
        base_ref = MagicMock()
        base_ref.object.sha = "abc123"
        mock_repo.get_git_ref.return_value = base_ref

        # Mock file read for update
        existing = MagicMock()
        existing.decoded_content = b"replicas: 1\nimage: nginx:latest"
        existing.sha = "file-sha"
        mock_repo.get_contents.return_value = existing

        # Mock PR creation
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.html_url = "https://github.com/arigsela/kubernetes/pull/42"
        mock_repo.create_pull.return_value = mock_pr

        changes = json.dumps([{
            "file_path": "base-apps/myapp/deploy.yaml",
            "action": "update",
            "patches": [{"old_string": "replicas: 1", "new_string": "replicas: 3"}],
        }])

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                create_remediation_pr.run(
                    service="myapp",
                    action_summary="scale-replicas",
                    changes_json=changes,
                    incident_context="Pod crash loops",
                    reason="Increase replicas for stability",
                )
            )

        assert result["pr_number"] == 42
        assert "pull/42" in result["pr_url"]
        assert "base-apps/myapp/deploy.yaml" in result["files_changed"]


# ============================================================
# create_document_pr
# ============================================================


class TestCreateDocumentPr:
    def test_validation_missing_filename(self):
        from github_agent.tools import create_document_pr

        result = json.loads(
            create_document_pr.run(filename="", content="test", description="test")
        )
        assert "error" in result

    def test_validation_path_traversal_in_filename(self):
        from github_agent.tools import create_document_pr

        result = json.loads(
            create_document_pr.run(
                filename="../secret.md", content="test", description="test"
            )
        )
        assert "error" in result
        assert "path separators" in result["error"] or ".." in result["error"]

    def test_successful_document_pr(self, mock_github):
        from github_agent.tools import create_document_pr

        mock_gh, mock_repo = mock_github
        mock_repo.default_branch = "main"

        base_ref = MagicMock()
        base_ref.object.sha = "abc123"
        mock_repo.get_git_ref.return_value = base_ref

        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_pr.html_url = "https://github.com/arigsela/claude-agents/pull/99"
        mock_repo.create_pull.return_value = mock_pr

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                create_document_pr.run(
                    filename="runbook.md",
                    content="# Runbook\nSteps...",
                    description="Add K8s runbook",
                )
            )

        assert result["pr_number"] == 99
        assert result["file_path"] == "docs/runbook.md"

    def test_appends_md_extension(self, mock_github):
        from github_agent.tools import create_document_pr

        mock_gh, mock_repo = mock_github
        mock_repo.default_branch = "main"
        base_ref = MagicMock()
        base_ref.object.sha = "abc123"
        mock_repo.get_git_ref.return_value = base_ref
        mock_pr = MagicMock()
        mock_pr.number = 1
        mock_pr.html_url = "http://url"
        mock_repo.create_pull.return_value = mock_pr

        with patch("github_agent.tools._get_github_client", return_value=mock_gh):
            result = json.loads(
                create_document_pr.run(
                    filename="guide",
                    content="content",
                    description="desc",
                )
            )

        assert result["file_path"] == "docs/guide.md"
