"""Two gates: the drift seam before every tool call, and the fix gate before a fix
reaches a person. No LLM sits in either path.

Tool calls (``ToolGate``). Order at each call (``tools.ToolBelt.call``):
authorization first (the tool is on this agent's allowlist and bound in its
AgentTemplate), then this gate, then the tool. The gate compares the *intent* (the
agent card's description plus the original task, never the latest hop) with the
*action* (the tool call rendered as one sentence) as the angle between two
embeddings, and answers allow, ask or refuse by per-workflow thresholds. Until the
drift phase ships, ``RecordingGate`` allows everything and keeps the rendered
sentences, which become the calibration set. ``AngleGate`` is the real check; it
needs an ``Embedder`` (see the design doc for the embedding-source decision).

Fixes (``FixGate``, spec section 7). A proposed fix is model output steered by doc
and manifest text that anyone who can edit the repository writes, so it is
untrusted, and this gate is the last check before it reaches the report or a
person. Two layers:

1. Rules, deterministic, always on (``FixGate`` without an embedder, which is what
   production runs: ``build_fix_gate``). The trusted fields, the claim's range and
   the doc's lines, come from the claim and the doc, never from the finding the
   model filled in. Then the replacement rule (``prompts.validate_replacement``),
   ruling G1 for names, and the render check (rulings G2(b) and G4): the doc is
   rendered before and after the fix as GitHub would, and a fix that makes any
   link or image live that was not live before is refused. Per-line rules cannot
   see block context outside the claim's lines (a fence, an HTML block or a
   comment above); the render check is the authority on markdown semantics.
2. Angle (offline only, plan R2): with an embedder, the angle between the intent
   and the rendered fix may add an ask or a refusal, never allow what the rules
   refused.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Literal, Protocol

from linkify_it import LinkifyIt
from markdown_it import MarkdownIt

from docs_checker.prompts import is_word, occurs_whole, replacement_tokens, validate_replacement

if TYPE_CHECKING:
    from docs_checker.config import Settings
    from docs_checker.state import Claim, Finding

logger = logging.getLogger(__name__)

Decision = Literal["allow", "ask", "refuse"]


@dataclass(frozen=True)
class ToolCallContext:
    intent: str
    action: str
    tool: str
    args: Mapping[str, object]
    workflow: str


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    angle_deg: float | None = None
    reason: str = ""


class ToolGate(Protocol):
    async def check(self, call: ToolCallContext) -> GateResult: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def render_intent(card_description: str, question: str) -> str:
    return f"{card_description.strip()} Task: {question.strip()}"


_ACTION_TEMPLATES = {
    "get_file_contents": "Read the file {path} from the {owner}/{repo} repository.",
    "search_code": "Search code for '{query}'.",
    "get-catalog-entity": "Look up the catalog entity {kind}:{namespace}/{name}.",
}


def render_action(tool: str, args: Mapping[str, object]) -> str:
    """The tool call as one deterministic sentence (sorted, no free text added)."""
    template = _ACTION_TEMPLATES.get(tool)
    if template:
        try:
            return template.format(**{k: v for k, v in args.items()})
        except (KeyError, IndexError):
            pass
    rendered = ", ".join(f"{k}={args[k]!r}" for k in sorted(args))
    return f"Call the tool {tool} with {rendered}." if rendered else f"Call the tool {tool}."


def angle_degrees(a: Sequence[float], b: Sequence[float]) -> float:
    """cos theta = (A.I) / (|A| |I|), returned as degrees in [0, 180]."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / norm))))


@dataclass(frozen=True)
class Thresholds:
    """Angles in degrees: below ``ask_at`` allow, from ``refuse_at`` refuse, between ask."""

    ask_at: float
    refuse_at: float

    def __post_init__(self) -> None:
        _check_order(self)

    def decide(self, angle: float) -> Decision:
        if angle >= self.refuse_at:
            return "refuse"
        if angle >= self.ask_at:
            return "ask"
        return "allow"


