"""Strip secret material before anything leaves the runner (spec §8)."""
from __future__ import annotations

import re

SECRET_VALUE_RE = re.compile(
    r"(?i)((?:password|passwd|token|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*)(\S{8,})")
_DATA_KEY_RE = re.compile(r"^(\s*)(data|stringData):\s*$")
_SECRET_KIND_RE = re.compile(r"^kind:\s*Secret\s*$")
_ANY_KIND_RE = re.compile(r"^kind:\s*\S+")


def redact_text(text: str) -> str:
    return SECRET_VALUE_RE.sub(r"\1[REDACTED]", text)


def redact_patch(patch: str) -> str:
    """Mask values under data:/stringData: of kind: Secret documents, then secret-looking values."""
    out: list[str] = []
    in_secret, data_indent = False, None
    for line in patch.splitlines():
        if line.startswith("@@"):
            data_indent = None
            out.append(line)
            continue
        prefix, body = line[:1], line[1:]
        if body.startswith("---"):
            in_secret, data_indent = False, None
        elif _SECRET_KIND_RE.match(body):
            in_secret = True
        elif _ANY_KIND_RE.match(body):
            in_secret = False
        if data_indent is not None:
            indent = len(body) - len(body.lstrip())
            if body.strip() and indent > data_indent:
                out.append(f"{prefix}{' ' * indent}[REDACTED]")
                continue
            data_indent = None
        if in_secret and (m := _DATA_KEY_RE.match(body)):
            data_indent = len(m.group(1))
        out.append(prefix + redact_text(body))
    return "\n".join(out)
