#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""pr-explainer: collect deterministic facts about a PR into <out>/facts.json and <out>/diff.patch.

Usage: collect.py --pr N [--repo owner/name] --out DIR   (run inside a checkout of the repo)
Needs gh and git. Uses helm for Helm-sourced apps and `kubectl kustomize` for kustomize apps;
when either is missing or fails, that app falls back to render=source-diff (spec §6.2).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pathspec
import yaml

POLICY_PATH = ".github/review-policy.yaml"
MANIFEST_SUFFIXES = (".yaml", ".yml", ".json")
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Rollout", "Job", "CronJob"}
CLUSTER_SCOPED = {
    "Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition", "StorageClass",
    "PersistentVolume", "PriorityClass", "ClusterIssuer", "ClusterSecretStore", "IngressClass",
    "GatewayClass", "APIService", "RuntimeClass", "ValidatingAdmissionPolicy",
    "ValidatingAdmissionPolicyBinding", "MutatingAdmissionPolicy", "MutatingAdmissionPolicyBinding",
    "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration",
}
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
ATLANTIS_RE = re.compile(r"^\s*# (\S+) (will be created|will be updated in-place|must be replaced|"
                         r"will be destroyed|will be read during apply)", re.M)
TF_ACTIONS = {"will be created": "create", "will be updated in-place": "update", "must be replaced": "replace",
              "will be destroyed": "destroy", "will be read during apply": "read"}
TRIAGE_RE = re.compile(r"<!-- pr-triage -->\s*\n###\s*\S+\s*(review:\w+)\s*\n\*\*Why:\*\*\s*(.*)")
MAX_CHANGED_PATHS = 10
MAX_HITS_PER_APP_RULE = 5


def sh(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}…: {proc.stderr.strip()[:400]}")
    return proc.stdout


def gh_pages(path: str) -> list[dict]:
    return [item for page in json.loads(sh("gh", "api", "--paginate", "--slurp", path)) for item in page]


def repo_from_origin() -> str:
    url = sh("git", "remote", "get-url", "origin").strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        sys.exit(f"collect: cannot derive owner/repo from origin {url!r}; pass --repo")
    return m.group(1)


class Trees:
    """Detached worktrees of the PR's base and head commits."""

    def __init__(self, pr: int, base_sha: str, head_sha: str):
        sh("git", "fetch", "--quiet", "origin", f"pull/{pr}/head", base_sha)
        self.merge_base = sh("git", "merge-base", base_sha, head_sha).strip()
        self.dir = Path(tempfile.mkdtemp(prefix="pr-explainer-"))
        self.base, self.head = self.dir / "base", self.dir / "head"
        try:
            sh("git", "worktree", "add", "--detach", "--quiet", str(self.base), self.merge_base)
            sh("git", "worktree", "add", "--detach", "--quiet", str(self.head), head_sha)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for tree in (self.base, self.head):
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], capture_output=True)


def load_docs(text: str) -> list[dict]:
    docs = []
    for d in yaml.safe_load_all(text):
        if not isinstance(d, dict):
            continue
        if d.get("kind") == "List":
            docs += [i for i in d.get("items") or [] if isinstance(i, dict) and i.get("kind")]
        elif d.get("kind"):
            docs.append(d)
    return docs


def applications(root: Path) -> dict[str, tuple[str, dict]]:
    """Application name -> (repo-relative file, doc) for base-apps/*.yaml in a worktree."""
    apps: dict[str, tuple[str, dict]] = {}
    for f in sorted((root / "base-apps").glob("*.y*ml")):
        try:
            docs = load_docs(f.read_text())
        except yaml.YAMLError:
            continue
        for d in docs:
            if d.get("kind") == "Application":
                apps[d["metadata"]["name"]] = (str(f.relative_to(root)), d)
    return apps


def source_kind(root: Path, app: dict) -> str:
    src = app["spec"].get("source") or {}
    if src.get("chart"):
        return "helm"
    path = src.get("path")
    if not path:
        return "unknown"
    d = root / path
    if (d / "Chart.yaml").exists():
        return "helm-local"
    if any((d / k).exists() for k in ("kustomization.yaml", "kustomization.yml", "Kustomization")):
        return "kustomize"
    return "directory"