def _check_order(thresholds: Any) -> None:
    """``ask_at`` strictly below ``refuse_at`` (C#49); NaN fails too."""
    if not thresholds.ask_at < thresholds.refuse_at:
        raise ValueError(
            f"thresholds need ask_at < refuse_at, got ask_at={thresholds.ask_at!r}, "
            f"refuse_at={thresholds.refuse_at!r}"
        )


@dataclass
class RecordingGate:
    """Allow everything; keep (workflow, intent, action) for threshold calibration."""

    seen: list[ToolCallContext] = field(default_factory=list)

    async def check(self, call: ToolCallContext) -> GateResult:
        self.seen.append(call)
        return GateResult(decision="allow", reason="drift check not enabled")


class AngleGate:
    def __init__(
        self,
        embedder: Embedder,
        thresholds: Mapping[str, Thresholds],
        default: Thresholds,
    ):
        self._embedder = embedder
        self._thresholds = dict(thresholds)
        self._default = default

    async def check(self, call: ToolCallContext) -> GateResult:
        intent_vec, action_vec = await self._embedder.embed([call.intent, call.action])
        angle = angle_degrees(intent_vec, action_vec)
        thresholds = self._thresholds.get(call.workflow, self._default)
        decision = thresholds.decide(angle)
        return GateResult(
            decision=decision,
            angle_deg=round(angle, 2),
            reason=f"{angle:.1f} deg vs ask {thresholds.ask_at} / refuse {thresholds.refuse_at}",
        )


# --- the fix gate --------------------------------------------------------------------


@dataclass(frozen=True)
class FixAction:
    """A proposed fix and what it is checked against (C#9).

    ``claim`` and ``doc_lines`` (the whole doc at the run's commit, line 1 first) are
    trusted: the gate takes the range and the old lines from them, never from the
    finding the model filled in.
    """

    finding: Finding
    claim: Claim
    doc_lines: list[str]


def render_fix(action: FixAction) -> str:
    """The fix as one deterministic sentence (the action the angle layer embeds)."""
    finding = action.finding
    return (
        f"In {finding.doc}, replace lines {finding.line_start}-{finding.line_end} "
        f"{json.dumps(finding.old_text)} with {json.dumps(finding.replacement)}."
    )


def apply_fix(
    doc_lines: Sequence[str], line_start: int, line_end: int, replacement: str
) -> list[str]:
    """The doc's lines with ``line_start..line_end`` (1-based, inclusive) replaced by
    the replacement's lines."""
    return [*doc_lines[: line_start - 1], *replacement.split("\n"), *doc_lines[line_end:]]


# The render check is pure Python over attacker-written text, and linkify-it validates
# every link candidate against the rest of its text token: a line of thousands of
# candidates costs time quadratic in its length. Text tokens never cross a line break,
# so capping the line bounds the cost: at worst about 2 s per render of a 256 KiB doc,
# and a check renders the fixed doc twice (the original's renders are cached). A doc
# beyond either cap gets no fix (fail closed).
MAX_RENDER_LINE_CHARS = 4096
MAX_RENDER_CHARS = 1 << 20  # four times the largest doc discovery reads (256 KiB)

# A www. link: a domain character, then everything up to a space or "<" (possessive,
# so a validation never backtracks), less trailing punctuation as GitHub drops it.
_WWW_TAIL = re.compile(r"[A-Za-z0-9_-][^\s<]*+")
_URL_TRAILING = "?!.,:*_~'\""

# Attributes whose value is a URL that a browser follows or loads.
_URL_ATTRS = frozenset(
    {
        "href", "src", "srcset", "imagesrcset", "poster", "cite", "action", "formaction",
        "background", "longdesc", "lowsrc", "dynsrc", "data", "manifest", "icon",
        "codebase", "archive", "usemap", "ping", "profile", "classid",
    }
)  # fmt: skip
_SRCSETS = frozenset({"srcset", "imagesrcset"})


