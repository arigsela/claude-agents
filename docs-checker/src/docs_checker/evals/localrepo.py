"""A local stand-in for the agent-docs MCP server: the docs repository at one commit, from a clone.

``local_repo_tools(clone, commit)`` returns the four read tools of server
``agent-docs-mcp``, wrapped by langchain-mcp-adapters the way production wraps
the real server (``handle_tool_errors=False``). Each answer has the shape
github-mcp-server v1.14.0 gives (tests/fixtures/mcp), so the tool belt and
``RepoReader`` parse both the same way:

- ``get_file_contents``: a file is a status line naming its blob, then the file
  as an embedded text resource, bytes as stored (no newline translation). An
  empty file says "empty", a binary one "binary", and one of 1 MiB or more comes
  back as a link. A directory is one compact JSON array of entries, in git's
  order. A path that is not in the tree goes to the server's tree fallback: up to
  three tree paths that end with it (not an error), or the not-found error.
- ``list_commits`` and ``get_commit``: compact JSON commits from ``git log``,
  dates in UTC. GitHub's account objects are left out, as GitHub leaves them out
  for an email that is not linked to an account.
- ``search_code``: always no items with ``incomplete_results`` true. That is what
  GitHub answers for arigsela/kubernetes, which is not in its code-search index
  (Ruling S1), so an eval never gets a search the deployment could not make (C#17).

The repository it serves: the default branch ``main`` points at ``commit``, and
only ``commit`` and its ancestors exist. ``overlays`` are planted at ``commit``
(mutations and extra docs for evals; Ruling O1), path to text: a text replaces the
file there or adds a new one (with any directories it needs), and ``None`` deletes
the file (it reads as absent and leaves every listing; a directory it empties goes
too). ``list_commits`` at ``commit`` names ``commit`` first for an overlay path and
every directory above one, as if the overlays were committed there. Other commits
read as stored. A directory an overlay changed keeps its tree sha (a new one gets a
made-up sha): nothing reads a tree by its sha.

Git runs as an argument list with ``check=False``, never through a shell. A ref
must be ``main`` or hex and a path may not climb with ``..``, so nothing from a
tool call reaches git as an option or leaves the repository.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    EmbeddedResource,
    ResourceLink,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
)

SERVER = "agent-docs-mcp"
DEFAULT_BRANCH = "main"

_DEFAULT_REFS = frozenset(
    {DEFAULT_BRANCH, "HEAD", f"heads/{DEFAULT_BRANCH}", f"refs/heads/{DEFAULT_BRANCH}"}
)
_HEX = re.compile(r"[0-9a-fA-F]{4,40}")
_SYMLINK = "120000"
_MAX_CONTENT = 1024 * 1024  # the server sends a link instead, at this size or more
_MAX_MATCHES = 3  # the tree fallback's maxMatchingFiles
_SNIFF_BYTES = 512  # what Go's http.DetectContentType looks at
# Go's text sniffer: any of these in the first 512 bytes means binary.
_BINARY_BYTES = frozenset([*range(0x09), 0x0B, *range(0x0E, 0x1B), *range(0x1C, 0x20)])

# The server's own words, as captured.
_NOT_FOUND = (
    "Failed to get file contents. The path does not point to a file or directory, "
    "or the file does not exist in the repository."
)
_BAD_TREE = (
    "failed to get git tree: Invalid object requested. SHA must identify a commit or a tree."
)
_NO_HITS = '{"total_count":0,"incomplete_results":true,"items":[]}'
_UNREADABLE = "failed to inspect repository file: content unavailable"
_CLIMBS = "the path must stay inside the repository"
# One commit as ``git log -z`` prints it: a field per line, the raw message last.
_LOG_FORMAT = "%H%n%an%n%ae%n%at%n%cn%n%ce%n%ct%n%B"

_GO_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def go_json(value: Any) -> str:
    """``value`` as Go's ``json.Marshal`` writes it: compact, UTF-8, with ``<``, ``>``,
    ``&``, U+2028 and U+2029 escaped (JSON has none of them outside strings)."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for char, escaped in _GO_ESCAPES.items():
        text = text.replace(char, escaped)
    return text


