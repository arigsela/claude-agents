"""Tool access: allowlist, per-node scoping, the drift gate, typed results, paced search.

- Read-only by construction (defense in depth with the AgentTemplate binding):
  only ``READ_ONLY_TOOLS`` can ever be called, whatever the MCP servers
  advertise. In kagent 1.0 a BYO runtime enforces binding tool filters itself;
  egress opens per origin, so a server's write tools are reachable unless the
  code refuses them. This allowlist is that refusal.
- Each node may call only its own tools (``NODE_TOOLS``). Lever 4
  (``tools_on_demand``) decides which schemas a model carries: on, the node's
  own; off, every read tool (bound with ``models.no_tools_choice()``). Sorted by
  name either way (lever 1: tool order is part of the cached prefix).
- Every call returns a ``ToolResult`` whose status comes from what
  github-mcp-server v1.14.0 actually answers (``tests/fixtures/mcp``). Only an
  unambiguous not-found is ``absent``: a doc line called "missing" on a failed
  read would be a false finding, so anything unclear is ``error`` or
  ``transient``.
- The caller gets the whole (redacted) text; ``model_text`` is the only place
  text is capped for a model (lever 7), on line boundaries.
- Searches are capped per run and paced (GitHub code search allows about ten
  requests a minute).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import httpx
from langchain_core.tools import ToolException

from docs_checker.config import Settings, load_settings
from docs_checker.gate import ToolCallContext, ToolGate, render_action
from docs_checker.levers import Levers
from docs_checker.redact import redact, redact_obj

ToolStatus = Literal["ok", "absent", "denied", "transient", "error"]

READ_ONLY_TOOLS = frozenset({"get_file_contents", "search_code", "list_commits", "get_commit"})

# The tools each node's code may call. intake resolves the run's ref to one commit.
NODE_TOOLS: dict[str, frozenset[str]] = {
    "intake": frozenset({"get_commit", "list_commits"}),
    "scope": frozenset({"get_file_contents", "list_commits", "get_commit"}),
    "load": frozenset({"get_file_contents", "list_commits"}),
    "locate": frozenset({"search_code"}),
}

# Tool text sent to a model, at most (lever 7).
MODEL_TEXT_CHARS = 8192

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """One tool call's outcome.

    ``text`` is the whole result, redacted (line counts kept), never capped: it is
    parsed by the caller, and ``model_text`` shrinks it for a model. ``raw_chars``
    is the size the server returned. ``status``: ``absent`` a confirmed not-found,
    ``denied`` refused (by this agent's policy, or a 401/403), ``transient`` a
    timeout, rate limit, 5xx or transport failure, ``error`` anything else.
    """

    text: str
    status: ToolStatus
    raw_chars: int

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class ToolEvent(TypedDict):
    """One gated tool call, kept for audit and emitted as A2A function_call parts."""

    name: str
    server: str  # the MCP server whose binding authorized it ("" when denied)
    args: dict
    decision: str  # allow | ask | ask-rejected | refuse | deny
    action: str  # the call rendered as one sentence (the drift check's input)
    result_chars: int
    status: str  # the ToolResult status
    ok: bool  # the tool ran and returned what was asked for
    evidence: list[str]  # sources this call read successfully (what a fact may cite)


# GitHub code search qualifiers that choose which repositories are searched,
# found anywhere in the query (after "(", a quote, or "-" too), with an optional
# negation.
_SCOPE_QUALIFIER = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<neg>-?)(?P<kind>repo|org|user|owner|enterprise)\s*:\s*(?P<value>[^\s()]*)"
)
# Boolean operators and grouping can attach terms outside the repo scope.
_SEARCH_OPERATORS = re.compile(r"(?<!\S)(?:OR|AND|NOT)(?!\S)|[()]")

# The run's search count and last search start, in the belt's run_state.
_SEARCH_COUNT = "search:count"
_SEARCH_LAST_START = "search:last_start"

# Tools whose owner/repo/path name a place in one repository.
_REPO_TOOLS = frozenset({"get_file_contents", "list_commits", "get_commit"})


# --- what the server's answers mean ----------------------------------------
#
# Grounded in the captured shapes (tests/fixtures/mcp) and github-mcp-server
# v1.14.0's source (pkg/errors/error.go, pkg/github/repositories*.go):
#
# - API errors read "<what failed>: <METHOD> <url>: <code> <message> [...]"
#   (go-github's ErrorResponse), or "...: unexpected status <code>: <body>".
# - Rate limits are rewritten as "GitHub API rate limit exceeded" or "GitHub
#   secondary rate limit exceeded"; go-github's own text is a 403 that says
#   "API rate limit exceeded" or "exceeded a secondary rate limit".
# - get_file_contents never reports a 404 for its path: any contents-API error
#   goes to a tree fallback, which either says the path is not in the commit's
#   tree (an error result) or, without error, lists up to three tree paths that
#   END with the path asked for. A 404 there is the tree's or the ref's.
# - A sha that names no commit is a 422 worded "No commit found for SHA".
_HTTP_STATUS = re.compile(
    r"\b(?:GET|HEAD|POST|PUT|PATCH|DELETE) \S+: (?P<code>[1-5]\d\d)\b"
    r"|\bunexpected status (?P<raw>[1-5]\d\d)\b"
)
_RATE_LIMITED = re.compile(
    r"(?i)rate limit exceeded|secondary rate limit|too many requests|abuse detection"
)
# Go's net/http and dial errors, and the MCP client's own timeout.
_TRANSPORT = re.compile(
    r"(?i)\btimed out\b|i/o timeout|deadline exceeded|Client\.Timeout|"
    r"connection (?:reset|refused|closed|aborted)|broken pipe|unexpected EOF|"
    r"temporarily unavailable|no such host|TLS handshake timeout"
)
_PATH_NOT_IN_TREE = (
    "The path does not point to a file or directory, or the file does not exist in the repository"
)
_NO_COMMIT = "No commit found for SHA"
_TREE_MATCHES = "Resolved potential matches in the repository tree"
_TREE_MATCH_LIMIT = 3  # github-mcp-server's maxMatchingFiles
_MATCHING_FILES = re.compile(r"matching files: (\[.*\])\)")
# A ref that does not exist read from the default branch instead (C#18: never).
_REF_FALLBACK = re.compile(r"Note: the provided ref '.*' does not exist, default branch")


def _status_code(text: str) -> int | None:
    match = _HTTP_STATUS.search(text)
    if not match:
        return None
    return int(match["code"] or match["raw"])


def _by_code(code: int) -> ToolStatus | None:
    if code in (401, 403):
        return "denied"
    if code in (408, 429) or code >= 500:
        return "transient"
    return None


def classify_failure(name: str, text: str) -> ToolStatus:
    """The status of a failure the server reported in words (an isError result)."""
    if _RATE_LIMITED.search(text):  # before the 403 check: a primary rate limit is a 403
        return "transient"
    code = _status_code(text)
    if code is not None:
        by_code = _by_code(code)
        if by_code:
            return by_code
        if code == 404 and name != "get_file_contents":
            return "absent"
        return "error"
    if name == "get_file_contents" and _PATH_NOT_IN_TREE in text:
        return "absent"
    if name in ("get_commit", "list_commits") and _NO_COMMIT in text:
        return "absent"
    if _TRANSPORT.search(text):
        return "transient"
    return "error"


def _classify_exception(name: str, error: BaseException) -> ToolStatus:
    """The status of a call that raised. Only the server's own words can say absent."""
    if isinstance(error, BaseExceptionGroup):
        found = {_classify_exception(name, e) for e in error.exceptions}
        for status in ("transient", "denied"):
            if status in found:
                return status
        return "error"
    if isinstance(error, TimeoutError | ConnectionError | httpx.TransportError):
        return "transient"
    if isinstance(error, httpx.HTTPStatusError):
        # The MCP endpoint's own status; a 404 means the endpoint, never the file.
        return _by_code(error.response.status_code) or "error"
    status = classify_failure(name, str(error))
    if isinstance(error, ToolException):  # an isError result, raised by the adapter
        return status
    return "error" if status == "absent" else status


def _classify_content(name: str, args: Mapping[str, Any], text: str) -> ToolStatus:
    """The status of a result the server did not mark as an error."""
    if name != "get_file_contents":
        return "ok"
    first = text.split("\n", 1)[0]
    if first.startswith(_TREE_MATCHES):
        return _tree_match_status(str(args.get("path") or ""), first)
    if _REF_FALLBACK.search(first):
        return "error"  # read at another commit than the one asked for
    if "is too large to display" in first or first.startswith("successfully downloaded binary"):
        return "error"  # no text came back
    return "ok"


def _tree_match_status(path: str, line: str) -> ToolStatus:
    """The tree fallback listed paths ending with ``path``: the contents API failed.

    If ``path`` itself is listed, it exists and the read failed for another
    reason (transient). If not, and fewer than the fallback's limit came back,
    the tree has no such path (absent). A full list that leaves it out proves
    nothing.
    """
    match = _MATCHING_FILES.search(line)
    try:
        matches = json.loads(match.group(1)) if match else None
    except ValueError:
        matches = None
    if not isinstance(matches, list):
        return "error"
    wanted = path.strip("/")
    if wanted in {str(m).strip("/") for m in matches}:
        return "transient"
    return "absent" if len(matches) < _TREE_MATCH_LIMIT else "error"


# --- text --------------------------------------------------------------------


def _block_texts(result: Any) -> list[str]:
    """The text of each block of a LangChain/MCP tool result (str, blocks, or a pair)."""
    if isinstance(result, tuple) and len(result) == 2:  # content_and_artifact
        result = result[0]
    if isinstance(result, str):
        return [result]
    if isinstance(result, list):
        texts = []
        for block in result:
            if isinstance(block, dict):
                texts.append(str(block.get("text", "")))
            else:
                texts.append(str(getattr(block, "text", block)))
        return [t for t in texts if t]
    content = getattr(result, "content", None)
    if content is not None:
        return _block_texts(content)
    return [str(result)]


def to_text(result: Any) -> str:
    """Normalise a LangChain/MCP tool result to one text, one block per line group."""
    return "\n".join(_block_texts(result))


_MARKER_ROOM = 96  # room kept for the omission marker


def model_text(result: ToolResult, levers: Levers, *, max_chars: int = MODEL_TEXT_CHARS) -> str:
    """Tool text as a model may see it: redacted, and with ``shrink_results`` on,
    at most ``max_chars``, cut between lines with a marker saying what was left out.

    The only place tool text is capped for a model. A single line longer than the
    cap is cut inside it (the marker says so). Redaction runs before the cut, so a
    cut cannot leave half a secret that no pattern matches.
    """
    text = redact(result.text)
    if not levers.shrink_results or len(text) <= max_chars:
        return text
    lines = text.split("\n")
    if lines[-1] == "":  # a final newline ends the last line; it is not another one
        lines.pop()
    budget = max_chars - _MARKER_ROOM
    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    if kept:
        head = "\n".join(kept)
        what = f"{len(lines) - len(kept)} more lines"
    else:  # one line longer than the cap
        head = lines[0][:budget]
        what = f"the rest of line 1 and {len(lines) - 1} more lines"
    return f"{head}\n[... {what} ({len(text) - len(head)} characters) omitted ...]"


# --- the repository boundary ---------------------------------------------------


def scope_args(name: str, args: Mapping[str, Any], repo: str) -> tuple[dict, str | None]:
    """Confine repository tools to ``repo`` (``owner/name``).

    Returns the arguments to call with, or an error. The model's owner/repo must
    name the configured repository (missing ones are filled in); paths may not
    climb out of it; a code search may not name another repo, org or user, and
    one without a ``repo:`` qualifier is scoped to the configured repository.
    Whatever the MCP credential could reach, the agent only reads this repo.
    """
    owner, _, repo_name = repo.partition("/")
    scoped = dict(args)
    if name in _REPO_TOOLS:
        for key, expected in (("owner", owner), ("repo", repo_name)):
            given = scoped.get(key)
            if given not in (None, "") and str(given).lower() != expected.lower():
                return scoped, f"error: only the {repo} repository can be read"
            scoped[key] = expected
        path = str(scoped.get("path") or "")
        parts = path.replace("\\", "/").split("/")
        if ".." in parts or "://" in path or path.startswith("~"):
            return scoped, "error: the path must stay inside the repository"
        return scoped, None
    if name == "search_code":
        query = str(scoped.get("query") or "")
        # Parse the whole expression: no boolean operators or grouping (they can
        # attach a term outside the scope), no negated scope, and no scope but
        # this repository. Docs checks search for literal values, so nothing
        # useful is lost.
        if _SEARCH_OPERATORS.search(query):
            return scoped, "error: searches may not use OR, AND, NOT or parentheses"
        qualifiers = list(_SCOPE_QUALIFIER.finditer(query))
        for q in qualifiers:
            if q["neg"] or q["kind"].lower() != "repo" or q["value"].lower() != repo.lower():
                return scoped, f"error: searches are limited to the {repo} repository"
        # Always carry exactly one scope qualifier, appended by the agent.
        bare = _SCOPE_QUALIFIER.sub(" ", query)
        scoped["query"] = " ".join([*bare.split(), f"repo:{repo}"])
        return scoped, None
    named = f"{scoped.get('owner', '')}/{scoped.get('repo', '')}"
    if ("owner" in scoped or "repo" in scoped) and named.lower() != repo.lower():
        # any other repository-shaped call
        return scoped, f"error: only the {repo} repository can be read"
    return scoped, None


class ToolBelt:
    """Every tool call goes through ``call``: authorize, gate, invoke, classify.

    Tools keep the identity of the server that advertised them. A tool is
    callable only when its name is on ``READ_ONLY_TOOLS`` *and* in the binding
    of that same server: a name bound on one server never authorizes a tool of
    the same name advertised by another. A name that two servers both bind and
    advertise is ambiguous and refused (fail closed), never resolved by order.

    The search count and the last search's start live in ``run_state``, a dict
    that outlives the belt: the executor passes the task's replay memo, so a
    belt rebuilt for a HITL resume continues the run's cap and pacing (no
    run_state: the belt's own, for one belt). Limits, the repository and the
    levers come from ``settings`` (code defaults when omitted); ``clock`` and
    ``sleep`` are seams for tests.
    """

    def __init__(
        self,
        tools_by_server: Mapping[str, Iterable[Any]],
        gate: ToolGate,
        *,
        bindings: Mapping[str, Iterable[str]],
        settings: Settings | None = None,
        run_state: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        offered: dict[str, list[tuple[str, Any]]] = {}
        for server, tools in tools_by_server.items():
            # A server the AgentTemplate does not bind contributes nothing.
            allowed = READ_ONLY_TOOLS & set(bindings.get(server, ()))
            for tool in tools:
                if tool.name in allowed:
                    offered.setdefault(tool.name, []).append((server, tool))
        self._tools: dict[str, tuple[str, Any]] = {}
        self.ambiguous: frozenset[str] = frozenset(
            name for name, entries in offered.items() if len(entries) > 1
        )
        for name, entries in offered.items():
            if len(entries) == 1:
                self._tools[name] = entries[0]
            else:
                logger.warning(
                    "tool %r is bound on several servers (%s); refusing it",
                    name,
                    ", ".join(sorted(server for server, _ in entries)),
                )
        self._gate = gate
        self._settings = settings or load_settings({})
        self._clock = clock
        self._sleep = sleep
        self._run = run_state if run_state is not None else {}
        self._search_lock = asyncio.Lock()

    def schemas_for(self, node: str) -> list[Any]:
        """The tools a node's model carries, sorted by name (lever 4).

        ``tools_on_demand`` on: the node's own tools (none for a node without
        any). Off: every read tool, for every node; the caller binds them with
        ``models.no_tools_choice()`` so they cannot be called.
        """
        if self._settings.levers.tools_on_demand:
            names = NODE_TOOLS.get(node, frozenset())
        else:
            names = READ_ONLY_TOOLS
        return [self._tools[n][1] for n in sorted(self._tools) if n in names]

    def server_of(self, name: str) -> str | None:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    async def call(
        self,
        name: str,
        args: Mapping[str, Any],
        *,
        node: str,
        intent: str,
        call_id: str | None = None,
        memo: dict[str, Any] | None = None,
    ) -> tuple[ToolResult, ToolEvent]:
        server = self.server_of(name) or ""
        # The arguments actually used: confined to the repository (see scope_args).
        args, scope_error = scope_args(name, args, self._settings.repo)
        action = render_action(name, args)
        call_id = call_id or stable_call_id(node, name, args)

        def event(decision: str, result: ToolResult) -> tuple[ToolResult, ToolEvent]:
            return result, ToolEvent(
                name=name,
                server=server,
                args=redact_obj(dict(args)),
                decision=decision,
                action=redact(action),
                result_chars=len(result.text),
                status=result.status,
                ok=result.ok,
                # Only a successful read is evidence a fact may cite.
                evidence=evidence_for(name, args) if result.ok else [],
            )

        def denied(decision: str, text: str) -> tuple[ToolResult, ToolEvent]:
            return event(decision, ToolResult(text=text, status="denied", raw_chars=0))

        # 1. Authorization: allowlisted, bound on the server that offers it,
        #    unambiguous, in this node's scope, and inside the repository.
        if name not in self._tools or name not in NODE_TOOLS.get(node, ()):
            return denied("deny", f"error: tool {name!r} is not available to this node")
        if scope_error:
            return denied("deny", scope_error)

        # 2. Drift check, after auth.
        verdict = await self._gate.check(
            ToolCallContext(intent=intent, action=action, tool=name, args=args, workflow=node)
        )
        if verdict.decision == "refuse":
            return denied(
                "refuse", f"error: refused, the call strays from the task ({verdict.reason})"
            )
        if verdict.decision == "ask":
            # Pauses the graph; the A2A executor turns this into input-required with
            # a kagent HITL tool_approval_request and resumes with the decision.
            from langgraph.types import interrupt

            reply = interrupt(
                {
                    "action_requests": [
                        {"name": name, "id": call_id, "call_id": call_id, "args": dict(args)}
                    ],
                    "hint": f"{action} ({verdict.reason})",
                }
            )
            if not _approved(reply, call_id):
                return denied("ask-rejected", "error: a human rejected this call")

        # A resume re-runs the node: a call that already ran (same id, so the same
        # tool and arguments) returns its recorded result instead of running
        # again, without counting or waiting as a search. This comes after the gate
        # on purpose: an "ask" must still reach interrupt() in order, so each
        # resume value meets the pause it answers.
        memo_key = f"tool:{call_id}"
        if memo is not None and memo_key in memo:
            return memo[memo_key]

        if name == "search_code":
            # One search at a time, each at least search_interval_s after the last
            # one started, at most max_searches per run (C#20).
            async with self._search_lock:
                limit = self._settings.max_searches
                if self._run.get(_SEARCH_COUNT, 0) >= limit:
                    outcome = denied("deny", f"error: this run's {limit} searches are used up")
                else:
                    await self._pace_search()
                    outcome = event(verdict.decision, await self._invoke(name, args, call_id))
        else:
            outcome = event(verdict.decision, await self._invoke(name, args, call_id))
        if memo is not None:
            memo[memo_key] = outcome
        return outcome

    async def _pace_search(self) -> None:
        """Wait until ``search_interval_s`` after the run's last search started; count
        this one.

        The start is monotonic time. A run restored in another process carries a
        start from another clock, so the wait is clamped to one interval: never
        longer than that, possibly shorter if that clock was behind.
        """
        last = self._run.get(_SEARCH_LAST_START)
        interval = self._settings.search_interval_s
        if last is not None:
            wait = min(last + interval - self._clock(), interval)
            if wait > 0:
                await self._sleep(wait)
        self._run[_SEARCH_COUNT] = self._run.get(_SEARCH_COUNT, 0) + 1
        self._run[_SEARCH_LAST_START] = self._clock()

    async def _invoke(self, name: str, args: Mapping[str, Any], call_id: str) -> ToolResult:
        # 3. Invoke as a tool call, so an MCP error result (isError) comes back as a
        #    ToolMessage with status "error" or as a ToolException, never as
        #    evidence. The whole text goes back, redacted block by block (a file
        #    is parsed as itself, not with the server's status line before it).
        timeout = self._settings.tool_timeout_s
        call = {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}
        try:
            raw = await asyncio.wait_for(self._tools[name][1].ainvoke(call), timeout)
        except TimeoutError:
            return ToolResult(f"error: the tool timed out after {timeout:g} s", "transient", 0)
        except Exception as error:  # noqa: BLE001 - a failed tool is a result for the caller
            message = str(error)
            return ToolResult(
                text=redact(f"error: {type(error).__name__}: {message}")[:500],
                status=_classify_exception(name, error),
                raw_chars=len(message),
            )
        blocks = _block_texts(raw)
        raw_text = "\n".join(blocks)
        text = "\n".join(redact(block) for block in blocks)
        if getattr(raw, "status", "success") == "error":
            return ToolResult(
                text=f"error: the tool failed: {text}",
                status=classify_failure(name, raw_text),
                raw_chars=len(raw_text),
            )
        return ToolResult(text, _classify_content(name, args, raw_text), len(raw_text))


def normalize_source(source: str) -> str:
    """One spelling per repo path: no leading ``/`` or ``./``."""
    source = str(source).strip().lstrip("/")
    while source.startswith("./"):
        source = source[2:]
    return source


def evidence_for(name: str, args: Mapping[str, Any]) -> list[str]:
    """The sources a successful call actually read, in the form facts cite them.

    ``search_code`` only locates files and the commit tools only date them; none
    is evidence for what a file says, so a fact must come from a read.
    """
    if name == "get_file_contents":
        path = normalize_source(args.get("path") or "")
        return [path] if path else []
    return []


def evidence_of(events: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every source read successfully by the given tool events."""
    return {source for e in events if e.get("ok") for source in e.get("evidence") or ()}


def stable_call_id(node: str, name: str, args: Mapping[str, Any]) -> str:
    """A call id that survives LangGraph re-running the node on resume."""
    key = json.dumps([node, name, dict(args)], sort_keys=True, default=str)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _approved(reply: Any, call_id: str) -> bool:
    """Read a kagent HITL tool_approval_response for this one pending call.

    Strict, like kagent-core's ``require_tool_approval_response``: the reply must
    be a tool_approval_response, carry exactly one decision whose id is this
    call's id, and that decision must be the boolean ``True``. A decision for
    another id never approves this call (on resume LangGraph re-runs the node, so
    the model may now propose a different call than the one a human approved),
    and ``"false"``, ``1`` or a missing value are not approvals.
    """
    if not isinstance(reply, Mapping) or reply.get("type") != "tool_approval_response":
        return False
    approvals = reply.get("approvals")
    if not isinstance(approvals, list) or not approvals:
        return False
    if not all(isinstance(a, Mapping) for a in approvals):
        return False
    ids = [a.get("id") for a in approvals]
    if ids != [call_id]:  # unknown, missing or duplicate ids
        return False
    return approvals[0].get("approved") is True
