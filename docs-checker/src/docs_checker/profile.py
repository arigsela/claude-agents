"""Repo profiles: the docs to check and their sources, for repos whose docs carry no
``sources:`` front matter (the CHG OpenTofu repos).

A profile is a YAML file in the image (``DOCS_CHECKER_PROFILE``):

    repo: owner/name
    domain: <what the evidence files are, for the prompts>
    docs:
      <doc path>:
        - path: <file>
        - dir: <directory>

Its sources become the doc's ``DocMeta.sources`` exactly as front matter would, so
everything after scope is unchanged. A profile source carries ``line`` 0: no doc line
names it, so an absent one leaves the doc incomplete (the profile is stale) instead of
a ``missing`` finding on the doc.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from docs_checker.evidence import is_evidence_source
from docs_checker.frontmatter import DocMeta, FrontMatterError, SourceRef, parse_front_matter

PROFILE_SOURCE_LINE = 0


@dataclass(frozen=True)
class RepoProfile:
    repo: str
    domain: str
    docs: dict[str, tuple[SourceRef, ...]]


def _sources(doc: str, entries: object) -> tuple[SourceRef, ...]:
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"profile doc {doc!r} lists no sources")
    sources = []
    for entry in entries:
        if not (isinstance(entry, dict) and len(entry) == 1):
            raise ValueError(f"profile doc {doc!r}: a source is one `path:` or `dir:`")
        ((kind, value),) = entry.items()
        if kind not in ("path", "dir") or not isinstance(value, str) or not value.strip():
            raise ValueError(f"profile doc {doc!r}: bad source {entry!r}")
        value = value.strip().strip("/")
        if not is_evidence_source(value):
            raise ValueError(f"profile doc {doc!r}: {value!r} is documentation, not evidence")
        sources.append(SourceRef(kind=kind, value=value, line=PROFILE_SOURCE_LINE))
    return tuple(sources)


def parse_profile(text: str, *, repo: str) -> RepoProfile:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or set(raw) != {"repo", "domain", "docs"}:
        raise ValueError("a profile has exactly repo, domain and docs")
    if raw["repo"] != repo:
        raise ValueError(f"profile repo {raw['repo']!r} is not DOCS_CHECKER_REPO {repo!r}")
    if not isinstance(raw["domain"], str) or not raw["domain"].strip():
        raise ValueError("profile domain is empty")
    docs = raw["docs"]
    if not isinstance(docs, dict) or not docs:
        raise ValueError("profile lists no docs")
    return RepoProfile(
        repo=raw["repo"],
        domain=raw["domain"].strip(),
        docs={str(doc).strip("/"): _sources(str(doc), entries) for doc, entries in docs.items()},
    )


def load_profile(path: str, *, repo: str) -> RepoProfile:
    with open(path, encoding="utf-8") as handle:
        return parse_profile(handle.read(), repo=repo)


def doc_meta(path: str, text: str, profile: RepoProfile | None) -> DocMeta:
    """The doc's sources from the profile when it lists the doc, else its front matter.

    Front matter is still parsed for where the body starts; a doc with none, or with
    front matter that does not parse, starts at line 1."""
    if profile is None or path not in profile.docs:
        return parse_front_matter(path, text)
    try:
        parsed = parse_front_matter(path, text)
        body_start, last_reviewed = parsed.body_start, parsed.last_reviewed
    except FrontMatterError:
        body_start, last_reviewed = 1, None
    return DocMeta(
        path=path,
        sources=list(profile.docs[path]),
        last_reviewed=last_reviewed,
        body_start=body_start,
    )
