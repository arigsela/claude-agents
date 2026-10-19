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

from docs_checker.frontmatter import DocMeta, FrontMatterError, parse_front_matter
from docs_checker.repo import ReadResult, RepoReader

DEFAULT_ROOTS = ("base-apps", "docs", "recovery")

_EXCLUDED = (
    re.compile(r"(?:.*/)?SPEC\.md"),
    re.compile(r"docs/superpowers/.*"),
    re.compile(r"base-apps/[^/]+/docs/(?:index|runbook)\.md"),
    re.compile(r"templates/.*"),
)


_EXCLUDED_DIRS = ("docs/superpowers", "templates")


class DiscoveryError(Exception):
    def __init__(self, path: str, status: str):
        self.path = path
        self.status = status
        super().__init__(f"cannot read {path} while discovering docs ({status})")


def in_scope(path: str) -> bool:
    """A candidate by path: a markdown file that is not excluded. (Front matter
    with ``sources`` is the other half; ``discover`` checks it.)"""
    path = path.strip("/")
    return path.endswith(".md") and not any(rule.fullmatch(path) for rule in _EXCLUDED)


def _may_hold_docs(directory: str) -> bool:
    return not directory.strip("/").startswith(_EXCLUDED_DIRS)


async def discover(
    reader: RepoReader, roots: tuple[str, ...] = DEFAULT_ROOTS, *, max_docs: int
) -> tuple[list[str], bool]:
    """In-scope doc paths in listing order, and whether more existed past ``max_docs``."""
    docs: list[str] = []

    async def walk(directory: str) -> bool:  # True once the cap is exceeded
        listing = await reader.list_dir(directory, node="scope")
        if listing.status == "absent":
            return False
        if not listing.found:
            raise DiscoveryError(directory, listing.status)
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
        result = await reader.read(path, node="scope")
        if not result.found:
            raise DiscoveryError(path, result.status)
        try:
            return bool(parse_front_matter(path, result.text or "").sources)
        except FrontMatterError:
            return (result.text or "").startswith("---")

    for root in roots:
        if await walk(root.strip("/")):
            return docs, True
    return docs, False


async def expand_sources(
    reader: RepoReader, meta: DocMeta, *, max_dir_files: int, max_file_bytes: int
) -> tuple[dict[str, ReadResult], list[str]]:
    """What the doc cites, read at the reader's commit, and what was skipped."""
    read: dict[str, ReadResult] = {}
    skipped: list[str] = []

    async def fetch(path: str) -> None:
        path = path.rstrip("/")
        if path in read:
            return
        result = await reader.read(path, node="load")
        if result.found and len((result.text or "").encode()) > max_file_bytes:
            skipped.append(f"{path}: over {max_file_bytes} bytes")
        else:
            read[path] = result

    for source in meta.sources:
        if source.kind == "url":
            skipped.append(f"{source.value}: url")
        elif source.kind == "dir" or source.value.endswith("/"):
            listing = await reader.list_dir(source.value, node="load")
            if not listing.found:
                read[listing.path] = listing
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
