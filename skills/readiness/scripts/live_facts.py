#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: live facts from kubectl (get, top) and gh (api, GET only). Read-only; fails soft."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from readiness_model import fact  # noqa: E402

Run = Callable[[list[str]], tuple[int, str, str]]

TIMEOUT_S = 20


def subprocess_run(argv: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S)
    except FileNotFoundError:
        return 127, "", "not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {TIMEOUT_S}s"
    return p.returncode, p.stdout, p.stderr


def parse_quantity_cpu(s: str) -> int:
    s = s.strip()
    if s.endswith("m"):
        return int(float(s[:-1]))
    return int(float(s) * 1000)


_MEM_MI = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024,
           "k": 1000 / 1048576, "M": 1e6 / 1048576, "G": 1e9 / 1048576}


def parse_quantity_mem(s: str) -> int:
    s = s.strip()
    m = re.fullmatch(r"([0-9.]+)([A-Za-z]*)", s)
    if not m:
        raise ValueError(f"unreadable memory quantity: {s!r}")
    num, unit = float(m.group(1)), m.group(2)
    if unit == "":
        return int(num / 1048576)
    if unit not in _MEM_MI:
        raise ValueError(f"unknown memory unit: {unit!r}")
    return int(num * _MEM_MI[unit])


def pod_workload(pod: dict) -> str | None:
    meta = pod.get("metadata") or {}
    for o in meta.get("ownerReferences") or []:
        kind, name = o.get("kind"), o.get("name") or ""
        if kind == "StatefulSet":
            return f"StatefulSet/{name}"
        if kind == "ReplicaSet":
            h = (meta.get("labels") or {}).get("pod-template-hash")
            suffix = f"-{h}" if h else None
            if suffix and name.endswith(suffix) and len(name) > len(suffix):
                return f"Deployment/{name[:-len(suffix)]}"
    return None


def _cmd(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def _reason(rc: int, err: str, tool: str) -> str:
    if rc == 127:
        return f"unavailable: {tool} not installed"
    lines = [ln.strip() for ln in (err or "").splitlines() if ln.strip()]
    return f"unavailable: {lines[0] if lines else f'exit {rc}'}"


def cluster_facts(namespace: str, workloads: list[str], run: Run = subprocess_run) -> tuple[list[dict], str]:
    get = ["kubectl", "get", "deploy,statefulset,pods", "-n", namespace, "-o", "json", "--request-timeout=5s"]
    top = ["kubectl", "top", "pods", "-n", namespace, "--containers", "--no-headers", "--request-timeout=5s"]
    get_cmd, top_cmd = _cmd(get), _cmd(top)
    rc, out, err = run(get)
    if rc != 0:
        return [], _reason(rc, err, "kubectl")
    try:
        items = json.loads(out).get("items") or []
        if not isinstance(items, list):
            raise ValueError("items is not a list")
    except (ValueError, AttributeError) as e:
        return [], f"unavailable: unreadable kubectl output ({e})"

    wanted = set(workloads)
    facts: list[dict] = []
    present = {}
    for it in items:
        if not isinstance(it, dict) or it.get("kind") not in ("Deployment", "StatefulSet"):
            continue
        present[f"{it['kind']}/{(it.get('metadata') or {}).get('name')}"] = it
    for w in workloads:
        it = present.get(w)
        if it is None:
            value = {"found": False, "ready": 0, "desired": 0}
        else:
            desired = (it.get("spec") or {}).get("replicas")
            value = {"found": True, "ready": int((it.get("status") or {}).get("readyReplicas") or 0),
                     "desired": 1 if desired is None else int(desired)}
        facts.append(fact(f"cluster.workload.{w}", "cluster", value, get_cmd))

    pod_to_wl: dict[str, str] = {}
    for it in items:
        if not isinstance(it, dict) or it.get("kind") != "Pod":
            continue
        wl = pod_workload(it)
        if wl not in wanted:
            continue
        name = (it.get("metadata") or {}).get("name")
        pod_to_wl[name] = wl
        css = (it.get("status") or {}).get("containerStatuses") or []
        restarts = sum(int(c.get("restartCount") or 0) for c in css)
        oom = any((((c.get("lastState") or {}).get("terminated") or {}).get("reason")) == "OOMKilled"
                  for c in css)
        facts.append(fact(f"cluster.pod.{name}", "cluster",
                          {"workload": wl, "restarts": restarts, "oom_killed": oom,
                           "phase": (it.get("status") or {}).get("phase")}, get_cmd))

    trc, tout, _ = run(top)
    if trc == 0:
        usage: dict[str, dict] = {}
        for line in tout.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0] not in pod_to_wl:
                continue
            try:
                cpu, mem = parse_quantity_cpu(parts[2]), parse_quantity_mem(parts[3])
            except ValueError:
                continue
            u = usage.setdefault(f"{pod_to_wl[parts[0]]}/{parts[1]}", {"cpu_m": 0, "memory_mi": 0})
            u["cpu_m"], u["memory_mi"] = max(u["cpu_m"], cpu), max(u["memory_mi"], mem)
        for k, v in usage.items():
            facts.append(fact(f"cluster.usage.{k}", "cluster", v, top_cmd))
    return facts, "ok"


def _gh_code(rc: int, out: str) -> int:
    m = re.match(r"HTTP/\S+\s+(\d{3})", out or "")
    return int(m.group(1)) if m else 0


def github_facts(slug: str, default_branch: str | None, run: Run = subprocess_run) -> tuple[list[dict], str]:
    facts: list[dict] = []
    status = "ok"

    def call(path: str) -> tuple[int, str, str]:
        argv = ["gh", "api", "-i", path]
        rc, out, err = run(argv)
        return _gh_code(rc, out), _cmd(argv), (rc, err)

    pcode, pcmd, (prc, perr) = call(f"repos/{slug}")
    if pcode == 0 and prc != 0:
        return [], _reason(prc, perr, "gh")
    if pcode != 200:
        return [fact("github.dependabot_alerts", "github", {"enabled": None, "http": pcode}, pcmd),
                fact("github.branch_protection", "github", {"protected": None, "http": pcode}, pcmd)], \
            f"unavailable: repo not readable (HTTP {pcode})"

    code, cmd, _ = call(f"repos/{slug}/vulnerability-alerts")
    facts.append(fact("github.dependabot_alerts", "github",
                      {"enabled": True if code == 204 else False if code == 404 else None, "http": code}, cmd))

    if default_branch is None:
        facts.append(fact("github.branch_protection", "github", {"protected": None, "http": 0},
                          "skipped: default branch unknown"))
    else:
        code, cmd, _ = call(f"repos/{slug}/branches/{default_branch}/protection")
        facts.append(fact("github.branch_protection", "github",
                          {"protected": True if code == 200 else False if code == 404 else None, "http": code},
                          cmd))
    return facts, status
