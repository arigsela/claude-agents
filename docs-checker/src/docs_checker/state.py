"""Typed handoffs between graph nodes (cost lever 2): small validated models, not transcripts.

Size limits are Pydantic constraints, so an over-long model answer fails validation
instead of flowing on. ``DocOutcome.tool_events`` is the one exception: events are
produced by code, not a model, so an over-long list is truncated (first 50 kept).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from docs_checker.tools import ToolEvent

Verdict = Literal["supported", "stale", "missing", "unsupported"]
ClaimKind = Literal[
    "version", "image", "chart", "name", "namespace", "host",
    "port", "path", "schedule", "resources", "count", "config",
]  # fmt: skip
Status = Literal["checked", "unchanged", "incomplete", "skipped-budget", "failed"]

MAX_TOOL_EVENTS = 50


def _sha(*parts: object) -> str:
    """Unambiguous: the parts are hashed as a JSON list, so no join can collide."""
    blob = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


class Window(BaseModel):
    source: str
    start: int
    end: int
    text: str


def evidence_hash(windows: list[Window]) -> str:
    """Hash of the evidence a claim was judged against, in order."""
    h = hashlib.sha256()
    for w in windows:
        for part in (w.source, w.start, w.end, w.text):
            data = str(part).encode()
            h.update(len(data).to_bytes(8, "big") + data)  # length-prefixed: no ambiguity
    return h.hexdigest()


class Claim(BaseModel):
    doc: str
    line_start: int
    line_end: int
    text: str = Field(max_length=400)
    kind: ClaimKind
    keys: list[str] = Field(default_factory=list, max_length=5)
    values: list[str] = Field(min_length=1, max_length=5)
    source_hint: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return _sha(self.doc, self.line_start, self.line_end, self.text)[:16]

    def semantic_key(self, checker_version: str, evidence_hash: str) -> str:
        """Cache key for a judgement: what is claimed, the checker, and the evidence.

        Identical claims judged against different evidence never share a key (J4).
        """
        return _sha(
            _norm(self.text),
            self.kind,
            [_norm(k) for k in self.keys],
            [_norm(v) for v in self.values],
            checker_version,
            evidence_hash,
        )


class Evidence(BaseModel):
    claim_id: str
    windows: list[Window] = Field(default_factory=list, max_length=5)
    searched: bool = False


class Decision(BaseModel):
    """Identity-free, so it is the cached unit."""

    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=300)
    window_index: int | None = None
    judged_by: str


class Judgement(BaseModel):
    claim_id: str
    decision: Decision


class Finding(BaseModel):
    id: str
    instance: str  # eval scoping (C#31)
    commit: str
    doc: str
    line_start: int
    line_end: int
    claim: Claim
    verdict: Literal["stale", "missing"]
    evidence: Window | None = None
    evidence_hash: str
    confidence: float = Field(ge=0, le=1)
    old_text: str
    replacement: str
    needs_look: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def action_digest(self) -> str:
        """What an approval binds to (C#24): change any part and the digest changes."""
        return _sha(
            self.commit, self.doc, self.line_start, self.line_end,
            self.old_text, self.replacement, self.evidence_hash,
        )[:24]  # fmt: skip


class DocOutcome(BaseModel):
    doc: str
    commit: str
    status: Status
    reason: str = ""
    findings: list[Finding] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    fingerprint: dict[str, str] = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    refused: int = 0
    tool_events: list[ToolEvent] = Field(default_factory=list)
    transcript: list[str] = Field(default_factory=list)

    @field_validator("tool_events", mode="after")
    @classmethod
    def _cap_events(cls, events: list[ToolEvent]) -> list[ToolEvent]:
        return events[:MAX_TOOL_EVENTS]


def merge_outcomes(
    old: dict[str, DocOutcome] | None, new: dict[str, DocOutcome]
) -> dict[str, DocOutcome]:
    """LangGraph reducer keyed by doc: the later outcome wins; inputs are not mutated."""
    return {**(old or {}), **new}


OutcomeMap = Annotated[dict[str, DocOutcome], merge_outcomes]