class _GitHubLinkify(LinkifyIt):
    """linkify-it set up like GitHub's autolinks: ``scheme://`` links and ``www.``
    links on any domain (linkify-it's own ``www.`` handling knows only a list of
    top-level domains, so ``www.evil.dev`` would stay text), never a bare domain
    (GitHub leaves ``ghcr.io/x`` and ``grafana.example.com`` as text)."""

    def __init__(self) -> None:
        super().__init__(options={"fuzzy_link": False})
        # A bound method, not a plain function: linkify-it installs a plain function
        # validator on its class, shared by every instance.
        self.add("www.", {"validate": self._validate_www})

    def _validate_www(self, text: str, pos: int) -> int:
        match = _WWW_TAIL.match(text, pos)
        if match is None:
            return 0
        end = match.end()
        while end > pos and text[end - 1] in _URL_TRAILING:
            end -= 1
        return end - pos

    def normalize(self, match: Any) -> None:
        super().normalize(match)
        if match.schema.lower() == "www.":
            match.url = "http://" + match.url


def _any_link(url: str) -> bool:
    """Every link target counts, ``javascript:`` too: a renderer may follow what
    markdown-it would drop."""
    return True


@lru_cache(maxsize=1)
def _markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"linkify": True}).enable("linkify")
    md.linkify = _GitHubLinkify()
    md.validateLink = _any_link
    return md


class _HtmlUrls(HTMLParser):
    """The URL attributes of one raw HTML token (entities decoded, comments skipped)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in _SRCSETS:
                self.urls += [c.split()[0] for c in value.split(",") if c.strip()]
            elif name in _URL_ATTRS or name.endswith(":href"):
                self.urls.append(value.strip())


def _collect(tokens: Sequence[Any], urls: list[str]) -> None:
    for token in tokens:
        if token.type in ("link_open", "image"):
            target = token.attrGet("href" if token.type == "link_open" else "src")
            if target is not None:
                urls.append(str(target))
        elif token.type in ("html_block", "html_inline"):
            # One parser per token: an unclosed <script> or comment in one token
            # cannot hide the next one.
            parser = _HtmlUrls()
            parser.feed(token.content)
            parser.close()
            urls += parser.urls
        if token.children:
            _collect(token.children, urls)


@lru_cache(maxsize=16)  # each check of a doc renders the same original again
def _url_counts(text: str) -> tuple[tuple[str, int], ...]:
    urls: list[str] = []
    _collect(_markdown().parse(text), urls)
    return tuple(Counter(urls).items())


def rendered_urls(text: str) -> Counter[str]:
    """Every URL the rendered ``text`` links to or loads, with how often: links and
    images (inline, reference-resolved, autolinks and GitHub-style bare links) and the
    URL attributes of raw HTML. Code, comments and other inert text give none.

    CommonMark (markdown-it-py) with GitHub-style linkify. Known gap: a bare email
    on a top-level domain outside linkify-it's list stays text (low risk: mailto)."""
    return Counter(dict(_url_counts(text)))


def _front_matter_lines(lines: Sequence[str]) -> int:
    """How many lines the front matter takes, both fences included; 0 for none."""
    if not lines or lines[0].lstrip("\ufeff").rstrip("\r") != "---":
        return 0
    for number, line in enumerate(lines[1:], start=2):
        if line.rstrip("\r") == "---":
            return number
    return 0


def _views(lines: Sequence[str]) -> tuple[str, str]:
    """The doc as plain CommonMark reads it, and as GitHub shows it: the body alone,
    the front matter's lines left blank. Front matter can open a fence or an HTML
    block that would hide the whole body from the first view."""
    head = _front_matter_lines(lines)
    return "\n".join(lines), "\n".join([""] * head + list(lines[head:]))


def added_urls(original: Sequence[str], patched: Sequence[str]) -> set[str]:
    """The URLs the patched doc renders more often than the original, in either view
    (rulings G2(b) and G4). Counts, not a set: a link the original already has must
    not let a fix make a second one live."""
    added: set[str] = set()
    for before, after in zip(_views(original), _views(patched), strict=True):
        added |= set(rendered_urls(after) - rendered_urls(before))
    return added