def expand_braces(pattern: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    return [p for alt in m.group(1).split(",")
            for p in expand_braces(pattern[:m.start()] + alt + pattern[m.end():])]


def dir_manifests(root: Path, app: dict) -> tuple[list[tuple[dict, str]], set[str]]:
    src = app["spec"]["source"]
    base = root / src["path"]
    opts = src.get("directory") or {}
    candidates = base.rglob("*") if opts.get("recurse") else base.glob("*")
    include = expand_braces(opts["include"]) if opts.get("include") else None
    exclude = expand_braces(opts["exclude"]) if opts.get("exclude") else []
    out: list[tuple[dict, str]] = []
    loaded: set[str] = set()
    for f in sorted(candidates):
        if not f.is_file() or f.suffix not in MANIFEST_SUFFIXES:
            continue
        rel = str(f.relative_to(base))
        if include and not any(fnmatch.fnmatch(rel, p) for p in include):
            continue
        if any(fnmatch.fnmatch(rel, p) for p in exclude):
            continue
        try:
            docs = [json.loads(f.read_text())] if f.suffix == ".json" else load_docs(f.read_text())
        except (yaml.YAMLError, json.JSONDecodeError) as err:
            raise RuntimeError(f"invalid YAML: {f.relative_to(root)}: {str(err).splitlines()[0]}")
        loaded.add(str(f.relative_to(root)))
        out += [(d, str(f.relative_to(root))) for d in docs if isinstance(d, dict) and d.get("kind")]
    return out, loaded


def helm_docs(root: Path, app: dict, work: Path) -> list[dict]:
    helm = os.environ.get("HELM_BIN", "helm")  # HELM_BIN=/nonexistent simulates a missing helm
    if not shutil.which(helm):
        raise RuntimeError("helm not installed (brew install helm)")
    spec = app["spec"]
    src = spec["source"]
    h = src.get("helm") or {}
    name = h.get("releaseName") or app["metadata"]["name"]
    ns = (spec.get("destination") or {}).get("namespace") or "default"
    if src.get("chart"):
        repo = src["repoURL"]
        chart = ([src["chart"], "--repo", repo] if repo.startswith(("http://", "https://"))
                 else [f"oci://{repo.rstrip('/')}/{src['chart']}"])
        chart += ["--version", str(src["targetRevision"])]
    else:
        chart = [str(root / src["path"])]
    cmd = [helm, "template", name, *chart, "--namespace", ns]
    if not h.get("skipCrds"):
        cmd.append("--include-crds")
    for vf in h.get("valueFiles") or []:
        if src.get("path"):
            cmd += ["-f", str(root / src["path"] / vf)]
    for key in ("values", "valuesObject"):
        if h.get(key):
            value = h[key] if isinstance(h[key], str) else yaml.safe_dump(h[key])
            tmp = tempfile.NamedTemporaryFile("w", dir=work, suffix=".yaml", delete=False)
            tmp.write(value)
            tmp.close()
            cmd += ["-f", tmp.name]
    for prm in h.get("parameters") or []:
        cmd += ["--set-string" if prm.get("forceString") else "--set", f"{prm['name']}={prm['value']}"]
    return load_docs(sh(*cmd))


def render_app(root: Path, app_file: str, app: dict, work: Path,
               repo: str) -> tuple[list[tuple[dict, str]], set[str] | None, list[str]]:
    """Returns (docs with their source file, files actually loaded or None for 'all', render notes)."""
    src = app["spec"].get("source") or {}
    if not src.get("chart") and src.get("path"):
        url = (src.get("repoURL") or "").lower().rstrip("/")
        url = url[:-4] if url.endswith(".git") else url
        if url and repo.lower() not in url:
            raise RuntimeError("source is another repository")
        if not (root / src["path"]).is_dir():
            raise RuntimeError("source path missing")
    kind = source_kind(root, app)
    if kind == "directory":
        docs, loaded = dir_manifests(root, app)
        return docs, loaded, []
    if kind == "kustomize":
        if not shutil.which("kubectl"):
            raise RuntimeError("kubectl not installed")
        return [(d, src["path"]) for d in load_docs(sh("kubectl", "kustomize", str(root / src["path"])))], None, []
    if kind in ("helm", "helm-local"):
        notes = []
        if (src.get("helm") or {}).get("valueFiles") and not src.get("path"):
            notes.append("valueFiles not applied (chart-repo source)")
        return [(d, app_file) for d in helm_docs(root, app, work)], None, notes
    raise RuntimeError(f"unsupported Application source ({kind})")


def res_key(doc: dict, default_ns: str) -> tuple[str, str, str]:
    md = doc.get("metadata")
    md = md if isinstance(md, dict) else {}
    ns = "" if doc.get("kind") in CLUSTER_SCOPED else (md.get("namespace") or default_ns)
    return (str(doc.get("kind")), ns, str(md.get("name", "?")))


def diff_paths(a, b, prefix: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b), key=str):
            out += diff_paths(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f"{prefix}[{i}]")
        return out
    return [] if a == b else [prefix or "."]


