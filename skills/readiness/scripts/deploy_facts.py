#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: facts from a deploy-repo (GitOps) checkout: the rendered Application, alert rules, registry policy."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

import facts_lib as fl
from readiness_model import fact

ALERT_RULE_FILE = "base-apps/logging/grafana-alerting.yaml"
WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob")
TEXT_SUFFIXES = (".yaml", ".yml", ".md", ".tf")
SKIP_DIRS = {".git", "node_modules", ".terraform"}
TEXT_CAP = 20000
QUERY_CAP = 300
HOST_CAP = 10
_NS_MATCHER = re.compile(r'namespace\s*=~?\s*"')
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")
_MATCHER = re.compile(r'([A-Za-z_]\w*)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"')


def _value_matches(op: str, pattern: str, name: str) -> bool:
    if op == "=":
        return pattern == name
    try:
        return re.fullmatch(pattern, name) is not None
    except re.error:
        return False


def _rule_match(exprs: list[str], namespace: str | None, names: list[str]) -> tuple[bool, bool, bool]:
    """(mentions the app, namespace-filtered, namespace matched). Only positive matchers on quoted values count."""
    ns_seen = ns_hit = value_hit = False
    for e in exprs:
        for key, op, val in _MATCHER.findall(e):
            if op not in ("=", "=~"):
                continue
            if key == "namespace":
                ns_seen = True
                ns_hit = ns_hit or bool(namespace and _value_matches(op, val, namespace))
            else:
                value_hit = value_hit or any(_value_matches(op, val, n) for n in names)
    return ns_hit or value_hit, ns_seen, ns_hit


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _word(name: str) -> str:
    return rf"(?<![\w-]){re.escape(name)}(?![\w-])"


def find_application(root: Path, repo: str, folder: str) -> tuple[str, dict] | None:
    """(file, Application) with a source whose path is `folder` in `repo`."""
    want = folder.rstrip("/")
    for _name, file, app in fl.find_applications(root):
        for src in fl.app_sources(app):
            if (str(src.get("path", "")).rstrip("/") == want and fl.same_repo(src.get("repoURL"), repo)):
                return file, app
    return None


def _evidence(root: Path, file: str, kind: str, name: str) -> str:
    try:
        lines = fl.find_lines(root, file, kind, name)
    except (OSError, UnicodeDecodeError):
        lines = None
    return f"{file}:{lines[0]}-{lines[1]}" if lines else file


def _comment_on_replicas(root: Path, file: str, kind: str, name: str) -> str | None:
    try:
        lines = fl.find_lines(root, file, kind, name)
        if not lines:
            return None
        body = (root / file).read_text().splitlines()[lines[0] - 1:lines[1]]
    except (OSError, UnicodeDecodeError):
        return None
    for text in body:
        m = re.match(r"^\s*replicas:\s*[^#\s]*\s*#\s*(.*\S)", text)
        if m:
            return m.group(1)
    return None


def _res(block) -> dict:
    block = _d(block)
    return {"cpu": block.get("cpu"), "memory": block.get("memory")}


def _container_fact(ref: str, c: dict, init: bool, evidence: str) -> dict:
    sec = _d(c.get("securityContext"))
    image = str(c.get("image", ""))
    res = _d(c.get("resources"))
    value = {
        "workload": ref, "init": init, "image": image, "image_pinned": bool(_DIGEST.search(image)),
        "probes": {k: bool(c.get(f"{k}Probe")) for k in ("readiness", "liveness", "startup")},
        "resources": {"requests": _res(res.get("requests")), "limits": _res(res.get("limits"))},
        "security": {
            "runAsNonRoot": sec.get("runAsNonRoot"), "runAsUser": sec.get("runAsUser"),
            "readOnlyRootFilesystem": sec.get("readOnlyRootFilesystem"),
            "allowPrivilegeEscalation": sec.get("allowPrivilegeEscalation"),
            "capabilities_drop": [str(x) for x in _l(_d(sec.get("capabilities")).get("drop"))],
        },
    }
    return fact(f"deploy.container.{ref}/{c.get('name')}", "deploy", value, evidence)