# Kinds whose words are names: a plain word may change only to one the evidence has.
NAMED_KINDS = frozenset({"image", "host", "namespace", "name"})


def _ungrounded_word(old: str, new: str, evidence: str) -> bool:
    """Ruling G1: ``new`` has a plain word that is neither in ``old`` nor, whole, in
    the evidence's code (``redis`` -> ``evilredis``)."""
    return any(
        is_word(token) and not occurs_whole(token, old) and not occurs_whole(token, evidence)
        for token in replacement_tokens(new)
    )


def _refusal(action: FixAction) -> str | None:
    """Why the rules refuse ``action``, or None when it passes every one."""
    # Not at module level: evidence -> state -> tools -> gate would make a cycle.
    from docs_checker.evidence import code_only

    finding, claim, lines = action.finding, action.claim, action.doc_lines
    if finding.doc != claim.doc:
        return "the fix is for another doc than its claim"
    if finding.claim != claim:
        return "the fix carries another claim"
    if (finding.line_start, finding.line_end) != (claim.line_start, claim.line_end):
        return "the fix changes other lines than its claim's"
    if not 1 <= claim.line_start <= claim.line_end <= len(lines):
        return "the claim's lines are not in the doc"
    old = "\n".join(lines[claim.line_start - 1 : claim.line_end])
    if finding.old_text != old:
        return "the fix's old text is not the doc's lines"
    # Comments are never evidence (validate_replacement strips them too).
    evidence = code_only(finding.evidence.text) if finding.evidence else ""
    if validate_replacement(old, finding.replacement, evidence) != finding.replacement:
        return "the replacement fails the replacement rule"
    if finding.verdict == "stale" and finding.replacement == old:
        return "the fix of a stale claim changes nothing"
    if claim.kind in NAMED_KINDS and _ungrounded_word(old, finding.replacement, evidence):
        return f"a new word in a {claim.kind} claim is not in the evidence"
    patched = apply_fix(lines, claim.line_start, claim.line_end, finding.replacement)
    if any(len(line) > MAX_RENDER_LINE_CHARS for line in (*lines, *patched)) or (
        sum(len(line) + 1 for line in patched) > MAX_RENDER_CHARS
    ):
        return "the doc is too long to render-check"
    try:
        added = added_urls(lines, patched)
    except Exception as error:  # noqa: BLE001 - fail closed on any render failure
        logger.warning("fix render check failed: %s", type(error).__name__)
        return "the render check failed"
    if added:
        return "the fixed doc renders a link or image the original does not"
    return None


class FixGate:
    """The rules layer, then the angle layer when an embedder is set (see the module
    docstring). The angle may only add an ask or a refusal."""

    def __init__(self, *, embedder: Embedder | None = None, thresholds: Thresholds | None = None):
        if thresholds is not None:
            _check_order(thresholds)
        elif embedder is not None:
            raise ValueError("an embedder needs thresholds")
        self._embedder = embedder
        self._thresholds = thresholds

    async def check(self, intent: str, action: FixAction) -> GateResult:
        # The render check parses the doc several times: keep it off the event loop.
        refusal = await asyncio.to_thread(_refusal, action)
        if refusal is not None:
            return GateResult(decision="refuse", reason=refusal)
        if self._embedder is None or self._thresholds is None:
            return GateResult(decision="allow", reason="the fix passes every rule")
        intent_vec, action_vec = await self._embedder.embed([intent, render_fix(action)])
        angle = angle_degrees(intent_vec, action_vec)
        thresholds = self._thresholds
        return GateResult(
            decision=thresholds.decide(angle),
            angle_deg=round(angle, 2),
            reason=(
                f"the fix passes every rule; {angle:.1f} deg vs ask {thresholds.ask_at} "
                f"/ refuse {thresholds.refuse_at}"
            ),
        )


def build_fix_gate(settings: Settings) -> FixGate:
    """The fix gate production runs: the rules alone. The angle layer is an offline
    demonstration (plan R2), so no embedder is configured; ``settings`` is where one
    would come from."""
    return FixGate()