def find_lines(root: Path, file: str | None, kind: str, name: str) -> list[int] | None:
    p = root / file if file else None
    if not p or not p.is_file() or p.suffix not in (".yaml", ".yml"):
        return None
    lines = p.read_text().splitlines()
    start, seen_kind, seen_name = 1, None, None
    for i, line in enumerate(lines + ["---"], start=1):
        if line.startswith("---"):
            if seen_kind == kind and seen_name == name:
                return [start, i - 1]
            start, seen_kind, seen_name = i + 1, None, None
        elif line.startswith("kind:"):
            seen_kind = line.split(":", 1)[1].strip()
        elif seen_name is None and re.match(r"^  name:\s*\S", line):
            seen_name = line.split(":", 1)[1].strip().strip("'\"")
    return None


def _d(value) -> dict:
    return value if isinstance(value, dict) else {}


def pod_spec(doc: dict) -> tuple[dict, dict]:
    spec = _d(doc.get("spec"))
    if doc.get("kind") == "CronJob":
        spec = _d(_d(spec.get("jobTemplate")).get("spec"))
    template = _d(spec.get("template"))
    return _d(template.get("spec")), _d(_d(template.get("metadata")).get("labels"))


def build_edges(docs: dict[tuple, dict]) -> list[tuple[tuple, tuple, str]]:
    """Deterministic relationships only (spec §6.2). The model never adds edges."""
    by_kind_name: dict[tuple[str, str], list[tuple]] = {}
    for k in docs:
        by_kind_name.setdefault((k[0], k[2]), []).append(k)

    def find(kind, name, ns=None):
        return [c for c in by_kind_name.get((kind, name), []) if ns is None or c[1] in (ns, "")]

    def doc_edges(k, d):
        edges = []
        kind, ns, _ = k
        spec = _d(d.get("spec"))
        if kind == "Service" and spec.get("selector"):
            for wk, wd in docs.items():
                if wk[0] in WORKLOADS and wk[1] == ns:
                    labels = pod_spec(wd)[1]
                    if labels and all(labels.get(a) == b for a, b in spec["selector"].items()):
                        edges.append((k, wk, "selects"))
        if kind == "HTTPRoute":
            for rule in spec.get("rules") or []:
                for ref in rule.get("backendRefs") or []:
                    edges += [(k, t, "routes-to") for t in find("Service", ref.get("name"), ref.get("namespace", ns))]
        if kind == "Ingress":
            for rule in spec.get("rules") or []:
                for path in (rule.get("http") or {}).get("paths") or []:
                    svc = ((path.get("backend") or {}).get("service") or {}).get("name")
                    edges += [(k, t, "routes-to") for t in find("Service", svc, ns)]
        if kind == "VirtualService":
            for route in spec.get("http") or []:
                for r in route.get("route") or []:
                    host = ((r.get("destination") or {}).get("host") or "").split(".")[0]
                    edges += [(k, t, "routes-to") for t in find("Service", host)]
        if kind in ("RoleBinding", "ClusterRoleBinding"):
            ref = d.get("roleRef") or {}
            edges += [(k, t, "binds") for t in find(ref.get("kind"), ref.get("name"))]
            for s in d.get("subjects") or []:
                if s.get("kind") == "ServiceAccount":
                    edges += [(k, t, "binds") for t in find("ServiceAccount", s.get("name"), s.get("namespace", ns))]
        if kind == "ExternalSecret":
            target = (spec.get("target") or {}).get("name") or k[2]
            edges += [(k, t, "produces") for t in find("Secret", target, ns)]
        if kind in WORKLOADS:
            ps = pod_spec(d)[0]
            refs = []
            for v in ps.get("volumes") or []:
                if v.get("secret"):
                    refs.append(("Secret", v["secret"].get("secretName")))
                if v.get("configMap"):
                    refs.append(("ConfigMap", v["configMap"].get("name")))
                if v.get("persistentVolumeClaim"):
                    refs.append(("PersistentVolumeClaim", v["persistentVolumeClaim"].get("claimName")))
            for c in (ps.get("containers") or []) + (ps.get("initContainers") or []):
                for ef in c.get("envFrom") or []:
                    if ef.get("secretRef"):
                        refs.append(("Secret", ef["secretRef"].get("name")))
                    if ef.get("configMapRef"):
                        refs.append(("ConfigMap", ef["configMapRef"].get("name")))
                for e in c.get("env") or []:
                    vf = e.get("valueFrom") or {}
                    if vf.get("secretKeyRef"):
                        refs.append(("Secret", vf["secretKeyRef"].get("name")))
                    if vf.get("configMapKeyRef"):
                        refs.append(("ConfigMap", vf["configMapKeyRef"].get("name")))
            for rk, rn in refs:
                edges += [(k, t, "mounts") for t in find(rk, rn, ns)]
        return edges

    edges = []
    for k, d in docs.items():
        try:
            edges += doc_edges(k, d)
        except (AttributeError, TypeError, KeyError):
            continue  # wrong-shaped manifest: adds no edges
    return list(dict.fromkeys(edges))


