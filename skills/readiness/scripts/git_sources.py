#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: read the app repo at a commit (git archive) and the deploy repo from a temp shallow clone.

Never fetches into the user's checkout and never reads their working tree."""
from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
_SLUG = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def _git(*args: str, cwd: Path | None = None, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check,
                          env=_ENV, timeout=timeout)


def slug_from_remote(url: str) -> str | None:
    """`owner/repo` for a github.com remote URL (ssh, scp-style or https), else None."""
    m = _SLUG.search(url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def github_url(slug: str) -> str:
    return f"https://github.com/{slug}.git"


def export_commit(repo: Path, sha: str, dest: Path) -> None:
    """Extract the tree of `sha` into `dest`; untracked and uncommitted files never appear."""
    out = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha],
                         capture_output=True, check=True, env=_ENV).stdout
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(out)) as tar:
        for member in tar.getmembers():
            p = PurePosixPath(member.name)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"unsafe path in archive: {member.name}")
        tar.extractall(dest, filter="data")


def _remote_head(url: str, cwd: Path | None = None) -> tuple[str | None, str | None]:
    """(default branch name, its sha) from `git ls-remote --symref <url> HEAD`; (None, None) on failure."""
    try:
        r = _git("ls-remote", "--symref", url, "HEAD", cwd=cwd, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None, None
    branch = sha = None
    for line in r.stdout.splitlines():
        if line.startswith("ref:"):
            m = re.match(r"ref:\s+refs/heads/(\S+)\s+HEAD", line)
            branch = m.group(1) if m else None
        else:
            parts = line.split()
            if len(parts) == 2 and parts[1] == "HEAD":
                sha = parts[0]
    return branch, sha


def default_branch(url: str) -> str | None:
    return _remote_head(url)[0]


def app_ref_info(repo: Path, ref: str = "HEAD") -> dict:
    """Facts about `ref` in the user's checkout: slug, branch, sha, the origin's default branch name and
    whether `ref` is on it.

    `on_default_branch` is True when the sha is the default branch's tip or is an ancestor of it (the commit is on
    that branch), False when the tip is present locally and the sha is not reachable from it, and None when it cannot be told
    (no origin, offline, or the tip is not present locally; this never fetches)."""
    repo = Path(repo)
    sha = _git("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=repo).stdout.strip()
    branch = _git("rev-parse", "--abbrev-ref", ref, cwd=repo, check=False).stdout.strip()
    if branch in ("", "HEAD", sha):
        branch = None
    origin = _git("remote", "get-url", "origin", cwd=repo, check=False).stdout.strip()
    slug = slug_from_remote(origin) if origin else None
    dflt, tip = _remote_head("origin", cwd=repo) if origin else (None, None)
    on_default: bool | None = None
    if tip:
        if sha == tip:
            on_default = True
        elif _git("cat-file", "-e", f"{tip}^{{commit}}", cwd=repo, check=False).returncode == 0:
            r = _git("merge-base", "--is-ancestor", sha, tip, cwd=repo, check=False)
            on_default = r.returncode == 0
    return {"path": str(repo), "slug": slug, "branch": branch, "sha": sha,
            "on_default_branch": on_default, "default_branch": dflt}


def remote_checkout(url: str, ref: str, dest: Path) -> str:
    """Shallow, blobless checkout of `ref` (branch, tag, sha or HEAD) at `url` into `dest`; returns the sha.

    Symlinks in the tree are written as plain files holding the link text, so no read follows one out of `dest`."""
    if ref.startswith("-"):
        raise ValueError(f"unsafe ref: {ref!r}")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", "--quiet", cwd=dest)
    _git("config", "core.symlinks", "false", cwd=dest)
    _git("remote", "add", "origin", url, cwd=dest)
    # gh's token covers private repos. The empty entry drops inherited helpers so a stale credential cannot win.
    _git("config", "credential.helper", "", cwd=dest)
    _git("config", "--add", "credential.helper", "!gh auth git-credential", cwd=dest)
    _git("fetch", "--quiet", "--depth", "1", "--filter=blob:none", "--", "origin", ref, cwd=dest, timeout=600)
    _git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=dest, timeout=600)
    return _git("rev-parse", "HEAD", cwd=dest).stdout.strip()
