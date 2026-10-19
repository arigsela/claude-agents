"""Evidence windows and a narrow code judge (cost levers 6 and 7).

Windows are small slices of the source files (not whole files). The code judge decides
only the clear cases without a model; everything else goes on to a model.

Choices: values match case-sensitively as whole tokens, keys case-insensitively as whole
tokens. A YAML comment is a line starting with ``#`` (after spaces); lines inside a block
scalar are not recognised, which is deliberately simple. A hit is a non-comment line
holding a claim value (a key on the same line ranks it higher), or, ranked last, a line
with a claim key in YAML key position (``key:`` or ``- key:``, ruling K1): that is how a
value that changed in the manifest is still found. Only a value makes evidence
"sufficient" (``insufficient``): a key-only window still lets the caller widen.
"""

from __future__ import annotations

import re

from docs_checker.state import Claim, Decision, Window

_COMMENT = re.compile(r"^\s*#")
_DOC_FILES = {"SPEC.md"}


def is_evidence_source(path: str) -> bool:
    """False for documentation: ``*.md``, ``docs/**``, ``base-apps/*/docs/**``, SPEC.md, ``templates/**``.

    Matched by path segments, so ``templates-old/`` and ``mydocs/`` stay evidence.
    """
    parts = [p for p in path.split("/") if p]
    if not parts:
        return False
    if parts[-1].lower().endswith(".md") or parts[-1] in _DOC_FILES:
        return False
    if parts[0] in {"docs", "templates"}:
        return False
    return not (len(parts) > 2 and parts[0] == "base-apps" and parts[2] == "docs")


def _token(value: str, flags: int = 0) -> re.Pattern[str]:
    """``value`` as a whole token: not inside a longer word, number or dotted name on
    either side ("1.2" is not the tail of "0.1.2", nor "example.com" of
    "mail.example.com", nor "8080" of "18080"); quotes and a digest around it are fine."""
    return re.compile(r"(?<![\w.-])" + re.escape(value) + r"(?![\w-]|\.\w)", flags)


def _has_value(line: str, values: list[str]) -> bool:
    return any(_token(v).search(line) for v in values if v)


def _has_all_values(line: str, values: list[str]) -> bool:
    return all(_token(v).search(line) for v in values)


def _has_key(line: str, keys: list[str]) -> bool:
    return any(_token(k, re.IGNORECASE).search(line) for k in keys if k)


def _key_line(key: str) -> re.Pattern[str]:
    """``key`` in YAML key position: the line's first token (after a list dash), then ``:``."""
    return re.compile(r"^\s*-?\s*" + re.escape(key) + r"\s*:", re.IGNORECASE)


def _in_key_position(line: str, keys: list[str]) -> bool:
    return any(_key_line(k).match(line) for k in keys if k)


_INLINE_COMMENT = re.compile(r"\s#.*$")


def _code(line: str) -> str:
    """The line without a trailing ``  # comment`` (a quoted ``#`` is not handled)."""
    return _INLINE_COMMENT.sub("", line)


def _is_comment(line: str) -> bool:
    return bool(_COMMENT.match(line))


def code_only(text: str) -> str:
    """What of ``text`` can be evidence: comment lines dropped, trailing ``# ...`` cut."""
    return "\n".join(_code(line) for line in text.split("\n") if not _is_comment(line))


