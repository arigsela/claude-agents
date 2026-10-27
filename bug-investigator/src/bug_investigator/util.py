"""Small shared helpers: running commands, times, secret scrubbing."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], str]


class CommandError(RuntimeError):
    pass


def run(cmd: Sequence[str], cwd: str | None = None, timeout: int = 60) -> str:
    """Run a command and return stdout; raise CommandError on a non-zero exit."""
    try:
        r = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CommandError(f"{cmd[0]}: {e}") from e
    if r.returncode != 0:
        raise CommandError(f"{' '.join(cmd[:4])}: exit {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout


def run_json(runner: Runner, cmd: Sequence[str]):
    out = runner(cmd)
    return json.loads(out) if out.strip() else None


def parse_time(s) -> datetime | None:
    """RFC 3339 / ISO 8601 to an aware UTC datetime; None if it does not parse."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace(" ", "T", 1)
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    t = re.sub(r"(\.\d{6})\d+", r"\1", t)  # Python <3.11 accepts at most microseconds
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def window(start: datetime | None, end: datetime | None, fallback: datetime | None,
           pad: timedelta = timedelta(hours=2), cap: timedelta = timedelta(hours=24)) -> tuple[datetime, datetime]:
    """A query window: the given one, else fallback ±pad; never longer than cap, never in the future."""
    now = utc_now()
    if start is None and end is None:
        center = fallback or now
        start, end = center - pad, center + pad
    elif start is None:
        start = end - pad
    elif end is None:
        end = start + pad
    if end > now:
        end = now
    if start >= end:
        start = end - pad
    if end - start > cap:
        start = end - cap
    return start, end


# ---------------------------------------------------------------------------------- scrub

_SECRET_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bglsa_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
_LONG_BLOB = re.compile(r"[A-Za-z0-9+/_-]{41,}={0,2}")
_HEX = re.compile(r"[0-9a-fA-F]+")


def scrub_text(s: str, extra: Sequence[str] = ()) -> str:
    for secret in extra:
        if secret and len(secret) >= 8:
            s = s.replace(secret, "[redacted]")
    for p in _SECRET_PATTERNS:
        s = p.sub("[redacted]", s)

    def blob(m: re.Match) -> str:
        v = m.group(0)
        if _HEX.fullmatch(v) or "/" in v.strip("/") and v.count("/") >= 2 and not v.endswith("="):
            return v  # commit SHAs and paths stay
        if not (re.search(r"[A-Z]", v) and re.search(r"[a-z]", v) and re.search(r"[0-9]", v)):
            return v  # long identifiers (snake_case metric names) stay
        return "[redacted]"

    return _LONG_BLOB.sub(blob, s)


def scrub(obj, extra: Sequence[str] = ()):
    """Scrub secrets from every string in a JSON-like value."""
    if isinstance(obj, str):
        return scrub_text(obj, extra)
    if isinstance(obj, list):
        return [scrub(x, extra) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v, extra) for k, v in obj.items()}
    return obj


def read_secret(path: str | None) -> str:
    if not path or not os.path.isfile(path):
        return ""
    with open(path) as f:
        return f.read().strip()


def write_json(path: str, data) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def read_json(path: str):
    with open(path) as f:
        return json.load(f)
