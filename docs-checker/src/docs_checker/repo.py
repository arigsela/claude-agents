"""Reading the repository at one commit (C#18): files, directories, latest commits, search.

- Every read names the run's commit as ``sha``. github-mcp-server's ``ref`` is
  not used: a ``ref`` that does not exist silently reads the default branch,
  while ``sha`` skips ref resolution altogether. ``resolve_commit`` turns the
  run's ref into that commit once, at intake.
- Every result is typed, and only an unambiguous not-found at the commit is
  ``absent`` (Review Focus 1): the belt's status passes through unchanged, and
  anything that is not what was asked for (a directory read as a file, an answer
  that does not parse) is ``error``. A failed read never looks like a deleted file.
- Search answers ``None`` (unknown) unless the reader was built with
  ``search_allowed=True`` (C#17: GitHub searches the default branch only, so a
  reader at another commit must not search), and when GitHub answers with no
  items and ``incomplete_results`` (arigsela/kubernetes is not in its code-search
  index, Ruling S1): that is not proof that a value is absent.

Each call goes through ``ToolBelt.call``, so authorization, the gate, the
repository boundary, redaction and the replay memo all apply; a caller that
keeps tool events passes ``events=`` and gets each call's event appended.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from docs_checker.gate import render_intent
from docs_checker.prompts import AGENT_DESCRIPTION
from docs_checker.tools import ToolBelt, ToolEvent, ToolResult, normalize_source

ReadStatus = Literal["found", "absent", "denied", "transient", "error"]

# What each call is for, as the gate sees it, when the caller gives no intent.
DEFAULT_INTENT = render_intent(
    AGENT_DESCRIPTION, "Check the docs against the manifests they describe."
)

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
# The line before a file's text (github-mcp-server v1.14.0, repositories.go). An
# empty file says "empty"; binary, too-large and other answers are not a file's text.
_FILE_LINE = re.compile(
    r"successfully downloaded (?:text|empty) file \(SHA: (?P<sha>[0-9a-f]{40})\)"
)


@dataclass(frozen=True)
class ReadResult:
    """A file or a directory listing at the reader's commit.

    ``found``: ``text`` is the whole file (redacted by the belt, line count kept,
    so line N of the text is line N of the file) and ``sha`` its blob; or, for
    ``list_dir``, one path per line, directories ending in ``/``, and no sha.
    Any other status: ``text`` and ``sha`` are None.
    """

    path: str
    status: ReadStatus
    text: str | None
    sha: str | None

    @property
    def found(self) -> bool:
        return self.status == "found"


class RefError(Exception):
    """The run's ref names no commit the server could confirm (C#18).

    ``status`` is the belt's: ``absent`` when the server says there is no such
    commit; ``transient``, ``denied`` or ``error`` when it could not say.
    """

    def __init__(self, ref: str, status: str, detail: str = ""):
        self.ref = ref
        self.status = status
        self.detail = detail
        super().__init__(f"cannot resolve {ref!r} to a commit ({status}): {detail}".rstrip(": "))


def clean_path(path: str) -> str:
    """One spelling per path: no leading ``/`` or ``./``, no trailing ``/``."""
    return normalize_source(path).rstrip("/")


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _status(result: ToolResult) -> ReadStatus:
    return "found" if result.ok else result.status


async def _call(
    belt: ToolBelt,
    name: str,
    args: dict[str, Any],
    *,
    node: str,
    intent: str,
    memo: dict[str, Any] | None,
    events: list[ToolEvent] | None,
) -> ToolResult:
    result, event = await belt.call(name, args, node=node, intent=intent, memo=memo)
    if events is not None:
        events.append(event)
    return result


async def resolve_commit(
    belt: ToolBelt,
    ref: str,
    *,
    node: str = "intake",
    intent: str = DEFAULT_INTENT,
    memo: dict[str, Any] | None = None,
    events: list[ToolEvent] | None = None,
) -> str:
    """The 40-character sha that ``ref`` (``main``, a full or short sha) names now.

    Asks ``get_commit`` even for a full sha, so the run's commit is one the
    server confirmed. Raises ``RefError`` when it cannot.
    """
    wanted = ref.strip()
    if not wanted:
        raise RefError(ref, "error", "an empty ref names no commit")
    result = await _call(
        belt,
        "get_commit",
        {"sha": wanted, "detail": "none"},
        node=node,
        intent=intent,
        memo=memo,
        events=events,
    )
    if not result.ok:
        raise RefError(ref, result.status, result.text)
    commit = _json(result.text)
    sha = commit.get("sha") if isinstance(commit, Mapping) else None
    if not isinstance(sha, str) or not _FULL_SHA.fullmatch(sha.lower()):
        raise RefError(ref, "error", "the answer carries no commit sha")
    return sha.lower()


class RepoReader:
    """Reads the repository at one commit through the belt.

    ``commit`` must be a full lowercase sha (``resolve_commit``'s answer): a
    reader never resolves a ref itself, so every read of a run names the same
    commit. Each method's ``node`` is the node whose tools it uses (Ruling P4);
    callers at other nodes pass their own. ``memo`` is the run's replay memo, so a
    node re-run on resume does not read again.
    """

    def __init__(
        self,
        belt: ToolBelt,
        commit: str,
        *,
        search_allowed: bool = False,
        intent: str = DEFAULT_INTENT,
        memo: dict[str, Any] | None = None,
    ):
        if not _FULL_SHA.fullmatch(commit):
            raise ValueError(f"a reader needs a resolved 40-character sha, not {commit!r}")
        self.belt = belt
        self.commit = commit
        self.search_allowed = search_allowed
        self.intent = intent
        self.memo = memo

    async def _call(
        self, name: str, args: dict[str, Any], node: str, events: list[ToolEvent] | None
    ) -> ToolResult:
        return await _call(
            self.belt, name, args, node=node, intent=self.intent, memo=self.memo, events=events
        )

    async def read(
        self, path: str, *, node: str = "load", events: list[ToolEvent] | None = None
    ) -> ReadResult:
        """The file at ``path``, without the server's status line."""
        path = clean_path(path)
        result = await self._call(
            "get_file_contents", {"path": path, "sha": self.commit}, node, events
        )
        if not result.ok:
            return ReadResult(path, _status(result), None, None)
        first, _, rest = result.text.partition("\n")
        match = _FILE_LINE.fullmatch(first)
        if not match:  # a directory listing, a submodule, or something else that is not text
            return ReadResult(path, "error", None, None)
        return ReadResult(path, "found", rest, match["sha"])

    async def list_dir(
        self, path: str, *, node: str = "load", events: list[ToolEvent] | None = None
    ) -> ReadResult:
        """The entries of the directory at ``path`` (``""`` is the root), in git's order."""
        path = clean_path(path)
        result = await self._call(
            "get_file_contents", {"path": path, "sha": self.commit}, node, events
        )
        if not result.ok:
            return ReadResult(path, _status(result), None, None)
        entries = _json(result.text)
        if not isinstance(entries, list) or not all(
            isinstance(e, Mapping) and isinstance(e.get("path"), str) and e["path"] for e in entries
        ):  # a file, or not a listing
            return ReadResult(path, "error", None, None)
        lines = [e["path"].rstrip("/") + ("/" if e.get("type") == "dir" else "") for e in entries]
        return ReadResult(path, "found", "\n".join(lines), None)

    async def latest_commit(
        self, path: str, *, node: str = "scope", events: list[ToolEvent] | None = None
    ) -> str | None:
        """The last commit up to the reader's that touched ``path``; None if none
        did or the server could not say."""
        result = await self._call(
            "list_commits",
            {"sha": self.commit, "path": clean_path(path), "perPage": 1},
            node,
            events,
        )
        if not result.ok:
            return None
        commits = _json(result.text)
        if not isinstance(commits, list) or not commits or not isinstance(commits[0], Mapping):
            return None
        sha = commits[0].get("sha")
        return sha if isinstance(sha, str) and _FULL_SHA.fullmatch(sha) else None

    async def search(
        self, value: str, *, node: str = "locate", events: list[ToolEvent] | None = None
    ) -> list[str] | None:
        """Paths whose content has ``value`` (an exact phrase), or None for unknown.

        None without a call unless this reader may search; None when the value
        cannot be searched as one phrase, when the search fails, and when GitHub
        returns no items without saying the results are complete. ``[]`` only for
        a complete answer with no hits.
        """
        value = value.strip()
        if not self.search_allowed or not value or '"' in value or "\n" in value:
            return None
        result = await self._call("search_code", {"query": f'"{value}"'}, node, events)
        if not result.ok:
            return None
        answer = _json(result.text)
        items = answer.get("items") if isinstance(answer, Mapping) else None
        if not isinstance(items, list):
            return None
        if not items and answer.get("incomplete_results") is not False:
            return None
        paths: list[str] = []
        for item in items:
            path = item.get("path") if isinstance(item, Mapping) else None
            if isinstance(path, str) and path and path not in paths:
                paths.append(path)
        return paths