@dataclass(frozen=True)
class _Entry:
    mode: str
    kind: str  # blob, tree, or commit (a submodule)
    sha: str
    size: int  # a blob's bytes; 0 for a tree or a submodule
    path: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def parent(self) -> str:
        return self.path.rpartition("/")[0]


class _Tree:
    """A commit's whole tree, in git's recursive order (a tree before its contents)."""

    def __init__(self, entries: list[_Entry]):
        self.entries = entries
        self.by_path = {e.path: e for e in entries}
        self.children: dict[str, list[_Entry]] = {}
        for entry in entries:
            self.children.setdefault(entry.parent, []).append(entry)


def _climbs(path: str) -> bool:
    return ".." in path.replace("\\", "/").split("/")


def _is_file_path(path: str) -> bool:
    """A repository-relative file path: not empty, no leading or trailing ``/``, no
    empty, ``.`` or ``..`` segment."""
    return bool(path) and all(part not in ("", ".", "..") for part in path.split("/"))


def _git_order(entry: _Entry) -> list[bytes]:
    """The sort key of git's recursive order: siblings by name as bytes, a tree's
    name compared as if it ended in ``/``, and a tree's contents right after it."""
    parts = entry.path.split("/")
    names = [part + "/" for part in parts[:-1]]
    names.append(parts[-1] + ("/" if entry.kind == "tree" else ""))
    return [name.encode() for name in names]