def _workload_facts(root: Path, doc: dict, file: str) -> list[dict]:
    kind, name = doc["kind"], str(_d(doc.get("metadata")).get("name", "?"))
    ref = f"{kind}/{name}"
    ev = _evidence(root, file, kind, name)
    spec = _d(doc.get("spec"))
    pod, labels = fl.pod_spec(doc)
    template = _d(spec.get("template"))
    if kind == "CronJob":
        template = _d(_d(_d(spec.get("jobTemplate")).get("spec")).get("template"))
    volumes: list[str] = []
    for v in _l(pod.get("volumes")):
        for k in _d(v):
            if k != "name" and k not in volumes:
                volumes.append(k)
    value = {
        "kind": kind, "name": name, "replicas": spec.get("replicas"),
        "replicas_comment": _comment_on_replicas(root, file, kind, name),
        "pod_labels": labels,
        "pod_run_as_non_root": _d(pod.get("securityContext")).get("runAsNonRoot"),
        "pod_run_as_user": _d(pod.get("securityContext")).get("runAsUser"),
        "automount_sa_token": pod.get("automountServiceAccountToken"),
        "service_account": pod.get("serviceAccountName"),
        "pod_annotations": sorted(_d(_d(template.get("metadata")).get("annotations"))),
        "volume_kinds": volumes,
        "volume_claim_templates": len(_l(spec.get("volumeClaimTemplates"))),
    }
    out = [fact(f"deploy.workload.{ref}", "deploy", value, ev)]
    for key, init in (("initContainers", True), ("containers", False)):
        out += [_container_fact(ref, c, init, ev) for c in _l(pod.get(key)) if isinstance(c, dict)]
    return out


def _match_expressions(selector) -> list[dict]:
    """A label selector's matchExpressions as {key, operator, values}; rules.py evaluates them against pod labels."""
    out = []
    for e in map(_d, _l(_d(selector).get("matchExpressions"))):
        key, op = e.get("key"), e.get("operator")
        out.append({"key": None if key is None else str(key), "operator": None if op is None else str(op),
                    "values": [str(v) for v in _l(e.get("values"))]})
    return out


def _object_value(doc: dict) -> dict | None:
    kind, spec = doc["kind"], _d(doc.get("spec"))
    name = str(_d(doc.get("metadata")).get("name", "?"))
    if kind == "NetworkPolicy":
        sel = _d(spec.get("podSelector"))
        return {"pod_selector": _d(sel.get("matchLabels")), "match_expressions": _match_expressions(sel)}
    if kind == "PodDisruptionBudget":
        sel = _d(spec.get("selector"))
        return {"selector": _d(sel.get("matchLabels")), "match_expressions": _match_expressions(sel)}
    if kind == "HorizontalPodAutoscaler":
        t = _d(spec.get("scaleTargetRef"))
        return {"target": f"{t.get('kind')}/{t.get('name')}", "min": spec.get("minReplicas"),
                "max": spec.get("maxReplicas")}
    if kind == "Secret":
        keys = sorted({*_d(doc.get("data")), *_d(doc.get("stringData"))})
        return {"keys": keys, "has_data": bool(keys)}  # key names only, never values
    if kind == "ExternalSecret":
        keys = [str(d["secretKey"]) for d in _l(spec.get("data")) if isinstance(d, dict) and d.get("secretKey")]
        return {"target": _d(spec.get("target")).get("name", name), "keys": keys}
    if kind == "HTTPRoute":
        backends: list[str] = []
        for rule in _l(spec.get("rules")):
            for b in _l(_d(rule).get("backendRefs")):
                if _d(b).get("name") and b["name"] not in backends:
                    backends.append(str(b["name"]))
        return {"hostnames": [str(h) for h in _l(spec.get("hostnames"))], "backends": backends}
    if kind == "AuthorizationPolicy":
        return {"action": spec.get("action"), "selector": _d(_d(spec.get("selector")).get("matchLabels"))}
    if kind == "Service":
        return {"selector": _d(spec.get("selector")), "ports": _l(spec.get("ports"))}
    if kind == "PersistentVolumeClaim":
        return {"size": _d(_d(spec.get("resources")).get("requests")).get("storage")}
    return None