def windows_for(
    claim: Claim,
    sources: dict[str, str],
    *,
    radius: int = 3,
    max_windows: int = 5,
) -> list[Window]:
    """Up to ``max_windows`` windows of ±``radius`` lines around hits, best first:
    key+value lines, then value-only lines, then key-position lines (ruling K1); within a
    tier, the source the claim names (``source_hint``) first, then the doc's source order.
    When the named source has a hit, one of its windows is always kept: a value common to
    many files (an app's own name) must not crowd out the file the claim is about."""
    values = [v for v in claim.values if v]
    if not values:
        return []
    hits: list[tuple[int, int, str, int]] = []  # (tier, source order, source, line)
    for order, (path, text) in enumerate(sources.items()):
        if not is_evidence_source(path):
            continue
        for n, line in enumerate(text.split("\n"), start=1):
            if _is_comment(line):
                continue
            code = _code(line)
            if _has_value(code, values):
                tier = 0 if _has_key(code, claim.keys) else 1
            elif _in_key_position(code, claim.keys):
                tier = 2
            else:
                continue
            hits.append((tier, order, path, n))
    hint = _clean_path(claim.source_hint)
    hits.sort(key=lambda h: (h[0], h[2] != hint, h[1], h[3]))

    spans: list[list] = []  # [source, start, end] in selection order
    for _tier, _order, path, n in hits:
        lo, hi = n - radius, n + radius
        merged = next(
            (s for s in spans if s[0] == path and lo <= s[2] + 1 and hi >= s[1] - 1), None
        )
        if merged:
            merged[1], merged[2] = min(merged[1], lo), max(merged[2], hi)
        elif len(spans) < max_windows:
            spans.append([path, lo, hi])
    # Merging can make two kept spans touch; fold them together.
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(spans):
            for b in spans[i + 1 :]:
                if a[0] == b[0] and a[1] <= b[2] + 1 and b[1] <= a[2] + 1:
                    a[1], a[2] = min(a[1], b[1]), max(a[2], b[2])
                    spans.remove(b)
                    changed = True
                    break
            if changed:
                break

    hinted = next((h for h in hits if h[2] == hint), None) if hint else None
    if hinted and not any(s[0] == hint for s in spans):
        span = [hint, hinted[3] - radius, hinted[3] + radius]
        if len(spans) < max_windows:
            spans.append(span)
        elif spans:
            spans[-1] = span

    out: list[Window] = []
    for path, lo, hi in spans:
        rows = sources[path].split("\n")
        lo, hi = max(1, lo), min(len(rows), hi)
        out.append(Window(source=path, start=lo, end=hi, text="\n".join(rows[lo - 1 : hi])))
    return out


def _clean_path(path: str) -> str:
    return (path or "").strip().strip("`").removeprefix("./").lstrip("/")


def named_thing_present(claim: Claim, sources: dict[str, str]) -> str | None:
    """Where the thing a claim names still is, or None. A path claim names a file: present
    when that file was read. Any other claim names values: present when one of them is on a
    code line of the source the claim names (``source_hint``) if that source was read,
    else of any evidence source. A ``missing`` verdict on a present thing is contradicted
    by the repository (a model that saw only other files' windows can call it missing)."""
    if claim.kind == "path":
        wanted = {_clean_path(v) for v in claim.values if v}
        return next((p for p in sources if _clean_path(p) in wanted), None)
    values = [v for v in claim.values if v]
    if not values:
        return None
    hint = _clean_path(claim.source_hint)
    scope = {hint: sources[hint]} if hint in sources else sources
    for path, text in scope.items():
        if not is_evidence_source(path):
            continue
        if any(
            _has_value(_code(line), values) for line in text.split("\n") if not _is_comment(line)
        ):
            return path
    return None


def whole_files(sources: dict[str, str]) -> list[Window]:
    """One window per evidence file: the path used when ``shrink_results`` is off."""
    return [
        Window(source=p, start=1, end=len(t.split("\n")), text=t)
        for p, t in sources.items()
        if is_evidence_source(p)
    ]


def insufficient(windows: list[Window], claim: Claim) -> bool:
    """True when no window holds any claim value in its code (comments never count):
    this triggers the widening and search fallbacks. A key-only window (K1) is
    insufficient, so widening can still add real evidence."""
    values = [v for v in claim.values if v]
    return not any(_has_value(code_only(w.text), values) for w in windows)


def decide_in_code(claim: Claim, windows: list[Window], absent_paths: set[str]) -> Decision | None:
    """``supported`` or ``missing`` only when certain; otherwise None (a model decides)."""
    values = [v for v in claim.values if v]
    if not values or len(values) != len(claim.values):
        return None
    keys = [k for k in claim.keys if k]
    if keys:
        for i, w in enumerate(windows):
            if not is_evidence_source(w.source):
                continue
            for raw in w.text.split("\n"):
                line = _code(raw)
                if not _is_comment(raw) and _has_key(line, keys) and _has_all_values(line, values):
                    return Decision(
                        verdict="supported",
                        confidence=0.95,
                        reason="One line holds the key and every value.",
                        window_index=i,
                        judged_by="code",
                    )
    if claim.kind == "path" and all(v in absent_paths for v in values):
        return Decision(
            verdict="missing",
            confidence=0.9,
            reason="The path is confirmed absent at this commit.",
            window_index=None,
            judged_by="code",
        )
    return None
