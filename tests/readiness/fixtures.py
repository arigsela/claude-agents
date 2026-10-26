"""Builders for tests: git repos and file:// bare remotes made in temp dirs, independent of global git config."""
from __future__ import annotations

import subprocess
from pathlib import Path

IDENT = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-c", "init.defaultBranch=main"]


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *IDENT, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def write_files(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def commit_files(repo: Path, files: dict[str, str], message: str = "c") -> str:
    write_files(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def git_repo(tmp: Path, files: dict[str, str], branch: str = "main") -> Path:
    """A repo at `tmp/repo-<n>` with one commit of `files` on `branch`."""
    n = len([p for p in tmp.iterdir() if p.name.startswith("repo-")])
    repo = tmp / f"repo-{n}"
    repo.mkdir()
    git(repo, "init", "--quiet", "-b", branch)
    commit_files(repo, files, "init")
    return repo


def bare_remote(tmp: Path, files: dict[str, str], branches: dict[str, dict] | None = None) -> str:
    """A bare repo whose `main` holds `files`; each extra branch is `files` overlaid with its own dict.
    Returns its file:// URL."""
    src = git_repo(tmp, files, "main")
    for name, extra in (branches or {}).items():
        git(src, "checkout", "--quiet", "-b", name, "main")
        commit_files(src, extra, f"branch {name}")
        git(src, "checkout", "--quiet", "main")
    bare = tmp / f"remote-{src.name}.git"
    git(tmp, "clone", "--quiet", "--bare", str(src), str(bare))
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    return bare.as_uri()
