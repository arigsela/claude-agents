"""The render check: a fix may change a doc's text, never its structure (ruling G5).

A fix is model output steered by text anyone who can edit the repository writes.
Per-line rules cannot see block context outside the claim's lines (a fence, an HTML
block or a comment above), and comparing what renders (which links and images)
needs a parser that agrees with GitHub on every edge, which no parser does. So the
check freezes structure instead: the original and the fixed doc are parsed with
markdown-it-py (CommonMark plus GitHub-style linkify), and the two token streams,
inline children included, must be equal token by token in type, tag, nesting,
level, map, markup, info, attrs, block, hidden and meta, and in content except for
plain text and code (``text``, ``code_inline``, ``code_block``, ``fence``, and an
``inline`` token's raw source, whose children are compared one by one). Raw HTML
must be byte-identical. Only plain text and code content can then change, and
``prompts.validate_replacement`` governs that text: no flip, link, image, moved
link or changed attribute is possible, whichever parser renders the doc.

Both views are checked: the whole file, and the body as GitHub shows it (the front
matter's lines left blank), because front matter can open a fence that hides the
body from the first. A doc is refused (fail closed) when a parse reaches the
nesting limit, and when its raw HTML leaves a tag, comment or declaration open: a
browser carries that into the following blocks, where a text-only change (a
quote) can close it and make a link live.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any, NamedTuple

from linkify_it import LinkifyIt
from markdown_it import MarkdownIt
from markdown_it.parser_block import ParserBlock
from markdown_it.parser_inline import ParserInline

# linkify-it validates every link candidate against the rest of its text token, so a
# line of thousands of candidates costs time quadratic in its length. Text tokens
# never cross a line break, so capping the line bounds the cost: at worst about 2 s
# per parse of a 256 KiB doc. A doc beyond either cap gets no fix (fail closed).
MAX_RENDER_LINE_CHARS = 4096
MAX_RENDER_CHARS = 1 << 20  # four times the largest doc discovery reads (256 KiB)

# The commonmark preset stops at 20 and drops what is deeper, which GitHub renders.
# Python's own recursion limit stops a parse long before 1000 (a RecursionError,
# which the gate turns into a refusal); reaching the limit is a refusal too.
MAX_NESTING = 1000

# Token types whose content is plain text or code, free to change. An inline token's
# content is its raw source; its children are compared one by one instead.
FREE_CONTENT = frozenset({"text", "code_inline", "code_block", "fence", "inline"})

_NESTING_LIMIT = "docs_checker_nesting_limit"  # set in the parse env when reached

# A www. link: a domain character, then everything up to a space or "<" (possessive,
# so a validation never backtracks), less trailing punctuation as GitHub drops it.
_WWW_TAIL = re.compile(r"[A-Za-z0-9_-][^\s<]*+")
_URL_TRAILING = "?!.,:*_~'\""


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


class _Block(ParserBlock):
    """Flags a nested block parse entered at the nesting limit (it skips the rest)."""

    def tokenize(self, state: Any, startLine: int, endLine: int) -> None:
        if state.level >= state.md.options.maxNesting:
            state.env[_NESTING_LIMIT] = True
        super().tokenize(state, startLine, endLine)


class _Inline(ParserInline):
    """Flags an inline parse or skip at the nesting limit (each drops what follows)."""

    def tokenize(self, state: Any) -> None:
        if state.level >= state.md.options["maxNesting"]:
            state.env[_NESTING_LIMIT] = True
        super().tokenize(state)

    def skipToken(self, state: Any) -> None:
        if state.level >= state.md.options["maxNesting"]:
            state.env[_NESTING_LIMIT] = True
        super().skipToken(state)


def _any_link(url: str) -> bool:
    """Every link target makes a link, ``javascript:`` too: a renderer may follow
    what markdown-it would drop."""
    return True


@lru_cache(maxsize=2)
def _markdown(max_nesting: int) -> MarkdownIt:
    md = MarkdownIt("commonmark", {"linkify": True, "maxNesting": max_nesting})
    md.enable("linkify")
    md.linkify = _GitHubLinkify()
    md.validateLink = _any_link
    # The preset configured these parsers' rule chains; only the entry points change.
    md.block.__class__ = _Block
    md.inline.__class__ = _Inline
    return md


class _OpenMarkup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)

    def left_open(self, html: str) -> bool:
        """Whether ``html`` ends inside a tag, an attribute value, a comment or a
        declaration (what the parser holds back as incomplete starts with ``<``)."""
        self.feed(html)
        return self.rawdata.lstrip().startswith("<")


class Structure(NamedTuple):
    digest: str  # sha256 over every token's structural fields, in order
    nesting_limit: bool  # the parse reached the nesting limit and dropped content
    open_html: bool  # raw HTML leaves a tag, comment or declaration open


def _feed(digest: Any, tokens: Sequence[Any], state: dict[str, bool]) -> None:
    for token in tokens:
        record = [
            token.type, token.tag, token.nesting, token.level, token.map, token.markup,
            token.info, sorted(token.attrs.items()), token.block, token.hidden, token.meta,
            None if token.type in FREE_CONTENT else token.content,
            len(token.children or ()),
        ]  # fmt: skip
        data = json.dumps(record, default=repr, ensure_ascii=False).encode()
        digest.update(len(data).to_bytes(8, "big") + data)  # length-prefixed: unambiguous
        if token.type in ("html_block", "html_inline") and not state["open_html"]:
            state["open_html"] = _OpenMarkup().left_open(token.content)
        if token.children:
            _feed(digest, token.children, state)


@lru_cache(maxsize=32)  # small results; each check of a doc parses the same original
def structure(text: str, *, max_nesting: int = MAX_NESTING) -> Structure:
    """``text``'s structure as one digest, and whether the parse is trustworthy.
    Raises whatever the parser raises (a RecursionError on very deep nesting)."""
    env: dict[str, Any] = {}
    tokens = _markdown(max_nesting).parse(text, env)
    digest = hashlib.sha256()
    state = {"open_html": False}
    _feed(digest, tokens, state)
    return Structure(digest.hexdigest(), bool(env.get(_NESTING_LIMIT)), state["open_html"])


def _front_matter_lines(lines: Sequence[str]) -> int:
    """How many lines the front matter takes, both fences included; 0 for none."""
    if not lines or lines[0].lstrip("\ufeff").rstrip("\r") != "---":
        return 0
    for number, line in enumerate(lines[1:], start=2):
        if line.rstrip("\r") == "---":
            return number
    return 0


def views(lines: Sequence[str]) -> tuple[str, str]:
    """The doc as plain CommonMark reads it, and as GitHub shows it: the body alone,
    the front matter's lines left blank."""
    head = _front_matter_lines(lines)
    return "\n".join(lines), "\n".join([""] * head + list(lines[head:]))


def structure_refusal(
    original: Sequence[str], patched: Sequence[str], *, max_nesting: int = MAX_NESTING
) -> str | None:
    """Why the patched doc must not replace the original, or None when only plain
    text or code content differs in both views."""
    for lines in (original, patched):
        if any(len(line) > MAX_RENDER_LINE_CHARS for line in lines) or (
            sum(len(line) + 1 for line in lines) > MAX_RENDER_CHARS
        ):
            return "the doc is too long to render-check"
    for before, after in zip(views(original), views(patched), strict=True):
        old = structure(before, max_nesting=max_nesting)
        new = structure(after, max_nesting=max_nesting)
        if old.nesting_limit or new.nesting_limit:
            return "the doc nests deeper than the render check reads"
        if old.digest != new.digest:
            return "the fix changes the doc's structure, not only its text"
        if old.open_html or new.open_html:
            return "the doc's raw HTML leaves a tag or comment open"
    return None