def _alert_facts(root: Path, namespace: str | None, names: list[str]) -> list[dict]:
    """`deploy.alert_source` (was the rule file there and readable, how many rules it held and kept), then one
    `deploy.alert_rule.<uid>` per kept rule. `parsed` is true only when the file and every ConfigMap data blob
    load as YAML and at least one blob holds Grafana rule `groups`: anything else is "could not read the rules",
    never "there are no rules"."""
    file = ALERT_RULE_FILE
    p = root / file
    source = {"file": file, "exists": p.is_file(), "parsed": False, "rules_total": 0, "rules_kept": 0}
    rules: list[dict] = []
    try:
        text = p.read_text() if source["exists"] else ""
        docs = fl.load_docs(text) if source["exists"] else []
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        docs = None
    lines = text.splitlines() if docs else []
    blobs_ok, groups_seen = docs is not None, False
    for doc in docs or []:
        if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
            continue
        for blob in _d(doc.get("data")).values():
            if not isinstance(blob, str):
                continue
            try:
                parsed = yaml.safe_load(blob)
            except yaml.YAMLError:
                blobs_ok = False
                continue
            groups = _d(parsed).get("groups")
            groups_seen = groups_seen or isinstance(groups, list)
            for group in _l(groups):
                for rule in map(_d, _l(_d(group).get("rules"))):
                    source["rules_total"] += 1
                    exprs = [str(_d(_d(d).get("model")).get("expr")) for d in _l(rule.get("data"))
                             if _d(_d(d).get("model")).get("expr")]
                    mentions, filtered, ns_hit = _rule_match(exprs, namespace, names)
                    if not rule.get("uid") or (filtered and not ns_hit):
                        continue  # a rule scoped only to other namespaces says nothing about this app
                    uid = str(rule["uid"])
                    line = next((i for i, t in enumerate(lines, 1)
                                 if re.search(rf"uid:\s*{re.escape(uid)}\s*$", t)), 1)
                    value = {"uid": uid, "title": str(rule.get("title", "")),
                             "queries": [e[:QUERY_CAP] for e in exprs],
                             "mentions_app": mentions, "namespace_filtered": filtered}
                    rules.append(fact(f"deploy.alert_rule.{uid}", "deploy", value, f"{file}:{line}"))
    source.update(parsed=bool(source["exists"] and blobs_ok and groups_seen), rules_kept=len(rules))
    return [fact("deploy.alert_source", "deploy", source, file)] + rules


def _repo_names(images: list[str]) -> list[str]:
    names: list[str] = []
    for image in images:
        ref = image.split("@")[0]
        if "/" not in ref:
            continue
        last = ref.rsplit("/", 1)[1].split(":")[0]
        if last and last not in names:
            names.append(last)
    return names


def _registry_facts(root: Path, images: list[str]) -> list[dict]:
    names = _repo_names(images)
    out: list[dict] = []
    for f in sorted(root.rglob("*.tf")):
        rel = str(f.relative_to(root))
        if SKIP_DIRS & set(f.relative_to(root).parts) or not f.is_file():
            continue
        text = f.read_text(errors="replace")
        for m in re.finditer(r'^resource\s+"aws_ecr_lifecycle_policy"\s+"([^"]+)"\s*\{(.*?)^\}', text, re.M | re.S):
            hit = next((n for n in names if re.search(_word(n), m.group(2))), None)
            if hit is None:
                continue
            line = text.count("\n", 0, m.start()) + 1
            out.append(fact(f"deploy.registry.{len(out)}", "deploy",
                            {"file": rel, "line": line, "address": f"aws_ecr_lifecycle_policy.{m.group(1)}",
                             "repository": hit}, f"{rel}:{line}"))
    return out


def _host_facts(root: Path, folder: str, hosts: list[str]) -> list[dict]:
    prefix = folder + "/"
    files = [f for f in sorted(root.rglob("*")) if f.suffix in TEXT_SUFFIXES and f.is_file()
             and not SKIP_DIRS & set(f.relative_to(root).parts)
             and not str(f.relative_to(root)).startswith(prefix)]
    out = []
    for host in hosts:
        hits: list[dict] = []
        for f in files:
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if host in line and len(hits) < HOST_CAP:
                    hits.append({"file": str(f.relative_to(root)), "line": i, "text": line.strip()[:160]})
        ev = f"{hits[0]['file']}:{hits[0]['line']}" if hits else "repo scan"
        out.append(fact(f"deploy.host_mentions.{host}", "deploy", hits, ev))
    return out


