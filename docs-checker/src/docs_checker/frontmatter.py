"""A doc's YAML front matter: the ``sources:`` it says it describes, with their lines.

Source forms (all under ``sources:``):

- ``- base-apps/x/y.yaml``: a ``path``; a trailing ``/`` makes it a ``dir``;
  ``http(s)://...`` makes it a ``url``.
- ``- {id, resource, title}``: a ``map`` whose ``value`` is its ``resource``
  (a ``url`` when the resource is a link).

``line`` is the 1-based line of the entry in the file, so a finding can point at it.
The YAML is composed, never constructed: no tags are resolved into objects, and
front matter over 64 KiB is refused before it is parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import yaml

MAX_FRONT_MATTER_BYTES = 64 * 1024


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
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise FrontMatterError("no front matter: the file does not start with ---")
    size = 0
    for number, line in enumerate(lines[1:], start=2):
        size += len(line.encode())
        if size > MAX_FRONT_MATTER_BYTES:
            raise FrontMatterError(f"front matter is over {MAX_FRONT_MATTER_BYTES} bytes")
        if line.rstrip("\r\n") == "---":
            return "".join(lines[1 : number - 1]), number + 1
    raise FrontMatterError("front matter is not closed by a --- line")


def _scalar(node: yaml.Node | None) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _source(node: yaml.Node) -> SourceRef:
    line = node.start_mark.line + 2  # the front matter starts on file line 2
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
        sources = [_source(item) for item in node.value]
    return DocMeta(path, sources, _scalar(fields.get("last_reviewed")), body_start)
