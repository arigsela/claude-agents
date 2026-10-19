"""A doc's YAML front matter: the ``sources:`` it says it describes, with their lines.

Source forms (all under ``sources:``):

- ``- base-apps/x/y.yaml``: a ``path``; a trailing ``/`` makes it a ``dir``;
  ``http(s)://...`` makes it a ``url``.
- ``- {id, resource, title}``: a ``map`` whose ``value`` is its ``resource``
  (a ``url`` when the resource is a link).

``line`` is the 1-based line of the entry in the file, so a finding can point at it.
The YAML is composed, never constructed: no tags are resolved into objects, and
front matter over 64 KiB is refused before it is parsed.

Lines are counted by ``\\n`` only (``text.split("\\n")``), the way every other part of
the checker numbers a doc's lines: a form feed, NEL or U+2028 inside a line is not a
line break here, whatever ``str.splitlines`` (or YAML, which breaks at NEL, U+2028
and U+2029 too) would say; YAML's line of a source is mapped back to ``\\n`` counting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import yaml

MAX_FRONT_MATTER_BYTES = 64 * 1024

# What PyYAML's reader counts as a line break (pyyaml reader.py / scanner.py).
_YAML_BREAK = re.compile(r"\r\n|[\r\n\x85  ]")


class FrontMatterError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SourceRef:
    kind: Literal["path", "dir", "map", "url"]
    value: str
    line: int


@dataclass(frozen=True)
class DocMeta:
    path: str
    sources: list[SourceRef]
    last_reviewed: str | None
    body_start: int  # 1-based line of the first line after the closing fence


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _split(text: str) -> tuple[str, int]:
    """The front matter's text and the 1-based line after its closing fence."""
    lines = text.lstrip("﻿").split("\n")
    if lines[0].rstrip("\r") != "---":
        raise FrontMatterError("no front matter: the file does not start with ---")
    size = 0
    for number, line in enumerate(lines[1:], start=2):
        size += len(line.encode()) + 1
        if size > MAX_FRONT_MATTER_BYTES:
            raise FrontMatterError(f"front matter is over {MAX_FRONT_MATTER_BYTES} bytes")
        if line.rstrip("\r") == "---":
            return "\n".join(lines[1 : number - 1]) + "\n", number + 1
    raise FrontMatterError("front matter is not closed by a --- line")


def _line_map(block: str) -> list[int]:
    """For each of YAML's (0-based) lines of ``block``, the file line it starts on,
    counting lines by ``\\n`` only; the block starts on file line 2."""
    starts = [0, *(m.end() for m in _YAML_BREAK.finditer(block))]
    return [2 + block.count("\n", 0, at) for at in starts]


def _scalar(node: yaml.Node | None) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _source(node: yaml.Node, lines: list[int]) -> SourceRef:
    line = lines[min(node.start_mark.line, len(lines) - 1)]
    if isinstance(node, yaml.ScalarNode):
        value = node.value.strip()
        if not value:
            raise FrontMatterError(f"line {line}: an empty source")
        kind = "url" if _is_url(value) else "dir" if value.endswith("/") else "path"
        return SourceRef(kind, value, line)
    if isinstance(node, yaml.MappingNode):
        fields = {_scalar(k): v for k, v in node.value}
        resource = (_scalar(fields.get("resource")) or "").strip()
        if not resource:
            raise FrontMatterError(f"line {line}: a source map has no resource")
        return SourceRef("url" if _is_url(resource) else "map", resource, line)
    raise FrontMatterError(f"line {line}: a source must be a path or a map with a resource")


def parse_front_matter(path: str, text: str) -> DocMeta:
    """The doc's sources and review date. Raises ``FrontMatterError`` with the reason."""
    block, body_start = _split(text)
    try:
        root = yaml.compose(block, Loader=yaml.SafeLoader)
    except yaml.YAMLError as err:
        raise FrontMatterError(f"front matter is not valid YAML: {err}") from err
    if not isinstance(root, yaml.MappingNode):
        raise FrontMatterError("front matter is not a mapping")
    fields = {_scalar(k): v for k, v in root.value}
    sources: list[SourceRef] = []
    node = fields.get("sources")
    if node is not None:
        if not isinstance(node, yaml.SequenceNode):
            raise FrontMatterError("sources is not a list")
        lines = _line_map(block)
        sources = [_source(item, lines) for item in node.value]
    return DocMeta(path, sources, _scalar(fields.get("last_reviewed")), body_start)
