"""Deterministic PR features (no model calls). Spec §5.2."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import yaml

from .policy import Policy, component_of
from .redact import redact_patch

EXCERPT_CAP = 32_000
BODY_CAP = 2_000
IMAGE_BUMP_MAX_LINES = 4
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
KIND_LINE_RE = re.compile(r"^[+-]kind:\s*([A-Za-z0-9]+)\s*$")
DOC_KIND_RE = re.compile(r"^kind:\s*([A-Za-z0-9]+)")
IMAGE_LINE_RE = re.compile(r"^[+-]\s*(?:-\s*)?(?:image|tag):\s*\S+\s*$")
K3S_RE = re.compile(r"v\d+\.\d+\.\d+\+k3s\d+")
APP_FILE_RE = re.compile(r"^base-apps/[^/]+\.ya?ml$")
SOURCE_FIELDS = ("repoURL", "chart", "targetRevision", "path", "helm", "directory")
SPEC_FIELDS = ("destination", "syncPolicy", "ignoreDifferences")

Fetch = Callable[[str, str], "str | None"]  # (path, ref) -> file text, or None if absent


@dataclass
class Features:
    number: int
    title: str
    body: str
    size_bucket: str
    lines_changed: int
    files: list[str]
    components: list[str]
    hot_components_touched: list[str]
    kinds_changed: list[str]
    application_changes: dict[str, list[str]]
    signals: list[str]
    image_bump_files: list[str]
    patchless_files: list[str]
    diff_excerpt: str

    def jev_state(self) -> dict:
        """The only PR data sent to Jev/Claude: named buckets, no raw counts (Jev is weak at math)."""
        return {
            "title": self.title,
            "body": self.body,
            "size": self.size_bucket,
            "components": self.components,
            "hot_components_touched": self.hot_components_touched,
            "kinds_changed": self.kinds_changed,
            "application_changes": self.application_changes,
            "signals": self.signals,
            "diff_excerpt": self.diff_excerpt,
        }


def size_bucket(lines: int) -> str:
    if lines <= 10:
        return "tiny"
    if lines <= 100:
        return "small"
    if lines <= 500:
        return "medium"
    return "large"


def changed_lines(patch: str) -> list[str]:
    # GitHub's per-file `patch` has no ---/+++ headers, so every +/- line is content.
    return [line for line in patch.splitlines() if line[:1] in ("+", "-")]


def _hunk_ranges(patch: str) -> list[tuple[int, int]]:
    out = []
    for m in HUNK_RE.finditer(patch):
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) is not None else 1
        out.append((start, start + max(length, 1) - 1))
    return out


def _kinds_in_hunks(text: str, patch: str) -> set[str]:
    """Kinds of the YAML documents in `text` (head version) whose lines the patch's hunks touch."""
    docs, start, kind = [], 1, None
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        if line.startswith("---"):
            docs.append((start, i - 1, kind))
            start, kind = i + 1, None
        elif kind is None and (m := DOC_KIND_RE.match(line)):
            kind = m.group(1)
    docs.append((start, len(lines), kind))
    return {k for a, b in _hunk_ranges(patch) for s, e, k in docs if k and s <= b and a <= e}


def _load_application(text: str | None) -> dict:
    if not text:
        return {}
    try:
        for doc in yaml.safe_load_all(text):
            if isinstance(doc, dict) and doc.get("kind") == "Application":
                return doc
    except yaml.YAMLError:
        return {}
    return {}


def application_changes(base_text: str | None, head_text: str | None) -> list[str]:
    a, b = _load_application(base_text), _load_application(head_text)
    if not a and not b:
        return []
    if not a:
        return ["added"]
    if not b:
        return ["removed"]
    sa, sb = a.get("spec") or {}, b.get("spec") or {}
    src_a, src_b = sa.get("source") or {}, sb.get("source") or {}
    out = [f"source.{f}" for f in SOURCE_FIELDS if src_a.get(f) != src_b.get(f)]
    out += [f for f in SPEC_FIELDS if sa.get(f) != sb.get(f)]
    return out or ["other"]


def build_excerpt(files: list[dict], policy: Policy) -> str:
    def priority(f: dict) -> int:
        path = f["filename"]
        if policy.always_read_paths.match_file(path):
            return 0
        if component_of(path) in policy.hot_components:
            return 1
        return 2

    parts, used = [], 0
    for f in sorted(files, key=priority):
        patch = f.get("patch")
        body = redact_patch(patch) if patch is not None else "[patch omitted by GitHub: file too large or binary]"
        chunk = f"### {f['filename']} ({f['status']})\n{body}\n"
        room = EXCERPT_CAP - used
        if len(chunk) > room:
            parts.append(chunk[: max(room, 0)] + "\n[excerpt truncated]")
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


def extract_features(pr: dict, files: list[dict], policy: Policy, fetch: Fetch) -> Features:
    base_sha, head_sha = pr["base"]["sha"], pr["head"]["sha"]
    paths = [f["filename"] for f in files]
    all_paths = paths + [f["previous_filename"] for f in files if f.get("previous_filename")]
    components = sorted({component_of(p) for p in all_paths})
    kinds: set[str] = set()
    app_changes: dict[str, list[str]] = {}
    signals: set[str] = set()
    image_files: list[str] = []
    patchless: list[str] = []
    image_lines = 0
    for f in files:
        path, status, patch = f["filename"], f["status"], f.get("patch")
        prev = f.get("previous_filename")
        if patch is None:
            patchless.append(path)
        else:
            lines = changed_lines(patch)
            kinds |= {m.group(1) for line in lines if (m := KIND_LINE_RE.match(line))}
            if any(K3S_RE.search(line) for line in lines):
                signals.add("k3s_version_change")
            if status == "modified" and lines and all(IMAGE_LINE_RE.match(line) for line in lines):
                image_files.append(path)
                image_lines += len(lines)
            if status in ("modified", "renamed") and path.endswith((".yaml", ".yml")):
                head_text = fetch(path, head_sha)
                if head_text:
                    kinds |= _kinds_in_hunks(head_text, patch)
        if APP_FILE_RE.match(path) or (prev and APP_FILE_RE.match(prev)):
            base_text = None if status == "added" else fetch(prev or path, base_sha)
            head_text = None if status == "removed" else fetch(path, head_sha)
            changes = application_changes(base_text, head_text)
            if changes:
                app_changes[path] = changes
            if changes == ["removed"]:
                signals.add("application_deleted")
    if image_lines > IMAGE_BUMP_MAX_LINES:
        image_files = []
    if image_files and len(image_files) == len(files):
        signals.add("image_tag_bump_only")
    lines_changed = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
    return Features(
        number=pr["number"],
        title=pr.get("title") or "",
        body=(pr.get("body") or "")[:BODY_CAP],
        size_bucket=size_bucket(lines_changed),
        lines_changed=lines_changed,
        files=paths,
        components=components,
        hot_components_touched=sorted(c for c in components if c in policy.hot_components),
        kinds_changed=sorted(kinds),
        application_changes=app_changes,
        signals=sorted(signals),
        image_bump_files=image_files,
        patchless_files=patchless,
        diff_excerpt=build_excerpt(files, policy),
    )
