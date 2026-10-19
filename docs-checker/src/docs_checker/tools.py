"""Tool access: allowlist, per-specialist scoping, the drift gate, result shrinking.

- Read-only by construction (defense in depth with the AgentTemplate binding):
  only ``READ_ONLY_TOOLS`` can ever be called, whatever the MCP servers
  advertise. In kagent 1.0 a BYO runtime enforces binding tool filters itself;
  egress opens per origin, so a server's write tools are reachable unless the
  code refuses them. This allowlist is that refusal.
- Lever 4: each specialist binds only its own tools, sorted by name (sorted
  for lever 1: tool order is part of the cached prefix).
- Lever 7: results are projected to the fields that answer questions and
  capped, before any model sees them.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypedDict

from docs_checker.gate import ToolCallContext, ToolGate, render_action
from docs_checker.redact import redact, redact_obj

Specialist = Literal["docs", "catalog"]


class ToolEvent(TypedDict):
    """One gated tool call, kept for audit and emitted as A2A function_call parts."""

    name: str
    server: str  # the MCP server whose binding authorized it ("" when denied)
    args: dict
    decision: str  # allow | ask | ask-rejected | refuse | deny
    action: str  # the call rendered as one sentence (the drift check's input)
    result_chars: int
    ok: bool  # the tool ran and returned without an error
    evidence: list[str]  # sources this call read successfully (what a fact may cite)


SPECIALIST_TOOLS: dict[str, frozenset[str]] = {
    "docs": frozenset({"get_file_contents", "search_code"}),
    "catalog": frozenset({"get-catalog-entity"}),
}
READ_ONLY_TOOLS = frozenset().union(*SPECIALIST_TOOLS.values())

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULT_CHARS = 4000
DEFAULT_REPO = "arigsela/kubernetes"

# GitHub code search qualifiers that choose which repositories are searched,
# found anywhere in the query (after "(", a quote, or "-" too), with an optional
# negation.
_SCOPE_QUALIFIER = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?P<neg>-?)(?P<kind>repo|org|user|owner|enterprise)\s*:\s*(?P<value>[^\s()]*)"
)
# Boolean operators and grouping can attach terms outside the repo scope.
_SEARCH_OPERATORS = re.compile(r"(?<!\S)(?:OR|AND|NOT)(?!\S)|[()]")

_CATALOG_FIELDS = (
    ("kind", ("kind",)),
    ("name", ("metadata", "name")),
    ("namespace", ("metadata", "namespace")),
    ("description", ("metadata", "description")),
    ("owner", ("spec", "owner")),
    ("system", ("spec", "system")),
    ("lifecycle", ("spec", "lifecycle")),
    ("type", ("spec", "type")),
    ("dependsOn", ("spec", "dependsOn")),
)


def _dig(data: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def project_catalog_entity(text: str) -> str:
    """Keep the handful of entity fields questions are about; drop the rest."""
    try:
        entity = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(entity, dict):
        return text
    projected = {name: _dig(entity, path) for name, path in _CATALOG_FIELDS}
    return json.dumps({k: v for k, v in projected.items() if v not in (None, [], "")})


def cap(text: str, max_chars: int = DEFAULT_MAX_RESULT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars * 3 // 4
    tail = max_chars - head
    return f"{text[:head]}\n...[{len(text) - max_chars} chars omitted]...\n{text[-tail:]}"


def to_text(result: Any) -> str:
    """Normalise a LangChain/MCP tool result (str, content blocks, or a pair)."""
    if isinstance(result, tuple) and len(result) == 2:  # content_and_artifact
        result = result[0]
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(getattr(block, "text", block)))
        return "\n".join(p for p in parts if p)
    content = getattr(result, "content", None)
    if content is not None:
        return to_text(content)
    return str(result)


def shrink(tool: str, text: str, max_chars: int = DEFAULT_MAX_RESULT_CHARS) -> str:
    """Project, redact, then cap (redact before the cap, so a cut cannot leave half
    a secret that no pattern matches)."""
    if tool == "get-catalog-entity":
        text = project_catalog_entity(text)
    return cap(redact(text), max_chars)


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
    if name == "get_file_contents":
        for key, expected in (("owner", owner), ("repo", repo_name)):
            given = scoped.get(key)
            if given in (None, ""):
                scoped[key] = expected
            elif str(given).lower() != expected.lower():
                return scoped, f"error: only the {repo} repository can be read"
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
    """Every tool call goes through ``call``: authorize, gate, invoke, shrink.

    Tools keep the identity of the server that advertised them. A tool is
    callable only when its name is on ``READ_ONLY_TOOLS`` *and* in the binding
    of that same server: a name bound on one server never authorizes a tool of
    the same name advertised by another. A name that two servers both bind and
    advertise is ambiguous and refused (fail closed), never resolved by order.
    """

    def __init__(
        self,
        tools_by_server: Mapping[str, Iterable[Any]],
        gate: ToolGate,
        *,
        bindings: Mapping[str, Iterable[str]],
        repo: str = DEFAULT_REPO,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
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
        self._repo = repo
        self._max = max_result_chars

    def tools_for(self, specialist: Specialist) -> list[Any]:
        scope = SPECIALIST_TOOLS[specialist]
        return [self._tools[n][1] for n in sorted(self._tools) if n in scope]

    def server_of(self, name: str) -> str | None:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    async def call(
        self,
        name: str,
        args: Mapping[str, Any],
        *,
        specialist: Specialist,
        intent: str,
        workflow: str,
        call_id: str | None = None,
        memo: dict[str, Any] | None = None,
    ) -> tuple[str, ToolEvent]:
        server = self.server_of(name) or ""
        # The arguments actually used: confined to the repository (see scope_args).
        args, scope_error = scope_args(name, args, self._repo)
        action = render_action(name, args)
        call_id = call_id or stable_call_id(specialist, name, args)

        def event(decision: str, text: str, *, ok: bool = False) -> tuple[str, ToolEvent]:
            return text, ToolEvent(
                name=name,
                server=server,
                args=redact_obj(dict(args)),
                decision=decision,
                action=redact(action),
                result_chars=len(text),
                ok=ok,
                # Only a successful read is evidence a fact may cite.
                evidence=evidence_for(name, args) if ok else [],
            )

        # 1. Authorization: allowlisted, bound on the server that offers it,
        #    unambiguous, in this specialist's scope, and inside the repository.
        if name not in self._tools or name not in SPECIALIST_TOOLS[specialist]:
            return event("deny", f"error: tool {name!r} is not available to this agent")
        if scope_error:
            return event("deny", scope_error)

        # 2. Drift check, after auth.
        verdict = await self._gate.check(
            ToolCallContext(intent=intent, action=action, tool=name, args=args, workflow=workflow)
        )
        if verdict.decision == "refuse":
            return event(
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
                return event("ask-rejected", "error: a human rejected this call")

        # A resume re-runs the node: a call that already ran (same id, so the same
        # tool and arguments) returns its recorded result instead of running
        # again. This comes after the gate on purpose: an "ask" must still reach
        # interrupt() in order, so each resume value meets the pause it answers.
        memo_key = f"tool:{call_id}"
        if memo is not None and memo_key in memo:
            return memo[memo_key]

        result = await self._invoke(name, args, call_id, verdict.decision, event)
        if memo is not None:
            memo[memo_key] = result
        return result

    async def _invoke(self, name, args, call_id, decision, event) -> tuple[str, ToolEvent]:
        # 3. Invoke and shrink (lever 7). Invoked as a tool call so the result is a
        #    ToolMessage whose status says whether the tool failed: an MCP error
        #    result (isError) can come back as ordinary content, never as evidence.
        try:
            raw = await self._tools[name][1].ainvoke(
                {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}
            )
        except Exception as error:  # noqa: BLE001 - a failed tool is a result for the model
            return event(decision, redact(f"error: {type(error).__name__}: {error}")[:500])
        text = shrink(name, to_text(raw), self._max)
        if getattr(raw, "status", "success") == "error":
            return event(decision, f"error: the tool failed: {text}"[: self._max])
        return event(decision, text, ok=True)


def normalize_source(source: str) -> str:
    """One spelling per source: repo paths without a leading ``/`` or ``./``,
    catalog refs (``kind:namespace/name``) lower-cased."""
    source = str(source).strip().lstrip("/")
    while source.startswith("./"):
        source = source[2:]
    if ":" in source.split("/", 1)[0]:
        source = source.lower()
    return source


def evidence_for(name: str, args: Mapping[str, Any]) -> list[str]:
    """The sources a successful call actually read, in the form facts cite them.

    ``search_code`` only locates files; it is not evidence for what a file says,
    so a fact must come from a read (``get_file_contents``) or an entity fetch.
    """
    if name == "get_file_contents":
        path = normalize_source(args.get("path") or "")
        return [path] if path else []
    if name == "get-catalog-entity":
        ref = args.get("entityRef") or args.get("ref")
        if ref:
            return [normalize_source(ref)]
        kind, entity = args.get("kind"), args.get("name")
        if not kind or not entity:
            return []
        namespace = args.get("namespace") or "default"
        return [normalize_source(f"{kind}:{namespace}/{entity}")]
    return []


def evidence_of(events: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every source read successfully by the given tool events."""
    return {source for e in events if e.get("ok") for source in e.get("evidence") or ()}


def stable_call_id(specialist: str, name: str, args: Mapping[str, Any]) -> str:
    """A call id that survives LangGraph re-running the node on resume."""
    key = json.dumps([specialist, name, dict(args)], sort_keys=True, default=str)
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