def deploy_facts(root: Path, repo: str, folder: str, work: Path, namespace: str | None = None) -> list[dict]:
    """`namespace` scopes the alert rules when no Application gives one (ApplicationSet-generated apps have no
    hand-written Application); the Application's destination namespace wins when present."""
    folder = folder.rstrip("/")
    found = find_application(root, repo, folder)
    notes: list[str] = []
    docs: list[tuple[dict, str]] = []
    opts: dict = {}
    if found is None:
        render = "no-application"
        notes.append(f"no Argo CD Application with a source path {folder} in {repo}")
    else:
        file, app = found
        opts = next((_d(s.get("directory")) for s in fl.app_sources(app)
                     if str(s.get("path", "")).rstrip("/") == folder), {})
        try:
            docs, _loaded, rnotes = fl.render_app(root, file, app, work, repo)
            notes += rnotes
            render = "rendered"
        except Exception as err:  # any render failure (yaml, os, helm subprocess) falls back to the raw folder
            notes.append(f"render failed: {err}")
            render = "raw-fallback"
    if render != "rendered":
        try:
            docs, _ = fl.dir_manifests(root, {"path": folder, "directory": opts})
        except (RuntimeError, OSError) as err:
            notes.append(f"raw folder unreadable: {err}")

    out: list[dict] = []
    if found:
        app = found[1]
        name = str(app["metadata"]["name"])
        src = next(s for s in fl.app_sources(app) if str(s.get("path", "")).rstrip("/") == folder)
        value = {"file": found[0], "name": name,
                 "namespace": _d(_d(app.get("spec")).get("destination")).get("namespace"),
                 "target_revision": src.get("targetRevision"), "path": folder, "render": render, "notes": notes}
        out.append(fact("deploy.application", "deploy", value, _evidence(root, found[0], "Application", name)))
    else:
        value = {"file": None, "name": None, "namespace": None, "target_revision": None,
                 "path": folder, "render": render, "notes": notes}
        out.append(fact("deploy.application", "deploy", value, folder))

    seen: set[str] = set()
    hosts: list[str] = []
    for doc, file in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("kind"), str):
            continue
        kind, name = doc["kind"], str(_d(doc.get("metadata")).get("name", "?"))
        if f"{kind}/{name}" in seen:
            continue
        if kind in WORKLOAD_KINDS:
            seen.add(f"{kind}/{name}")
            out += _workload_facts(root, doc, file)
            continue
        obj = _object_value(doc)
        if obj is not None:
            seen.add(f"{kind}/{name}")
            out.append(fact(f"deploy.object.{kind}/{name}", "deploy", obj, _evidence(root, file, kind, name)))
            hosts += [h for h in _l(obj.get("hostnames")) if h not in hosts]

    for key, fname in (("runbook", "runbook.md"), ("docs", "docs.md")):
        rel = f"{folder}/{fname}"
        exists = (root / rel).is_file()
        out.append(fact(f"deploy.file.{key}", "deploy", {"exists": exists, "path": rel}, rel))
        if exists:
            text = (root / rel).read_text(errors="replace")[:TEXT_CAP]
            out.append(fact(f"deploy.text.{rel}", "deploy", {"text": text}, rel))

    out += _alert_facts(root, namespace_of(out) or namespace, [r.split("/", 1)[1] for r in workload_refs(out)])
    out += _registry_facts(root, image_refs(out))
    out += _host_facts(root, folder, hosts)
    return out


def workload_refs(facts: list[dict]) -> list[str]:
    return [f["id"][len("deploy.workload."):] for f in facts if f["id"].startswith("deploy.workload.")]


def image_refs(facts: list[dict]) -> list[str]:
    out: list[str] = []
    for f in facts:
        if f["id"].startswith("deploy.container.") and f["value"]["image"] not in out:
            out.append(f["value"]["image"])
    return out


def namespace_of(facts: list[dict]) -> str | None:
    for f in facts:
        if f["id"] == "deploy.application":
            return f["value"].get("namespace")
    return None
