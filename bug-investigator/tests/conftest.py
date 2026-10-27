import json
import os
import subprocess

import pytest

from bug_investigator.util import CommandError, run

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}

APP_PY = """\
import json


def can_move(user, task):
    if user.role == "admin":
        return True
    return user.name == task.created_by
"""

PERMISSIONS_MD = """\
# Permissions

- **P1** A viewer may read every task.
- **P3** An editor may move a task that is assigned to them,
  whoever created it.
"""


def git(cwd, *args, date=None):
    env = dict(os.environ, **GIT_ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def commit(repo, files: dict, msg: str, date=None) -> str:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, date=date)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def app_repo(tmp_path):
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    first = commit(repo, {"src/app.py": "print('v1')\n", "docs/permissions.md": PERMISSIONS_MD}, "scaffold",
                   date="2026-10-20T10:00:00Z")
    second = commit(repo, {"src/app.py": APP_PY}, "Centralize permission checks (#14)", date="2026-10-27T09:10:00Z")
    return {"dir": str(repo), "first": first, "second": second}


def configmap(source: str) -> str:
    return (f"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: taskboard-code\n  annotations:\n"
            f"    taskboard.arigsela.com/source-commit: \"{source}\"\ndata:\n  app.py: |\n    print(1)\n")


@pytest.fixture
def deploy_repo(tmp_path, app_repo):
    repo = tmp_path / "deploy"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"base-apps/taskboard/code-configmap.yaml": configmap(app_repo["first"]),
                  "base-apps/taskboard/runbook.md": "# Runbook\n\n- **R1** Restart resets the data.\n"},
           "taskboard: deploy first", date="2026-10-20T11:00:00Z")
    commit(repo, {"base-apps/other/x.yaml": "x: 1\n"}, "other app", date="2026-10-21T11:00:00Z")
    commit(repo, {"base-apps/taskboard/code-configmap.yaml": configmap(app_repo["second"])},
           "taskboard: deploy second", date="2026-10-27T09:30:00Z")
    return {"dir": str(repo)}


class FakeGh:
    """Runs git for real; answers gh from a table keyed by the gh argv prefix."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[0] == "git":
            return run(cmd)
        for key, val in self.answers.items():
            if tuple(cmd[: len(key)]) == key:
                if isinstance(val, Exception):
                    raise val
                if callable(val):
                    return val(cmd)
                return val if isinstance(val, str) else json.dumps(val)
        raise CommandError(f"no fake answer for {cmd}")