def _blob_sha(data: bytes) -> str:
    """The sha git gives a blob with these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _is_binary(data: bytes) -> bool:
    return any(byte in _BINARY_BYTES for byte in data[:_SNIFF_BYTES])


def _git_env() -> dict[str, str]:
    """No GIT_* variables (a hook's GIT_DIR would point git at another repository);
    pathspecs are literal, as GitHub's ``path`` is a path, not a glob."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _arg(args: Mapping[str, Any], key: str) -> str:
    value = args.get(key)
    return "" if value is None else str(value)


def _number(args: Mapping[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        number = int(args.get(key) or default)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _answer(text: str, *more: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text), *more], isError=False)


def _error(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


def _person(name: str, email: str, stamp: str) -> dict[str, str]:
    person = {"name": name, "email": email}
    when = datetime.fromtimestamp(int(stamp), UTC)
    return {**{k: v for k, v in person.items() if v}, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ")}


class LocalRepoSession:
    """Answers MCP tool calls from a git clone as github-mcp-server v1.14.0 would.

    Stands in for an MCP ``ClientSession``: only ``call_tool`` is used. Git runs in
    a worker thread, so concurrent branches do not block the event loop.
    """

    def __init__(
        self, clone: Path | str, commit: str, overlays: Mapping[str, str | None] | None = None
    ):
        self.clone = Path(clone)
        sha = (
            None
            if commit.startswith("-")
            else self._git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        )
        if not sha:
            raise ValueError(f"{commit!r} names no commit in {self.clone}")
        self.commit = sha.strip()
        self._resolved: dict[str, str | None] = {}
        self._blobs: dict[str, bytes] = {}  # overlay blobs, by sha
        self._overlaid = frozenset(overlays or ())
        entries = self._planted(self._read_tree(self.commit), overlays or {})
        self._trees: dict[str, _Tree] = {self.commit: _Tree(entries)}

    def _planted(self, tree: _Tree, overlays: Mapping[str, str | None]) -> list[_Entry]:
        """``tree``'s entries with the overlays applied, in git's order."""
        entries = dict(tree.by_path)
        for path, text in overlays.items():
            entry = entries.get(path)
            if not _is_file_path(path) or (
                entry is not None and (entry.kind != "blob" or entry.mode == _SYMLINK)
            ):
                raise ValueError(f"an overlay must name a file path at {self.commit}: {path!r}")
            if text is None:
                if entry is None:
                    raise ValueError(f"an overlay deletes a file that is not there: {path!r}")
                del entries[path]
                continue
            parent = path.rpartition("/")[0]
            while parent:
                above = entries.get(parent)
                if above is None:
                    made_up = hashlib.sha1(f"overlay tree {parent}".encode()).hexdigest()
                    entries[parent] = _Entry("040000", "tree", made_up, 0, parent)
                elif above.kind != "tree":
                    raise ValueError(f"an overlay puts a file inside a file: {path!r}")
                parent = parent.rpartition("/")[0]
            data = text.encode("utf-8")
            self._blobs[_blob_sha(data)] = data
            mode = entry.mode if entry is not None else "100644"
            entries[path] = _Entry(mode, "blob", _blob_sha(data), len(data), path)
        # git has no empty directories: drop those the deletions emptied, deepest first
        if any(text is None for text in overlays.values()):
            trees = [p for p, e in entries.items() if e.kind == "tree"]
            for path in sorted(trees, reverse=True):
                if not any(e.parent == path for e in entries.values()):
                    del entries[path]
        return sorted(entries.values(), key=_git_order)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        progress_callback: Any = None,
        **_: Any,
    ) -> CallToolResult:
        return await asyncio.to_thread(self._call, name, dict(arguments or {}))

    def _call(self, name: str, args: dict[str, Any]) -> CallToolResult:
        handlers = {
            "get_file_contents": self._get_file_contents,
            "list_commits": self._list_commits,
            "get_commit": self._get_commit,
            "search_code": self._search_code,
        }
        handler = handlers.get(name)
        return handler(args) if handler else _error(f"unknown tool: {name}")

    # --- git ---------------------------------------------------------------------

    def _argv(self, args: tuple[str, ...]) -> list[str]:
        config = ("-c", "log.follow=false", "-c", "log.showSignature=false")
        return ["git", "-C", str(self.clone), *config, *args]

    def _git(self, *args: str) -> str | None:
        """Git's output, or None when it failed."""
        done = subprocess.run(
            self._argv(args),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
        )
        return done.stdout if done.returncode == 0 else None

    def _blob(self, sha: str) -> bytes | None:
        if sha in self._blobs:
            return self._blobs[sha]
        # Bytes, not text: text mode turns CRLF into LF, and the file must come
        # back as GitHub serves it, byte for byte.
        done = subprocess.run(
            self._argv(("cat-file", "blob", sha)), check=False, capture_output=True, env=_git_env()
        )
        return done.stdout if done.returncode == 0 else None

    def _read_tree(self, commit: str) -> _Tree:
        out = self._git("ls-tree", "-r", "-t", "-l", "-z", "--full-tree", commit)
        if out is None:
            raise RuntimeError(f"git ls-tree failed for {commit} in {self.clone}")
        entries = []
        for record in out.split("\0"):
            if record:
                meta, _, path = record.partition("\t")
                mode, kind, sha, size = meta.split()
                entries.append(_Entry(mode, kind, sha, int(size) if size.isdigit() else 0, path))
        return _Tree(entries)

    def _tree_at(self, commit: str) -> _Tree:
        if commit not in self._trees:
            self._trees[commit] = self._read_tree(commit)
        return self._trees[commit]

    def _resolve(self, name: str) -> str | None:
        """The commit ``name`` names in the served repository, or None."""
        if name in _DEFAULT_REFS:
            return self.commit
        if not _HEX.fullmatch(name):
            return None  # no branch or tag but main exists, and nothing reaches git as an option
        key = name.lower()
        if key not in self._resolved:
            out = self._git("rev-parse", "--verify", "--quiet", f"{key}^{{commit}}")
            sha = out.strip() if out else None
            if sha != self.commit and not self._is_ancestor(sha):
                sha = None  # no such commit, or one after the served main: not here yet
            self._resolved[key] = sha
        return self._resolved[key]

    def _is_ancestor(self, sha: str | None) -> bool:
        return sha is not None and self._git("merge-base", "--is-ancestor", sha, self.commit) == ""

    def _commit(self, record: str, owner: str, repo: str) -> dict[str, Any]:
        sha, author, author_email, authored, committer, committer_email, committed, message = (
            record.split("\n", 7)
        )
        return {
            "sha": sha,
            "html_url": f"https://github.com/{owner}/{repo}/commit/{sha}",
            "commit": {
                "message": message.rstrip("\n"),
                "author": _person(author, author_email, authored),
                "committer": _person(committer, committer_email, committed),
            },
        }

    # --- the tools -------------------------------------------------------------------

    def _get_file_contents(self, args: Mapping[str, Any]) -> CallToolResult:
        owner, repo = _arg(args, "owner"), _arg(args, "repo")
        path = _arg(args, "path").removeprefix("/")
        if _climbs(path):
            return _error(_CLIMBS)
        sha, ref = _arg(args, "sha"), _arg(args, "ref")
        commit = self._resolve(sha or ref or DEFAULT_BRANCH)
        if commit is None:
            if sha:
                return _error(_BAD_TREE)
            return _error(f'failed to resolve git reference: could not resolve ref "{ref}"')
        at = sha or commit  # how the server's links name the commit
        tree = self._tree_at(commit)
        wanted = path.rstrip("/")
        if not wanted:
            return self._listing(tree.children.get("", []), owner, repo, at)
        entry = tree.by_path.get(wanted)
        if entry is None:
            return self._match_files(tree, path, sha, commit)
        if entry.kind == "tree":
            return self._listing(tree.children.get(wanted, []), owner, repo, at)
        if entry.kind == "blob" and entry.mode != _SYMLINK:
            return self._file(entry, owner, repo, at)
        return _error(_UNREADABLE)  # a symlink or a submodule: not served as text here

    def _listing(self, entries: list[_Entry], owner: str, repo: str, at: str) -> CallToolResult:
        api = f"https://api.github.com/repos/{owner}/{repo}"
        listing = []
        for e in entries:
            path = quote(e.path)
            common = {
                "name": e.name,
                "path": e.path,
                "sha": e.sha,
                "url": f"{api}/contents/{path}?ref={at}",
            }
            if e.kind == "tree":
                listing.append(
                    {
                        "type": "dir",
                        "size": 0,
                        **common,
                        "git_url": f"{api}/git/trees/{e.sha}",
                        "html_url": f"https://github.com/{owner}/{repo}/tree/{at}/{path}",
                    }
                )
            else:
                listing.append(
                    {
                        "type": "file",
                        "size": e.size,
                        **common,
                        "git_url": f"{api}/git/blobs/{e.sha}",
                        "html_url": f"https://github.com/{owner}/{repo}/blob/{at}/{path}",
                        "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{at}/{path}",
                    }
                )
        return _answer(go_json(listing))

    def _file(self, entry: _Entry, owner: str, repo: str, at: str) -> CallToolResult:
        data = self._blob(entry.sha)
        if data is None:
            return _error(_UNREADABLE)
        path = quote(entry.path)
        uri = f"repo://{owner}/{repo}/sha/{at}/contents/{path}"
        if not data:
            empty = TextResourceContents(uri=uri, mimeType="text/plain", text="")
            return _answer(
                f"successfully downloaded empty file (SHA: {entry.sha})",
                EmbeddedResource(type="resource", resource=empty),
            )
        if len(data) >= _MAX_CONTENT:
            download = f"https://raw.githubusercontent.com/{owner}/{repo}/{at}/{path}"
            link = ResourceLink(
                type="resource_link",
                uri=uri,
                name=entry.name,
                title=f"File: {entry.path}",
                size=len(data),
            )
            return _answer(
                f"File {entry.path} is too large to display ({len(data)} bytes). Use the download "
                f"URL to fetch the content: {download} (SHA: {entry.sha})",
                link,
            )
        if _is_binary(data):
            blob = BlobResourceContents(
                uri=uri, mimeType="application/octet-stream", blob=base64.b64encode(data).decode()
            )
            return _answer(
                f"successfully downloaded binary file (SHA: {entry.sha})",
                EmbeddedResource(type="resource", resource=blob),
            )
        text = TextResourceContents(
            uri=uri, mimeType="text/plain; charset=utf-8", text=data.decode("utf-8", "replace")
        )
        return _answer(
            f"successfully downloaded text file (SHA: {entry.sha})",
            EmbeddedResource(type="resource", resource=text),
        )

    def _match_files(self, tree: _Tree, path: str, sha: str, commit: str) -> CallToolResult:
        """The server's tree fallback (``matchFiles``): tree paths ending with ``path``."""
        dir_only = path.endswith("/")
        suffix = path[:-1] if dir_only else path
        matches: list[str] = []
        for entry in tree.entries:
            if len(matches) == _MAX_MATCHES:
                break
            if dir_only and entry.kind != "tree":
                continue
            if entry.path.endswith(suffix):
                matches.append(entry.path + "/" if entry.kind == "tree" else entry.path)
        if not matches:
            return _error(_NOT_FOUND)
        refs = (
            {"Ref": "", "SHA": sha}
            if sha
            else {"Ref": f"refs/heads/{DEFAULT_BRANCH}", "SHA": commit}
        )
        return _answer(
            f"Resolved potential matches in the repository tree (resolved refs: {go_json(refs)}, "
            f"matching files: {go_json(matches)})."
        )

    def _list_commits(self, args: Mapping[str, Any]) -> CallToolResult:
        owner, repo = _arg(args, "owner"), _arg(args, "repo")
        sha, path = _arg(args, "sha"), _arg(args, "path").strip("/")
        if _climbs(path):
            return _error(_CLIMBS)
        per_page = _number(args, "perPage", 30, 1, 100)
        page = _number(args, "page", 1, 1, 1_000_000)
        commit = self._resolve(sha or DEFAULT_BRANCH)
        if commit is None:
            query = {"page": page, "path": path, "per_page": per_page, "sha": sha}
            encoded = urlencode(sorted((k, v) for k, v in query.items() if v != ""))
            return _error(
                f"failed to list commits: {sha}: GET https://api.github.com/repos/{owner}/{repo}"
                f"/commits?{encoded}: 404 Not Found []"
            )
        planted = commit == self.commit and self._touches_overlay(path)
        skip = 0 if planted else (page - 1) * per_page
        out = self._git(
            "log",
            "-z",
            f"--format={_LOG_FORMAT}",
            f"--max-count={page * per_page if planted else per_page}",
            f"--skip={skip}",
            commit,
            "--",
            *([path] if path else []),
        )
        if out is None:
            return _error(f"failed to list commits: {sha}: git log failed")
        records = [r for r in out.split("\0") if r.strip()]
        if planted:  # the overlays' own commit first, once; then the page asked for
            head = self._git("log", "-1", "-z", f"--format={_LOG_FORMAT}", commit, "--")
            if head is None:
                return _error(f"failed to list commits: {sha}: git log failed")
            records = [head.rstrip("\0")] + [r for r in records if not r.startswith(commit)]
            records = records[(page - 1) * per_page : page * per_page]
        commits = [self._commit(r, owner, repo) for r in records]
        return _answer(go_json(commits))

    def _touches_overlay(self, path: str) -> bool:
        """``path`` is an overlay path or a directory above one."""
        return any(p == path or p.startswith(f"{path}/") for p in self._overlaid if path)

    def _get_commit(self, args: Mapping[str, Any]) -> CallToolResult:
        owner, repo, sha = _arg(args, "owner"), _arg(args, "repo"), _arg(args, "sha")
        if not sha:
            return _error("missing required parameter: sha")
        commit = self._resolve(sha)
        if commit is None:
            return _error(f"failed to get commit: {sha}: No commit found for SHA: {sha}")
        out = self._git("log", "-1", "-z", f"--format={_LOG_FORMAT}", commit, "--")
        if out is None:
            return _error(f"failed to get commit: {sha}: git log failed")
        return _answer(go_json(self._commit(out.rstrip("\0"), owner, repo)))

    def _search_code(self, args: Mapping[str, Any]) -> CallToolResult:
        if not _arg(args, "query").strip():
            return _error("missing required parameter: query")
        return _answer(_NO_HITS)


# --- the tools' schemas (a subset of the captured ones; tests/fixtures/mcp/tools_list.json)

_OWNER = {"type": "string", "description": "Repository owner"}
_REPO = {"type": "string", "description": "Repository name"}
_PAGE = {"type": "number", "description": "Page number for pagination (min 1)", "minimum": 1}
_PER_PAGE = {
    "type": "number",
    "description": "Results per page for pagination (min 1, max 100)",
    "minimum": 1,
    "maximum": 100,
}


def _tool(name: str, title: str, description: str, properties: dict, required: list[str]) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": properties, "required": required},
        annotations=ToolAnnotations(title=title, readOnlyHint=True),
    )


TOOLS = (
    _tool(
        "get_commit",
        "Get commit details",
        "Get details for a commit from a GitHub repository",
        {
            "owner": _OWNER,
            "repo": _REPO,
            "sha": {"type": "string", "description": "Commit SHA, branch name, or tag name"},
            "detail": {"type": "string", "enum": ["none", "stats", "full_patch"]},
        },
        ["owner", "repo", "sha"],
    ),
    _tool(
        "get_file_contents",
        "Get file or directory contents",
        "Get the contents of a file or directory from a GitHub repository",
        {
            "owner": _OWNER,
            "repo": _REPO,
            "path": {"type": "string", "description": "Path to file/directory", "default": "/"},
            "ref": {"type": "string", "description": "Accepts optional git refs"},
            "sha": {"type": "string", "description": "Accepts optional commit SHA"},
        },
        ["owner", "repo"],
    ),
    _tool(
        "list_commits",
        "List commits",
        "Get list of commits of a branch in a GitHub repository",
        {
            "owner": _OWNER,
            "repo": _REPO,
            "sha": {"type": "string", "description": "Commit SHA, branch or tag name"},
            "path": {"type": "string", "description": "Only commits containing this file path"},
            "page": _PAGE,
            "perPage": _PER_PAGE,
        },
        ["owner", "repo"],
    ),
    _tool(
        "search_code",
        "Search code",
        "Fast and precise code search across ALL GitHub repositories",
        {
            "query": {"type": "string", "description": "Search query"},
            "page": _PAGE,
            "perPage": _PER_PAGE,
        },
        ["query"],
    ),
)


def local_repo_tools(
    clone: Path | str, commit: str, *, overlays: Mapping[str, str | None] | None = None
) -> dict[str, list[BaseTool]]:
    """The agent-docs server's read tools, answered from ``clone`` with ``main`` at
    ``commit`` and ``overlays`` planted there (text to replace or add a file, None to
    delete one). Raises ValueError for a commit the clone does not have or an overlay
    that does not name a file path there (or deletes a file that is not there)."""
    session = LocalRepoSession(clone, commit, overlays)
    return {
        SERVER: [
            convert_mcp_tool_to_langchain_tool(
                session, tool, server_name=SERVER, handle_tool_errors=False  # type: ignore[arg-type]
            )
            for tool in TOOLS
        ]
    }
