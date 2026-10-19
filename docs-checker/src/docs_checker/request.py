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


def _checked_ref(ref: object) -> str:
    if not isinstance(ref, str):
        raise ValueError(f"ref must be a string: {ref!r}")  # noqa: TRY004
    if not _REF.fullmatch(ref) or ".." in ref or ref.endswith(("/", ".lock")):
        raise ValueError(f"not a branch name or 7-40 hex commit: {ref!r}")
    return ref


def _checked_path(path: object) -> str:
    """Exactly a normalized repo-relative path: nothing is stripped or rewritten."""
    if not isinstance(path, str):
        raise ValueError(f"path must be a string: {path!r}")  # noqa: TRY004
    segments = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(c.isspace() or not c.isprintable() for c in path)
        or any(seg in ("", ".", "..") for seg in segments)
    ):
        raise ValueError(f"not a normalized repo-relative path: {path!r}")
    if not in_scope(path):
        raise ValueError(f"out of scope: {path}")
    return path


def _checked_scope(scope: object, max_paths: int) -> Literal["all"] | list[str]:
    if scope == "all":
        return "all"
    if not isinstance(scope, list) or not scope:
        raise ValueError("scope must be 'all' or a non-empty list of paths")
    paths = list(dict.fromkeys(_checked_path(p) for p in scope))  # dedupe, keep order
    if len(paths) > max_paths:
        raise ValueError(f"too many paths: {len(paths)} (at most {max_paths})")
    return paths


def parse_request(text: str | None, data: object, *, max_paths: int = 80) -> RunRequest | None:
    """Data part first, then ``check (all|<path>[, <path>...])( at <ref>)?``, else ``None``.

    ``data`` that is not a dict, and a non-string ref or path, raise ``ValueError``. A path that is not normalized
    or is outside scope, a ref that is neither a branch name nor 7-40 hex, or more
    than ``max_paths`` distinct paths raises ``ValueError``. Duplicate paths are
    dropped, keeping order.
    """
    if data is not None and not isinstance(data, dict):
        raise ValueError("request data must be an object")
    if data and "scope" in data:
        fields = {k: v for k, v in data.items() if k in RunRequest.model_fields}
        fields["scope"] = _checked_scope(fields["scope"], max_paths)
        if "ref" in fields:
            fields["ref"] = _checked_ref(fields["ref"])
        return RunRequest(**fields)
    match = _TEXT.fullmatch(text or "")
    if not match:
        return None
    what = match["what"].strip()
    scope = "all" if what.lower() == "all" else [s.strip() for s in what.split(",")]
    fields = {"scope": _checked_scope(scope, max_paths)}
    if match["ref"]:
        fields["ref"] = _checked_ref(match["ref"])
    return RunRequest(**fields)