def hunk_ranges(patch: str) -> list[list[int]]:
    out = []
    for m in HUNK_RE.finditer(patch):
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) is not None else 1
        out.append([start, start + max(length, 1) - 1])
    return out


def matched_glob(path: str, globs: list[str]) -> str | None:
    """gitwildmatch over the whole list (negations respected); returns the first positive pattern that hits."""
    if Path(path).suffix not in MANIFEST_SUFFIXES:
        path += "/_"  # a directory (e.g. a kustomize source path)
    if not pathspec.PathSpec.from_lines("gitwildmatch", globs).match_file(path):
        return None
    for g in globs:
        if not g.startswith("!") and pathspec.PathSpec.from_lines("gitwildmatch", [g]).match_file(path):
            return g
    return None


def trusted_comments(comments: list[dict], login: str) -> list[dict]:
    """Only the authenticated user's own comments and Bot comments may feed triage/Atlantis parsing."""
    out = []
    for c in comments:
        u = c.get("user") or {}
        if u.get("type") == "Bot" or (login and u.get("login") == login):
            out.append(c)
    return out


def read_policy(trees: Trees) -> dict | None:
    """Policy from the local checkout (spec §3), else the base worktree, else the head worktree."""
    roots = []
    try:
        roots.append(Path(sh("git", "rev-parse", "--show-toplevel").strip()))
    except RuntimeError:
        pass
    for root in (*roots, trees.base, trees.head):
        f = root / POLICY_PATH
        if f.exists():
            return yaml.safe_load(f.read_text()) or {}
    return None


