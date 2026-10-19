"""Which docs are in scope, and what they cite, both bounded.

``discover`` walks the roots with ``list_dir`` and reads each candidate ``.md``
file once to see whether its front matter has ``sources`` (in scope requires
it), so ``max_docs`` counts real in-scope docs. A file that opens ``---`` but
whose front matter is malformed is kept, so the caller can report it; a file
with no front matter is not a doc of ours. A listing or read that fails for any
reason but "absent" raises ``DiscoveryError``: a silently smaller scope would
look like a clean run.

``expand_sources`` reads what a doc cites. Size limits are checked after the
read, because the reader returns whole files; an oversize file is dropped from
the result and reported. Skipped entries read ``"<value>: <reason>"``.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from docs_checker.frontmatter import DocMeta, FrontMatterError, parse_front_matter
from docs_checker.repo import ReadResult, RepoReader, clean_path
from docs_checker.tools import ToolEvent

DEFAULT_ROOTS = ("base-apps", "docs", "recovery")

_EXCLUDED = (
    re.compile(r"(?:.*/)?SPEC\.md"),
    re.compile(r"base-apps/[^/]+/docs/(?:index|runbook)\.md"),
)
_EXCLUDED_DIRS = ("docs/superpowers", "templates")


def _under(path: str, directory: str) -> bool:
    """Whole path segments: ``templates-old`` is not under ``templates``."""
    return path == directory or path.startswith(directory + "/")


class DiscoveryError(Exception):
    """Scope could not be established. ``failures`` is every (path, status) that
    failed, so one error names all of them."""

    def __init__(self, failures: list[tuple[str, str]] | str, status: str = ""):
        if isinstance(failures, str):
            failures = [(failures, status)]
        self.failures = [Failure(p, st) for p, st in failures]
        self.path = self.failures[0].path
        self.status = self.failures[0].status
        listed = ", ".join(f"{f.path} ({f.status})" for f in self.failures)
        super().__init__(f"cannot establish the docs in scope: {listed}")


class Failure(NamedTuple):
    path: str
    status: str


def in_scope(path: str) -> bool:
    """A candidate by path: a markdown file that is not excluded. (Front matter
    with ``sources`` is the other half; ``discover`` checks it.)"""
    path = path.strip("/")
    return (
        path.endswith(".md")
        and not any(rule.fullmatch(path) for rule in _EXCLUDED)
        and not any(_under(path, d) for d in _EXCLUDED_DIRS)
    )


def _may_hold_docs(directory: str) -> bool:
    directory = directory.strip("/")
    return not any(_under(directory, d) for d in _EXCLUDED_DIRS)


async def _retrying(call, path: str) -> ReadResult:
    """One retry for a transient answer (2 attempts in all)."""
    result = await call(path, node="scope")
    if result.status == "transient":
        result = await call(path, node="scope")
    return result


async def discover(
    reader: RepoReader,
    roots: tuple[str, ...] = DEFAULT_ROOTS,
    *,
    max_docs: int,
    profile: Any = None,
) -> tuple[list[str], bool]:
    """In-scope doc paths in listing order, and whether more existed past ``max_docs``.

    With a repo profile the docs are the profile's, in its order, and nothing is
    walked: a listed doc that is gone is reported by the scope stage's read.

    A file that will not read (after one retry of a transient answer) stays in
    the list, so the load stage reports that doc failed and the run goes on. A
    directory that will not list is remembered while the walk continues, and all
    of them are raised together at the end: a partial list is never returned as
    complete. When every root is absent the roots are wrong, and that raises too.
    """
    if profile is not None:
        listed = list(profile.docs)
        return listed[:max_docs], len(listed) > max_docs
    docs: list[str] = []
    failures: list[tuple[str, str]] = []

    absent_roots = 0

    async def walk(directory: str, *, is_root: bool = False) -> bool:  # True past the cap
        nonlocal absent_roots
        listing = await _retrying(reader.list_dir, directory)
        if listing.status == "absent":
            absent_roots += is_root
            return False
        if not listing.found:
            failures.append((directory, listing.status))
            return False
        for entry in (listing.text or "").splitlines():
            if entry.endswith("/"):
                if _may_hold_docs(entry) and await walk(entry.rstrip("/")):
                    return True
            elif in_scope(entry) and await has_sources(entry):
                if len(docs) >= max_docs:
                    return True
                docs.append(entry)
        return False

    async def has_sources(path: str) -> bool:
        result = await _retrying(reader.read, path)
        if result.status == "absent":  # listed, yet not there at this commit
            raise DiscoveryError(path, result.status)
        if not result.found:
            return True  # the load stage reports it with the reader's status
        try:
            return bool(parse_front_matter(path, result.text or "").sources)
        except FrontMatterError:
            return (result.text or "").startswith("---")

    truncated = False
    for root in roots:
        truncated = await walk(root.strip("/"), is_root=True)
        if truncated:
            break
    if failures:
        raise DiscoveryError(failures)
    if roots and absent_roots == len(roots):
        raise DiscoveryError([(r.strip("/"), "absent") for r in roots])
    return docs, truncated


async def expand_sources(
    reader: RepoReader,
    meta: DocMeta,
    *,
    max_dir_files: int,
    max_file_bytes: int,
    events: list[ToolEvent] | None = None,
) -> tuple[dict[str, ReadResult], list[str]]:
    """What the doc cites, read at the reader's commit, and what was skipped. Each
    read's tool event is appended to ``events`` when a list is given. The result is
    keyed by ``clean_path`` (one spelling per path, as the reader names it), and
    ``graph_doc.load`` looks a source up the same way (review M2)."""
    read: dict[str, ReadResult] = {}
    skipped: list[str] = []

    async def fetch(path: str) -> None:
        path = clean_path(path)
        if path in read:
            return
        result = await reader.read(path, node="load", events=events)
        if result.found and len((result.text or "").encode()) > max_file_bytes:
            skipped.append(f"{path}: over {max_file_bytes} bytes")
        else:
            read[path] = result

    for source in meta.sources:
        if source.kind == "url":
            skipped.append(f"{source.value}: url")
        elif source.kind == "dir" or source.value.endswith("/"):
            listing = await reader.list_dir(source.value, node="load", events=events)
            if not listing.found:
                read[clean_path(source.value)] = listing
                continue
            entries = (listing.text or "").splitlines()
            files = [e for e in entries if not e.endswith("/")]
            skipped += [f"{e.rstrip('/')}: subdirectory" for e in entries if e.endswith("/")]
            for path in files[:max_dir_files]:
                await fetch(path)
            skipped += [
                f"{p}: over {max_dir_files} files in the directory" for p in files[max_dir_files:]
            ]
        else:
            await fetch(source.value)
    return read, skipped
