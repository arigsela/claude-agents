"""Secret redaction in code, not only in prompts.

Applied at both ends: to every tool result before a model sees it, and to every
model-written fact, answer and published tool argument before it leaves the
agent. Repo files and catalog text are untrusted, and a prompt instruction ("never
quote a credential") is not a control.

Two kinds of rule:

- token shapes that are secrets wherever they appear (provider key prefixes,
  private key blocks, JWTs, bearer headers);
- ``key: value`` / ``KEY=value`` pairs whose key names a credential, where the
  value is redacted. References are kept (``${VAR}``, ``{{ .x }}``, ``<placeholder>``),
  as are empty values and nested mappings.

It errs on the side of redacting: a non-secret value under a key like
``existingSecret`` is masked too. A false positive costs a word in an answer; a
false negative leaks a credential.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        # PEM private keys, whole block (or to the end of a truncated text).
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b",  # AWS access key ids
        r"\bsk-ant-[A-Za-z0-9_\-]{10,}",  # Anthropic
        r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}",  # OpenAI-style
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b",  # GitHub tokens
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
        r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",  # Slack
        r"\bhvs\.[A-Za-z0-9_\-]{20,}",  # Vault service tokens
        r"\bglpat-[A-Za-z0-9_\-]{20,}",  # GitLab
        r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWT
        r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/=._\-]{16,}",  # Authorization values
        r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@",  # user:password@ in URLs
    )
)

_SENSITIVE_WORD = (
    r"(?:password|passwd|passphrase|secret|token|api[_\-]?key|apikey|"
    r"access[_\-]?key|secret[_\-]?key|private[_\-]?key|client[_\-]?secret|credentials?)"
)
_SENSITIVE_KEY = r"[A-Za-z0-9_.\-]*?" + _SENSITIVE_WORD
_KEY = r"(?P<key>[\"']?\b" + _SENSITIVE_KEY + r"[\"']?)"

# Three value shapes after a credential key:
#   "quoted value", spaces and all, up to the closing quote;
#   key: plain YAML value, to the end of the line (a trailing " # comment" kept);
#   KEY=value, env style, up to whitespace.
_QUOTED = re.compile(
    r"(?im)" + _KEY + r"(?P<sep>\s*[:=]\s*)(?P<quote>[\"'])(?P<value>[^\n]*?)(?P=quote)"
)
_COLON_PLAIN = re.compile(
    r"(?im)" + _KEY + r"(?P<sep>\s*:[ \t]*)(?P<value>[^\s\"'#|>{\[][^\n]*?)" r"(?=[ \t]+#|[ \t]*$)"
)
_EQUALS_PLAIN = re.compile(r"(?im)" + _KEY + r"(?P<sep>\s*=\s*)(?P<value>[^\s\"',}#]+)")
_REFERENCE = re.compile(
    r"^(?:\$\{|\$\(|\{\{|<|%\(|\*|\[REDACTED\]|REDACTED$|true$|false$|null$|~$)"
)
_SENSITIVE_KEY_NAME = re.compile(r"(?i)^" + _SENSITIVE_KEY + r"$")


def _keep(value: str) -> bool:
    """Empty values, references and booleans/null are not credentials.

    Length is not a test: ``password: abc`` is a credential however short.
    """
    value = value.strip().strip("\"'")
    return not value or bool(_REFERENCE.match(value))


def _mask(match: re.Match[str]) -> str:
    value = match.group("value")
    if _keep(value):
        return match.group(0)
    quote = match.groupdict().get("quote") or ""
    return f"{match.group('key')}{match.group('sep')}{quote}{REDACTED}{quote}"


def is_sensitive_key(key: object) -> bool:
    """True for a mapping key that names a credential (``password``, ``DB_TOKEN``...)."""
    return isinstance(key, str) and bool(_SENSITIVE_KEY_NAME.match(key.strip("\"' ")))


def _keep_lines(match: re.Match[str]) -> str:
    """Replace a match but keep its newlines, so line numbers stay true."""
    return REDACTED + "\n" * match.group(0).count("\n")


# --- structure-aware passes (line-preserving) -------------------------------

_LINE_INDENT = re.compile(r"^(\s*)")
_BLOCK_START = re.compile(
    r"^(?P<indent>\s*)(?:-\s+)?(?P<key>[\"']?[A-Za-z0-9_.\-]+[\"']?)\s*:\s*[|>][-+0-9]*\s*(?:#.*)?$"
)
_ENV_NAME = re.compile(r"^\s*(?:-\s+)?name:\s*[\"']?(?P<name>[A-Za-z0-9_.\-]+)[\"']?\s*(?:#.*)?$")
_ENV_VALUE = re.compile(r"^(?P<pre>\s*(?:-\s+)?value:\s*)(?P<value>\S.*?)\s*$")
_DOC_SEP = re.compile(r"^---\s*$")
_KIND_SECRET = re.compile(r"^kind:\s*[\"']?Secret[\"']?\s*(?:#.*)?$")
_DATA_SECTION = re.compile(r"^(?P<indent>\s*)(?:data|stringData):\s*(?:#.*)?$")
_CHILD = re.compile(r"^(?P<pre>\s+[\"']?[^\s:#][^:]*?[\"']?\s*:\s*)(?P<value>\S.*?)\s*$")
_JSON_ENV = re.compile(
    r"(?i)(?P<pre>\"name\"\s*:\s*\"(?P<name>[A-Za-z0-9_.\-]+)\"\s*,\s*\"value\"\s*:\s*\")"
    r"(?P<value>[^\"]*)(?P<post>\")"
)


def _indent(line: str) -> int:
    return len(_LINE_INDENT.match(line).group(1))


def _mask_value(prefix: str, value: str) -> str:
    if _keep(value.strip("\"'")):
        return prefix + value
    quote = value[0] if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) > 1 else ""
    return f"{prefix}{quote}{REDACTED}{quote}"


def _mask_block(lines: list[str], start: int, parent_indent: int) -> int:
    """Mask the indented lines of a YAML block that begins after ``start``.

    Returns the index of the first line after the block.
    """
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() and _indent(line) <= parent_indent:
            break
        if line.strip():
            lines[i] = " " * _indent(line) + REDACTED
        i += 1
    return i


def _secret_documents(lines: list[str]) -> set[int]:
    """Indexes of the lines that belong to a ``kind: Secret`` YAML document."""
    secret, doc = set(), []
    for i, line in enumerate(lines + ["---"]):
        if _DOC_SEP.match(line):
            if any(_KIND_SECRET.match(lines[j]) for j in doc):
                secret.update(doc)
            doc = []
        else:
            doc.append(i)
    return secret


def _structured(text: str) -> str:
    lines = text.split("\n")
    secret = _secret_documents(lines)
    i = 0
    while i < len(lines):
        line = lines[i]
        # Every value under a Secret's data/stringData is a credential.
        section = _DATA_SECTION.match(line)
        if section and i in secret:
            parent = len(section.group("indent"))
            j = i + 1
            while j < len(lines):
                child = lines[j]
                if child.strip() and _indent(child) <= parent:
                    break
                block = _BLOCK_START.match(child)
                if block:
                    j = _mask_block(lines, j, _indent(child))
                    continue
                pair = _CHILD.match(child)
                if pair:
                    lines[j] = _mask_value(pair.group("pre"), pair.group("value"))
                j += 1
            i = j
            continue
        # password: |  (or >) followed by an indented block.
        block = _BLOCK_START.match(line)
        if block and is_sensitive_key(block.group("key")):
            i = _mask_block(lines, i, _indent(line))
            continue
        # env: - name: DB_PASSWORD / value: ... (value is the next sibling key).
        env = _ENV_NAME.match(line)
        if env and is_sensitive_key(env.group("name")):
            for j in (i + 1, i + 2, i - 1):
                if 0 <= j < len(lines) and j != i:
                    if j > i and lines[j].lstrip().startswith("- "):
                        break  # the next list item: no value for this name
                    value = _ENV_VALUE.match(lines[j])
                    if value:
                        if value.group("value")[:1] in "|>":
                            # value: |-  (a block): mask every line of it.
                            _mask_block(lines, j, _indent(lines[j]))
                        else:
                            lines[j] = _mask_value(value.group("pre"), value.group("value"))
                        break
        i += 1
    return "\n".join(lines)


def _mask_json_env(match: re.Match[str]) -> str:
    if not is_sensitive_key(match.group("name")) or _keep(match.group("value")):
        return match.group(0)
    return f"{match.group('pre')}{REDACTED}{match.group('post')}"


def _redact_json(text: str) -> str | None:
    """Redact a JSON document structurally; None when ``text`` is not JSON.

    Tool responses and some manifests are JSON, where the YAML passes see one
    long line (and escaped newlines inside strings). Parsing gives every string
    to ``redact`` with its real line structure and lets ``redact_obj`` mask
    Secret data and env pairs by their keys. Unchanged documents keep their
    exact formatting; changed ones are re-serialized in the same layout style.
    """
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    masked = redact_obj(parsed)
    if masked == parsed:
        return text
    indent = 2 if "\n" in stripped else None
    return json.dumps(masked, indent=indent, ensure_ascii=False)


def redact(text: str) -> str:
    """Return ``text`` with anything that looks like a credential replaced.

    Line count is preserved for YAML and plain text, so ``path:line``
    references into the result stay true. A JSON document is redacted
    structurally (see ``_redact_json``).
    """
    if not text:
        return text
    as_json = _redact_json(text)
    if as_json is not None:
        return as_json
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(_keep_lines, text)
    text = _structured(text)
    text = _JSON_ENV.sub(_mask_json_env, text)
    for pattern in (_QUOTED, _COLON_PLAIN, _EQUALS_PLAIN):
        text = pattern.sub(_mask, text)
    return text


def redact_obj(value: Any, *, key: object = None) -> Any:
    """Redact every string inside a JSON-like value (dicts, lists, strings).

    The key a value sits under counts: ``{"password": "hunter2"}`` is masked
    even though the string alone looks harmless.
    """
    sensitive_scalar = isinstance(value, str | int | float) and not isinstance(value, bool)
    if is_sensitive_key(key) and sensitive_scalar:
        return value if isinstance(value, str) and _keep(value) else REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        out = {k: redact_obj(v, key=k) for k, v in value.items()}
        # A Kubernetes Secret: every value under data/stringData is a credential.
        if value.get("kind") == "Secret":
            for section in ("data", "stringData"):
                if isinstance(value.get(section), Mapping):
                    out[section] = {
                        k: v if isinstance(v, str) and _keep(v) else REDACTED
                        for k, v in value[section].items()
                    }
        # {"name": "DB_PASSWORD", "value": "..."}: the env-var shape.
        secret_value = value.get("value")
        if (
            is_sensitive_key(value.get("name"))
            and isinstance(secret_value, str)
            and not _keep(secret_value)
        ):
            out["value"] = REDACTED
        return out
    if isinstance(value, list | tuple):
        return [redact_obj(v, key=key) for v in value]
    return value
