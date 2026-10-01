"""pr-explainer: group refs that differ in one place, shared by render.py and verify.py.

A PR that touches the same file in six environment directories cites six refs that differ only
in the environment segment. Shown one per line they bury the table, so refs whose display
segments differ at exactly one position collapse into one group: prefix{a, b, c}suffix.
"""
from __future__ import annotations

import re

BOUNDARY = "-_./ "


def entry(item: dict | None, rid: str) -> tuple[str, list[str], set[int]]:
    """(id, display segments, positions allowed to vary). Only the environment of a resource, the
    key of a Terraform instance, or a path segment may vary, so unrelated refs never merge."""
    segs = segments(item, rid)
    if not item or "created" in item:
        allowed: set[int] = set()
    elif "element" in item:  # GitHub Actions: vary on the input, output or job name
        allowed = {1}
    elif "kind" in item or "address" in item:
        allowed = {2} if "kind" in item else {1}
        allowed &= set(range(len(segs))) if len(segs) > 1 else set()
    else:
        allowed = set(range(0, len(segs), 2))  # path parts; the "/" separators sit at odd positions
    return rid, segs, allowed


def segments(item: dict | None, rid: str) -> list[str]:
    """Display text for a ref, split so constant separators never count as the varying part."""
    if not item:
        return [rid]
    if "kind" in item:  # Kubernetes resource; the scope separates the same object in two environments
        text = f'{item["kind"]} {item["namespace"] + "/" if item["namespace"] else ""}{item["name"]}'
        return [text, " · ", item["scope"]] if item.get("scope") else [text]
    if "address" in item:  # Terraform: vary on the for_each key or count index
        m = re.match(r'^(.*\[)("?)([^\]"]*)\2(\]) \((\w+)\)$', f'{item["address"]} ({item["action"]})')
        if m:
            return [m.group(1) + m.group(2), m.group(3), m.group(2) + m.group(4) + f" ({m.group(5)})"]
        return [f'{item["address"]} ({item["action"]})']
    if "element" in item:  # GitHub Actions entry: input enableAurora (removed) · java-deploy.yaml
        return [f'{item["element"]} ', item["name"], f' ({item["action"]}) · {item["workflow"].rsplit("/", 1)[-1]}']
    if "created" in item:  # ticket comment
        return [f'ticket comment {item["created"]}', " · ", item.get("author") or "unknown author"]
    out: list[str] = []
    for i, part in enumerate(item["file"].split("/")):
        out += (["/"] if i else []) + [part]
    return out


def group(refs: list[tuple[str, list[str], set[int]]]) -> list[tuple[int | None, list[tuple[str, list[str], set[int]]]]]:
    """[(varying position or None, [entry, ...])] in first-seen order; each seed takes its largest group."""
    remaining = list(range(len(refs)))
    out = []
    while remaining:
        seed, allowed = refs[remaining[0]][1], refs[remaining[0]][2]
        best, best_pos = [remaining[0]], None
        for pos in sorted(allowed):
            members = [i for i in remaining if len(refs[i][1]) == len(seed) and pos in refs[i][2]
                       and all(refs[i][1][j] == seed[j] for j in range(len(seed)) if j != pos)]
            if len(members) > len(best):
                best, best_pos = members, pos
        out.append((best_pos, [refs[i] for i in best]))
        remaining = [i for i in remaining if i not in best]
    return out


def trim(values: list[str]) -> tuple[str, list[str], str]:
    """Common prefix and suffix of the varying parts, cut back to a boundary character."""
    if len(values) < 2:
        return "", values, ""
    first, last = min(values), max(values)
    n = 0
    while n < min(len(first), len(last)) and first[n] == last[n]:
        n += 1
    while n and first[n - 1] not in BOUNDARY:
        n -= 1
    rev = [v[::-1] for v in values]
    rf, rl = min(rev), max(rev)
    s = 0
    while s < min(len(rf), len(rl)) and rf[s] == rl[s]:
        s += 1
    while s and rf[s - 1] not in BOUNDARY:
        s -= 1
    core = [v[n:len(v) - s] for v in values]
    if any(not c for c in core):
        return "", values, ""
    return values[0][:n], core, values[0][len(values[0]) - s:]