def collect(repo: str, pr: dict, files: list[dict], comments: list[dict], trees: Trees) -> dict:
    policy = read_policy(trees)
    policy_found = policy is not None
    policy = policy or {}
    read = policy.get("always_read") or {}
    read_kinds, read_globs = set(read.get("kinds") or []), read.get("paths") or []
    callouts = policy.get("risk_callouts") or {}

    apps_base, apps_head = applications(trees.base), applications(trees.head)
    changed = [f["filename"] for f in files] + [f["previous_filename"] for f in files if f.get("previous_filename")]
    affected: dict[str, list[str]] = {}
    for name, (afile, doc) in {**apps_base, **apps_head}.items():
        src_path = ((doc["spec"].get("source") or {}).get("path") or "").rstrip("/")
        hits = [p for p in changed if p == afile or (src_path and p.startswith(src_path + "/"))]
        if hits:
            affected[name] = hits

    apps_out, base_univ, head_univ, owner, where = [], {}, {}, {}, {}
    handled: set[str] = set()
    for name in sorted(affected):
        b, h = apps_base.get(name), apps_head.get(name)
        afile, adoc = h or b
        ns = (adoc["spec"].get("destination") or {}).get("namespace") or ""
        entry = {"app": name, "application_file": afile,
                 "source_kind": "unknown", "render": "rendered", "render_note": ""}
        try:
            entry["source_kind"] = source_kind(trees.head if h else trees.base, adoc)
            bdocs, bload, bnotes = render_app(trees.base, b[0], b[1], trees.dir, repo) if b else ([], set(), [])
            hdocs, hload, hnotes = render_app(trees.head, h[0], h[1], trees.dir, repo) if h else ([], set(), [])
        except Exception as err:
            entry["render"], entry["render_note"] = "source-diff", f"{type(err).__name__}: {err}"
            apps_out.append(entry)
            continue  # this app's files fall through to non_manifest_changes
        entry["render_note"] = "; ".join(dict.fromkeys(bnotes + hnotes))
        if bload is None or hload is None:
            handled.update(affected[name])
        else:  # directory app: only files that were actually loaded (plus the Application file) are covered
            handled.update(p for p in affected[name] if p in bload | hload or p == afile)
        for side, docs, univ in (("base", bdocs, base_univ), ("head", hdocs, head_univ)):
            for d, f in docs:
                k = res_key(d, ns)
                univ[k], owner[k] = d, name
                where.setdefault(k, {})[side] = f
        for side, pair, univ in (("base", b, base_univ), ("head", h, head_univ)):
            if pair:  # the Application object itself, so spec-only edits (syncPolicy, ...) show up
                k = res_key(pair[1], "argo-cd")
                univ[k], owner[k] = pair[1], name
                where.setdefault(k, {})[side] = pair[0]
        apps_out.append(entry)

    changes: dict[tuple, tuple[str, list[str]]] = {}
    for k in set(base_univ) | set(head_univ):
        a, b2 = base_univ.get(k), head_univ.get(k)
        if a is None:
            changes[k] = ("added", [])
        elif b2 is None:
            changes[k] = ("removed", [])
        elif paths := diff_paths(a, b2):
            changes[k] = ("modified", sorted(paths, key=lambda p: (-(p.count(".") + p.count("[")), p))[:MAX_CHANGED_PATHS])

    universe = dict(head_univ)
    universe.update({k: base_univ[k] for k, (act, _) in changes.items() if act == "removed"})
    generated: set[tuple] = set()
    for k, d in list(universe.items()):
        if k[0] == "ExternalSecret":
            target = ((d.get("spec") or {}).get("target") or {}).get("name") or k[2]
            sk = ("Secret", k[1], target)
            if sk not in universe:
                universe[sk] = {"kind": "Secret", "metadata": {"name": target, "namespace": k[1]}}
                owner[sk] = owner.get(k)
                generated.add(sk)
    edges = build_edges(universe)
    neighbors = {b2 for a, b2, _ in edges if a in changes} | {a for a, b2, _ in edges if b2 in changes}
    order = sorted(changes, key=lambda k: (owner.get(k) or "", k)) + sorted(n for n in neighbors if n not in changes)

    ids, resources = {}, []
    for i, k in enumerate(order, start=1):
        ids[k] = f"r{i}"
        action, paths = changes.get(k, ("generated" if k in generated else "context", []))
        loc = where.get(k, {})
        side = "base" if action == "removed" else "head"
        file = loc.get(side) or loc.get("head") or loc.get("base")
        resources.append({"id": ids[k], "app": owner.get(k), "kind": k[0], "namespace": k[1], "name": k[2],
                          "action": action, "changed_paths": paths, "file": file,
                          "lines": find_lines(trees.base if side == "base" else trees.head, file, k[0], k[2]),
                          "risk": callouts.get(k[0])})
    edges_out = [{"from": ids[a], "to": ids[b2], "type": t} for a, b2, t in edges if a in ids and b2 in ids]

    tf, nm, notes = [], [], []
    if not policy_found:
        notes.append({"key": "policy", "text": "No .github/review-policy.yaml found; no always-read checks were applied."})
    tf_files = [f for f in files if f["filename"].startswith("terraform/")]
    plans = [c for c in comments if ATLANTIS_RE.search(c.get("body") or "")]
    if tf_files and plans:
        for m in ATLANTIS_RE.finditer(plans[-1]["body"]):
            tf.append({"id": f"t{len(tf) + 1}", "address": m.group(1), "action": TF_ACTIONS[m.group(2)],
                       "source": "atlantis-plan"})
        handled.update(f["filename"] for f in tf_files if f["filename"].endswith((".tf", ".tfvars")))
    elif tf_files:
        notes.append({"key": "terraform", "text": "Terraform files changed but no Atlantis plan comment was "
                                                  "found; they appear as source-diff files only."})
    for f in files:
        if f["filename"] not in handled:
            nm.append({"id": f"f{len(nm) + 1}", "file": f["filename"], "status": f["status"],
                       "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                       "hunks": hunk_ranges(f.get("patch") or "")})

    candidates: dict[tuple, list[dict]] = {}
    for r in resources:
        if r["action"] in ("context", "generated"):
            continue
        if r["kind"] in read_kinds:
            rule = f"always_read.kinds {r['kind']}"
        elif r["file"] and (pat := matched_glob(r["file"], read_globs)):
            rule = f"always_read.paths ({pat})"
        else:
            continue
        candidates.setdefault((r["app"], rule), []).append(
            {"ref": r["id"], "rule": rule, "callout": callouts.get(r["kind"], "always read")})
    for n in nm:
        if pat := matched_glob(n["file"], read_globs):
            rule = f"always_read.paths ({pat})"
            candidates.setdefault(("file", n["file"], rule), []).append({"ref": n["id"], "rule": rule, "callout": "always read"})
    for t in tf:
        candidates.setdefault(("terraform", ""), []).append(
            {"ref": t["id"], "rule": "always_read.paths (terraform/**)", "callout": "infrastructure change"})
    policy_hits = []
    for group in candidates.values():
        kept = group[:MAX_HITS_PER_APP_RULE]
        if len(group) > len(kept):
            kept[-1] = {**kept[-1], "more": len(group) - len(kept)}
        policy_hits += kept

    triage = None
    for c in comments:
        if m := TRIAGE_RE.search(c.get("body") or ""):
            triage = {"label": m.group(1), "why": m.group(2).strip()}
    return {
        "pr": {"number": pr["number"], "title": pr["title"], "url": pr["html_url"], "repo": repo,
               "base_sha": pr["base"]["sha"], "head_sha": pr["head"]["sha"],
               "merge_base": trees.merge_base},
        "triage": triage, "apps": apps_out, "resources": resources, "edges": edges_out,
        "non_manifest_changes": nm, "terraform": tf, "policy_hits": policy_hits, "notes": notes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect deterministic PR facts for pr-explainer")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--repo", help="owner/name (default: origin of the current checkout)")
    ap.add_argument("--out", required=True, help="work directory for facts.json and diff.patch")
    args = ap.parse_args()
    repo = args.repo or repo_from_origin()
    pr = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{args.pr}"))
    files = gh_pages(f"repos/{repo}/pulls/{args.pr}/files?per_page=100")
    comments = gh_pages(f"repos/{repo}/issues/{args.pr}/comments?per_page=100")
    comments = trusted_comments(comments, sh("gh", "api", "user", "--jq", ".login").strip())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diff.patch").write_text(sh("gh", "pr", "diff", str(args.pr), "-R", repo))
    trees = Trees(args.pr, pr["base"]["sha"], pr["head"]["sha"])
    try:
        facts = collect(repo, pr, files, comments, trees)
    finally:
        trees.close()
    (out / "facts.json").write_text(json.dumps(facts, indent=2))
    changed = sum(r["action"] not in ("context", "generated") for r in facts["resources"])
    unrendered = [a["app"] for a in facts["apps"] if a["render"] != "rendered"]
    print(f"collect: {changed} changed resources, {len(facts['edges'])} edges, "
          f"{len(facts['non_manifest_changes'])} non-manifest files, {len(facts['policy_hits'])} policy hits, "
          f"unrendered apps: {unrendered or 'none'}")
    print(f"collect: wrote {out / 'facts.json'} and {out / 'diff.patch'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
