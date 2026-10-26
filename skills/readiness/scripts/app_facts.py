#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts from an exported app-repo tree (Dockerfile, workflows, hygiene files, telemetry deps)."""
from __future__ import annotations

import os
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
# Dockerfiles anywhere in the tree (a Backstage repo keeps one at packages/backend/Dockerfile), but not in
# dependencies, build output or test material, which do not build this app's image.
DOCKERFILE_SKIP_DIRS = frozenset({".git", "node_modules", "vendor", "dist", "build", "testdata", "fixtures",
                                  "__fixtures__", "examples", "test", "tests"})
MAX_DOCKERFILES = 10


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


def _is_dockerfile(name: str) -> bool:
    if name.endswith(".dockerignore"):
        return False
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.lower().endswith(".dockerfile")


def _dockerfiles(root: Path) -> list[str]:
    """Repo-relative Dockerfile paths, the root's first, then sorted; at most MAX_DOCKERFILES."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DOCKERFILE_SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if _is_dockerfile(name) and p.is_file() and not p.is_symlink():
                found.append(p.relative_to(root).as_posix())
    found.sort(key=lambda rel: ("/" in rel, rel))
    return found[:MAX_DOCKERFILES]


def _dockerfile_facts(root: Path) -> list[dict]:
    paths = _dockerfiles(root)
    if not paths:
        return []
    out: list[dict] = [fact("app.dockerfile.files", "app", {"paths": paths}, ", ".join(paths))]
    users: dict[str, str | None] = {}
    n = 0
    for rel in paths:
        froms, users[rel] = _parse_dockerfile(_read(root / rel))
        for lineno, image in froms:
            n += 1
            out.append(fact(f"app.dockerfile.from.{n}", "app",
                            {"image": image, "pinned": bool(_DIGEST.search(image))}, f"{rel}:{lineno}"))
    # The USER of the app's own image: the root Dockerfile's, else the only one's. With several and none at the
    # root, which one builds the deployed image is not knowable here, so none is claimed.
    primary = "Dockerfile" if "Dockerfile" in users else (paths[0] if len(paths) == 1 else None)
    if primary:
        out.append(fact("app.dockerfile.user", "app", {"user": users[primary], "path": primary}, primary))
    return out


def _parse_dockerfile(text: str) -> tuple[list[tuple[int, str]], str | None]:
    """([(line, external base image)], the final stage's USER)."""
    args: dict[str, str] = {}
    aliases: set[str] = set()
    froms: list[tuple[int, str]] = []
    user = None
    stage_users: dict[str, str | None] = {}
    cur_alias = None
    seen_from = False
    for lineno, line in enumerate(text.splitlines(), 1):
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
            user = stage_users.get(image.lower()) if image.lower() in aliases else None
            cur_alias = alias
            if alias:
                stage_users[alias] = user
            if image.lower() in aliases or image == "scratch":
                if alias:
                    aliases.add(alias)
                continue
            if alias:
                aliases.add(alias)
            froms.append((lineno, image))
        elif word == "USER":
            parts = s.split(None, 1)
            user = parts[1].strip() if len(parts) > 1 else None
            if cur_alias:
                stage_users[cur_alias] = user
    return froms, user


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
    refs = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("uses"), str):
            refs.append(job["uses"])
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                refs.append(step["uses"])
    lines = text.splitlines()
    taken: set[int] = set()
    uses = []
    for ref in refs:
        pat = re.compile(r"(?:^\s*-?\s*|[{,]\s*)uses:\s*[\"']?" + re.escape(ref) + r"[\"']?\s*(?:[,}#]|$)")
        line = next((n for n, t in enumerate(lines, 1) if n not in taken and pat.search(t)), 0)
        if line:
            taken.add(line)
        uses.append({"ref": ref, "pinned": _pinned_use(ref), "line": line})
    write_all = perms == "write-all" or any(
        isinstance(j, dict) and j.get("permissions") == "write-all" for j in jobs.values())
    value = {"file": rel, "triggers": _triggers(doc), "permissions": perms,
             "jobs_without_permissions": without, "write_all": write_all,
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
