#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts from an exported app-repo tree (Dockerfile, workflows, hygiene files, telemetry deps)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from readiness_model import fact

FILE_KEYS: dict[str, list[str]] = {
    "readme": ["README.md", "README"],
    "codeowners": ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"],
    "security": ["SECURITY.md", ".github/SECURITY.md"],
    "dependabot": [".github/dependabot.yml", ".github/dependabot.yaml"],
    "renovate": ["renovate.json", "renovate.json5", ".github/renovate.json"],
    "tests_dir": ["tests", "test", "__tests__"],
}

TELEMETRY_MARKERS = ("opentelemetry", "prometheus_client", "prometheus-client", "prom-client",
                     "micrometer", "go.opentelemetry.io", "structlog")
TELEMETRY_FILES = ("pyproject.toml", "uv.lock", "requirements*.txt", "package.json", "go.mod")
_TOKEN = re.compile(r"[A-Za-z0-9_.@/\-]*(?:%s)[A-Za-z0-9_.@/\-]*" % "|".join(re.escape(m) for m in TELEMETRY_MARKERS))

_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")
_SHA40 = re.compile(r"@[0-9a-f]{40}$")
README_CAP = 20000
RUN_CAP = 120


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def _file_facts(root: Path) -> list[dict]:
    out = []
    for key, paths in FILE_KEYS.items():
        want_dir = key == "tests_dir"
        hit = next((p for p in paths if ((root / p).is_dir() if want_dir else (root / p).is_file())), None)
        value = {"exists": hit is not None, "path": hit, "searched": list(paths)}
        out.append(fact(f"app.file.{key}", "app", value, hit or ", ".join(paths)))
    return out


def _expand(text: str, args: dict[str, str]) -> str:
    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}|\$(\w+)",
                  lambda m: args.get(m.group(1) or m.group(3), m.group(2) if m.group(2) is not None else m.group(0)),
                  text)


def _dockerfile_facts(root: Path) -> list[dict]:
    path = root / "Dockerfile"
    if not path.is_file():
        return []
    args: dict[str, str] = {}
    aliases: set[str] = set()
    out: list[dict] = []
    user = None
    seen_from = False
    n = 0
    for lineno, line in enumerate(_read(path).splitlines(), 1):
        s = line.strip()
        word = s.split(None, 1)[0].upper() if s and not s.startswith("#") else ""
        if word == "ARG" and not seen_from:
            m = re.match(r"ARG\s+(\w+)=(\S+)", s, re.I)
            if m:
                args[m.group(1)] = m.group(2).strip("\"'")
        elif word == "FROM":
            seen_from = True
            toks = [t for t in s.split()[1:] if not t.startswith("--")]
            if not toks:
                continue
            image = _expand(toks[0], args)
            if len(toks) >= 3 and toks[1].upper() == "AS":
                alias = toks[2].lower()
            else:
                alias = None
            if image.lower() in aliases or image == "scratch":
                if alias:
                    aliases.add(alias)
                continue
            if alias:
                aliases.add(alias)
            n += 1
            out.append(fact(f"app.dockerfile.from.{n}", "app",
                            {"image": image, "pinned": bool(_DIGEST.search(image))}, f"Dockerfile:{lineno}"))
        elif word == "USER":
            parts = s.split(None, 1)
            user = parts[1].strip() if len(parts) > 1 else None
    out.append(fact("app.dockerfile.user", "app", {"user": user}, "Dockerfile"))
    return out


def _triggers(doc: dict) -> list[str]:
    on = doc.get("on", doc.get(True))  # PyYAML parses a bare `on:` key as True
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(x) for x in on]
    if isinstance(on, dict):
        return [str(k) for k in on]
    return []


def _pinned_use(ref: str) -> bool:
    if ref.startswith("./"):
        return True
    if ref.startswith("docker://"):
        return bool(_DIGEST.search(ref))
    return bool(_SHA40.search(ref))


_USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\"[^\"]*\"|'[^']*'|[^\s#]+)")


def _workflow_fact(root: Path, p: Path) -> dict:
    rel = p.relative_to(root).as_posix()
    text = _read(p)
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        doc = None
    if not isinstance(doc, dict):
        doc = {}
    perms = doc.get("permissions")
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    without = [] if perms is not None else [
        str(name) for name, job in jobs.items() if not isinstance(job, dict) or "permissions" not in job]
    runs = []
    for job in jobs.values():
        for step in (job.get("steps") or []) if isinstance(job, dict) else []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"].strip().splitlines()[0][:RUN_CAP] if step["run"].strip() else "")
    uses = []
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _USES_LINE.match(line)
        if m:
            ref = m.group("ref").strip("\"'")
            uses.append({"ref": ref, "pinned": _pinned_use(ref), "line": lineno})
    value = {"file": rel, "triggers": _triggers(doc), "permissions": perms,
             "jobs_without_permissions": without, "write_all": perms == "write-all",
             "run_steps": runs, "uses": uses}
    return fact(f"app.workflow.{p.stem}", "app", value, rel)


def _workflow_facts(root: Path) -> list[dict]:
    d = root / ".github" / "workflows"
    if not d.is_dir():
        return []
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix in (".yml", ".yaml"))
    return [_workflow_fact(root, p) for p in files]


def _telemetry_fact(root: Path) -> dict:
    found: set[str] = set()
    files: list[str] = []
    for pattern in TELEMETRY_FILES:
        for p in sorted(root.glob(pattern)):
            if not p.is_file():
                continue
            hits = set(_TOKEN.findall(_read(p)))
            if hits:
                found |= hits
                files.append(p.name)
    return fact("app.deps.telemetry", "app", {"found": sorted(found), "files": files},
                ", ".join(files) if files else ", ".join(TELEMETRY_FILES))


def _text_facts(root: Path) -> list[dict]:
    p = root / "README.md"
    if not p.is_file():
        return []
    return [fact("app.text.README.md", "app", {"text": _read(p)[:README_CAP]}, "README.md")]


def app_facts(root: Path) -> list[dict]:
    root = Path(root)
    return (_file_facts(root) + _dockerfile_facts(root) + _workflow_facts(root)
            + [_telemetry_fact(root)] + _text_facts(root))
