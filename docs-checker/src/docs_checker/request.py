"""What a run was asked to check: structured data first, then the text form."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from docs_checker.scope import in_scope

_TEXT = re.compile(
    r"\s*check\s+(?P<what>.+?)(?:\s+at\s+(?P<ref>\S+))?\s*", re.IGNORECASE | re.DOTALL
)
_REF = re.compile(r"[0-9a-fA-F]{7,40}|[A-Za-z0-9][A-Za-z0-9._/-]*")


class RunRequest(BaseModel):
    scope: Literal["all"] | list[str]
    ref: str = "main"
    mode: Literal["scheduled", "interactive"] = "interactive"
    memory: dict | None = None


def _checked_ref(ref: str) -> str:
    if not _REF.fullmatch(ref) or ".." in ref or ref.endswith(("/", ".lock")):
        raise ValueError(f"not a branch name or 7-40 hex commit: {ref!r}")
    return ref


def _checked_scope(scope: object) -> Literal["all"] | list[str]:
    if scope == "all":
        return "all"
    if not isinstance(scope, list) or not scope or not all(isinstance(p, str) for p in scope):
        raise ValueError("scope must be 'all' or a non-empty list of paths")
    paths = [p.strip().strip("/") for p in scope]
    for path in paths:
        if not in_scope(path):
            raise ValueError(f"out of scope: {path}")
    return paths


def parse_request(text: str | None, data: dict | None) -> RunRequest | None:
    """Data part first, then ``check (all|<path>[, <path>...])( at <ref>)?``, else ``None``.

    A path outside scope, or a ref that is neither a branch name nor 7-40 hex, raises
    ``ValueError``.
    """
    if data and "scope" in data:
        fields = {k: v for k, v in data.items() if k in RunRequest.model_fields}
        fields["scope"] = _checked_scope(fields["scope"])
        if "ref" in fields:
            fields["ref"] = _checked_ref(str(fields["ref"]))
        return RunRequest(**fields)
    match = _TEXT.fullmatch(text or "")
    if not match:
        return None
    what = match["what"].strip()
    scope = (
        "all" if what.lower() == "all" else [p for p in (s.strip() for s in what.split(",")) if p]
    )
    fields = {"scope": _checked_scope(scope)}
    if match["ref"]:
        fields["ref"] = _checked_ref(match["ref"])
    return RunRequest(**fields)
