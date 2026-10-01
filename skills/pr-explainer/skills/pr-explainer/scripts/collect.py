#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""pr-explainer: collect deterministic facts about a PR into <out>/facts.json and <out>/diff.patch.

Usage: collect.py --pr N [--repo owner/name] --out DIR   (--repo is required outside a checkout of the repo)
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
from collections import Counter
from pathlib import Path

import pathspec
import yaml

POLICY_PATH = ".github/review-policy.yaml"
# Applications under these directories are templated (Helm templates/, vendored charts/), not applied as written.
APP_SKIP_DIRS = {".git", "node_modules", "templates", "charts", "vendor"}
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
# A resource header in plain-text plan output. Addresses can hold spaces inside for_each keys, and
# tainted or deposed objects carry a qualifier between the address and the action.
PLAN_LINE_RE = re.compile(r"^\s*# (.+?)(?: \(deposed object \w+\))?(?: is tainted, so)? (will be created|"
                          r"will be updated in-place|must be replaced|will be destroyed|will be read during apply)[ \t\r]*$", re.M)
# chg-opentofu-workflows opentofu-pr-plan.yaml posts one comment per environment, edited in place.
IAC_PLAN_MARKER_RE = re.compile(r"<!-- iac-pr-plan:([\w.-]+) -->")
IAC_SUMMARY_RE = re.compile(r"\*\*Summary:\*\* (\d+) to add, (\d+) to change, (\d+) to destroy, (\d+) to replace\.")
IAC_COMMIT_RE = re.compile(r"commit: `([0-9a-f]{7,40})`")
IAC_RUN_RE = re.compile(r"\[workflow run\]\((https://github\.com/[^)\s]+/actions/runs/\d+)\)")
ACTION_RANK = {"destroy": 0, "replace": 1, "create": 2, "update": 3, "read": 4}
JIRA_KEY_RE = re.compile(r"\bIFS-\d+\b", re.I)
JIRA_FIELDS = "summary,status,issuetype,description,parent,comment"
JIRA_DESCRIPTION_CHARS = 6000
JIRA_COMMENT_CHARS = 1500
JIRA_MAX_COMMENTS = 5
TF_ACTIONS = {"will be created": "create", "will be updated in-place": "update", "must be replaced": "replace",
              "will be destroyed": "destroy", "will be read during apply": "read"}
TRIAGE_RE = re.compile(r"<!-- pr-triage -->\s*\n###\s*\S+\s*(review:\w+)\s*\n\*\*Why:\*\*\s*(.*)")
TF_SUFFIXES = (".tf", ".tfvars", ".tf.json", ".terraform.lock.hcl")
PLAN_TOTALS_RE = re.compile(r"^Plan: (\d+) to add, (\d+) to change, (\d+) to destroy\.", re.M)
TF_BLOCK_RE = re.compile(r'^(resource|data)\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.M)
TF_TOP_RE = re.compile(r"^(resource|data|variable|output|locals|module|provider|terraform|moved|import|removed|check)\b", re.M)
MAX_CHANGED_PATHS = 10
MAX_HITS_PER_APP_RULE = 5
# GitHub runs only files directly in this directory; copies elsewhere (docs/examples/...) are text.
WORKFLOW_DIR = ".github/workflows/"
# Workflow-level keys that change how every job runs, compared as one element each.
WORKFLOW_SETTINGS = ("name", "run-name", "permissions", "env", "concurrency", "defaults")
# Events whose inputs/outputs/secrets form a caller-facing interface, compared per entry.
WORKFLOW_INTERFACE_EVENTS = ("workflow_call", "workflow_dispatch")
WORKFLOW_ELEMENT_ORDER = {"setting": 0, "trigger": 1, "input": 2, "output": 3, "secret": 4, "job": 5}


def sh(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}…: {proc.stderr.strip()[:400]}")
    return proc.stdout


def gh_pages(path: str) -> list[dict]:
    return [item for page in json.loads(sh("gh", "api", "--paginate", "--slurp", path)) for item in page]


def repo_from_origin() -> str | None:
    """owner/name of the current directory's origin, or None outside a GitHub checkout."""
    try:
        url = sh("git", "remote", "get-url", "origin").strip()
    except (RuntimeError, FileNotFoundError):
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


class Trees:
    """Detached worktrees of the PR's base and head commits.

    Uses the current checkout when its origin is the PR's repo. Anywhere else it fetches into a
    temporary bare repo, so the skill runs without a local clone and never fetches the wrong remote.
    """

    def __init__(self, repo: str, pr: int, base_sha: str, head_sha: str):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-explainer-"))
        self.base, self.head = self.dir / "base", self.dir / "head"
        origin = repo_from_origin()
        if origin and origin.lower() == repo.lower():
            self.local: Path | None = Path(sh("git", "rev-parse", "--show-toplevel").strip())
            self.git = self.local
            fetch = ["git", "fetch", "--quiet", "origin"]
        else:
            self.local = None
            self.git = self.dir / "repo.git"
            # Blobless: commits and trees for merge-base, file contents only for the two checkouts.
            fetch = ["git", "fetch", "--quiet", "--filter=blob:none", "origin"]
        try:
            if not self.local:
                sh("git", "init", "--quiet", "--bare", str(self.git))
                sh("git", "remote", "add", "origin", f"https://github.com/{repo}.git", cwd=self.git)
                # gh's token covers private repos, including the lazy blob fetches worktree add makes.
                # The empty entry drops inherited helpers so a stale keychain credential cannot win.
                sh("git", "config", "credential.helper", "", cwd=self.git)
                sh("git", "config", "--add", "credential.helper", "!gh auth git-credential", cwd=self.git)
            sh(*fetch, f"pull/{pr}/head", base_sha, cwd=self.git)
            self.merge_base = sh("git", "merge-base", base_sha, head_sha, cwd=self.git).strip()
            sh("git", "worktree", "add", "--detach", "--quiet", str(self.base), self.merge_base, cwd=self.git)
            sh("git", "worktree", "add", "--detach", "--quiet", str(self.head), head_sha, cwd=self.git)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.local:
            for tree in (self.base, self.head):
                subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=self.local, capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.local:
            subprocess.run(["git", "worktree", "prune"], cwd=self.local, capture_output=True)


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


def find_applications(root: Path) -> list[tuple[str, str, dict]]:
    """(name, repo-relative file, doc) for every Argo CD Application manifest in a worktree.

    Repos keep Applications in different places (base-apps/, argo/<env>/, ...), so the whole tree
    is searched. Helm templates/ and vendored charts/ are skipped: Applications there are
    templated, not applied as written.
    """
    found = []
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if f.suffix not in (".yaml", ".yml") or not f.is_file() or APP_SKIP_DIRS & set(rel.parts[:-1]):
            continue
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if "Application" not in text:
            continue
        try:
            docs = load_docs(text)
        except yaml.YAMLError:
            continue
        for d in docs:
            md, spec = d.get("metadata"), d.get("spec")
            if (d.get("kind") == "Application" and str(d.get("apiVersion", "")).startswith("argoproj.io/")
                    and isinstance(md, dict) and md.get("name") and isinstance(spec, dict)):
                found.append((str(md["name"]), str(rel), d))
    return found


def applications(base: list[tuple[str, str, dict]], head: list[tuple[str, str, dict]]) -> tuple[dict, dict, bool]:
    """App id -> (file, doc) for base and head, and whether Applications span several directories.

    The id is metadata.name, qualified with the file's directory when one name appears in several
    files (one Application per environment directory), and with the whole path if that still
    collides. Qualification uses both sides so an app keeps one id across base and head.
    """
    names = Counter(n for n, _, _ in {(n, f, "") for n, f, _ in base + head})
    dir_ids = Counter(f"{Path(f).parent}/{n}" for n, f, _ in {(n, f, "") for n, f, _ in base + head})

    def app_id(name: str, file: str) -> str:
        if names[name] == 1:
            return name
        qualified = f"{Path(file).parent}/{name}"
        return qualified if dir_ids[qualified] == 1 else f"{file}:{name}"

    dirs = {str(Path(f).parent) for _, f, _ in base + head}
    return ({app_id(n, f): (f, d) for n, f, d in base}, {app_id(n, f): (f, d) for n, f, d in head}, len(dirs) > 1)


def app_sources(app: dict) -> list[dict]:
    """spec.sources (multi-source) or spec.source, as a list."""
    spec = app.get("spec") or {}
    if isinstance(spec.get("sources"), list):
        return [s for s in spec["sources"] if isinstance(s, dict)]
    return [spec["source"]] if isinstance(spec.get("source"), dict) else []


def same_repo(url: str | None, repo: str) -> bool:
    url = (url or "").lower().rstrip("/")
    url = url[:-4] if url.endswith(".git") else url
    return url.endswith("/" + repo.lower()) or url.endswith(":" + repo.lower())


def value_file(root: Path, src: dict, refs: dict[str, dict], vf: str, repo: str) -> Path | None:
    """Worktree path of a helm valueFile, or None when it lives in another repository.

    "$<ref>/path" resolves through the multi-source source named <ref>; a plain name is relative
    to the source's own path. Raises when the path escapes the worktree.
    """
    if vf.startswith("$"):
        ref, _, rest = vf[1:].partition("/")
        if ref not in refs or not same_repo(refs[ref].get("repoURL"), repo):
            return None
        p = root / (refs[ref].get("path") or "") / rest
    elif src.get("path") and not src.get("chart"):
        p = root / src["path"] / vf
    else:
        return None
    p = Path(os.path.normpath(p))
    if not p.is_relative_to(root):
        raise RuntimeError(f"valueFile outside the repository: {vf}")
    return p


def watched_files(root: Path, app: dict, repo: str) -> tuple[list[str], set[str]]:
    """(source directories, value files) in this repo that the Application renders from."""
    sources = app_sources(app)
    refs = {s["ref"]: s for s in sources if s.get("ref")}
    dirs, files = [], set()
    for src in sources:
        if src.get("path") and not src.get("chart") and (not src.get("repoURL") or same_repo(src["repoURL"], repo)):
            dirs.append(src["path"].strip("/"))
        for vf in (src.get("helm") or {}).get("valueFiles") or []:
            try:
                p = value_file(root, src, refs, str(vf), repo)
            except RuntimeError:
                continue
            if p:
                files.add(str(p.relative_to(root)))
    return dirs, files


def app_source_kind(root: Path, app: dict) -> str:
    kinds = [source_kind(root, s) for s in app_sources(app) if s.get("chart") or s.get("path")]
    return ", ".join(dict.fromkeys(kinds)) or "unknown"


def source_kind(root: Path, src: dict) -> str:
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


def dir_manifests(root: Path, src: dict) -> tuple[list[tuple[dict, str]], set[str]]:
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


def helm_docs(root: Path, app: dict, src: dict, refs: dict[str, dict], work: Path,
              repo: str) -> tuple[list[dict], list[str]]:
    helm = os.environ.get("HELM_BIN", "helm")  # HELM_BIN=/nonexistent simulates a missing helm
    if not shutil.which(helm):
        raise RuntimeError("helm not installed (brew install helm)")
    spec = app["spec"]
    h = src.get("helm") or {}
    notes = []
    name = h.get("releaseName") or app["metadata"]["name"]
    ns = (spec.get("destination") or {}).get("namespace") or "default"
    if src.get("chart"):
        chart_repo = src["repoURL"]
        chart = ([src["chart"], "--repo", chart_repo] if chart_repo.startswith(("http://", "https://"))
                 else [f"oci://{chart_repo.rstrip('/')}/{src['chart']}"])
        chart += ["--version", str(src["targetRevision"])]
    else:
        chart_dir = root / src["path"]
        chart = [str(chart_dir)]
        chart_meta = yaml.safe_load((chart_dir / "Chart.yaml").read_text()) or {}
        if chart_meta.get("dependencies") and not (chart_dir / "charts").is_dir():
            # A wrapper chart's dependencies are not committed; Argo CD fetches them the same way.
            sh(helm, "dependency", "build", str(chart_dir))
    cmd = [helm, "template", name, *chart, "--namespace", ns]
    if not h.get("skipCrds"):
        cmd.append("--include-crds")
    if h.get("skipSchemaValidation"):
        cmd.append("--skip-schema-validation")
    for vf in h.get("valueFiles") or []:
        p = value_file(root, src, refs, str(vf), repo)
        if p is None:
            notes.append(f"valueFile {vf} not applied (another repository or a chart-repo source)")
        elif p.is_file():
            cmd += ["-f", str(p)]
        elif not h.get("ignoreMissingValueFiles"):
            raise RuntimeError(f"valueFile missing: {p.relative_to(root)}")
    for key in ("values", "valuesObject"):
        if h.get(key):
            value = h[key] if isinstance(h[key], str) else yaml.safe_dump(h[key])
            tmp = tempfile.NamedTemporaryFile("w", dir=work, suffix=".yaml", delete=False)
            tmp.write(value)
            tmp.close()
            cmd += ["-f", tmp.name]
    for prm in h.get("parameters") or []:
        cmd += ["--set-string" if prm.get("forceString") else "--set", f"{prm['name']}={prm['value']}"]
    return load_docs(sh(*cmd)), notes


def render_source(root: Path, app_file: str, app: dict, src: dict, refs: dict[str, dict], work: Path,
                  repo: str) -> tuple[list[tuple[dict, str]], set[str] | None, list[str]]:
    if not src.get("chart") and src.get("path"):
        if src.get("repoURL") and not same_repo(src["repoURL"], repo):
            raise RuntimeError("source is another repository")
        if not (root / src["path"]).is_dir():
            raise RuntimeError("source path missing")
    kind = source_kind(root, src)
    if kind == "directory":
        docs, loaded = dir_manifests(root, src)
        return docs, loaded, []
    if kind == "kustomize":
        if not shutil.which("kubectl"):
            raise RuntimeError("kubectl not installed")
        return [(d, src["path"]) for d in load_docs(sh("kubectl", "kustomize", str(root / src["path"])))], None, []
    if kind in ("helm", "helm-local"):
        docs, notes = helm_docs(root, app, src, refs, work, repo)
        return [(d, app_file) for d in docs], None, notes
    raise RuntimeError(f"unsupported Application source ({kind})")


def render_app(root: Path, app_file: str, app: dict, work: Path,
               repo: str) -> tuple[list[tuple[dict, str]], set[str] | None, list[str]]:
    """Returns (docs with their source file, files actually loaded or None for 'all', render notes).

    Multi-source Applications render every chart or path source, as Argo CD does; a ref-only
    source just supplies $<ref> value files.
    """
    sources = app_sources(app)
    refs = {s["ref"]: s for s in sources if s.get("ref")}
    renderable = [s for s in sources if s.get("chart") or s.get("path")]
    if not renderable:
        raise RuntimeError("no chart or path source")
    docs: list[tuple[dict, str]] = []
    loaded: set[str] | None = set()
    notes: list[str] = []
    for src in renderable:
        d, ld, n = render_source(root, app_file, app, src, refs, work, repo)
        docs += d
        notes += n
        loaded = None if loaded is None or ld is None else loaded | ld
    return docs, loaded, notes


def res_key(doc: dict, default_ns: str, scope: str = "") -> tuple[str, str, str, str]:
    """(kind, namespace, name, scope). scope is the Application's directory when Applications span
    several directories (one per environment), so one object in two clusters stays two resources."""
    md = doc.get("metadata")
    md = md if isinstance(md, dict) else {}
    ns = "" if doc.get("kind") in CLUSTER_SCOPED else (md.get("namespace") or default_ns)
    return (str(doc.get("kind")), ns, str(md.get("name", "?")), scope)


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
        kind, ns = k[0], k[1]
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
    """Only the authenticated user's own comments and Bot comments may feed triage/plan parsing."""
    out = []
    for c in comments:
        u = c.get("user") or {}
        if u.get("type") == "Bot" or (login and u.get("login") == login):
            out.append(c)
    return out


def read_policy(trees: Trees) -> dict | None:
    """Policy from the local checkout (spec §3), else the base worktree, else the head worktree."""
    roots = [trees.local] if trees.local else []
    for root in (*roots, trees.base, trees.head):
        f = root / POLICY_PATH
        if f.exists():
            return yaml.safe_load(f.read_text()) or {}
    return None


def tf_dir(path: str | Path) -> str:
    """The Terraform root a file belongs to: its directory, "" for the repo root."""
    parent = str(Path(path).parent)
    return "" if parent == "." else parent


def tf_block_list(root: Path, dirs: set[str] | None = None) -> list[tuple[str, str, int, str]]:
    """(address, file, line, body) for each resource/data block in the *.tf files under root.

    A block runs to the next top-level block keyword; tofu fmt keeps those at column 0. Comment
    lines are dropped so an address named only in prose does not become a dependency edge.
    dirs, when given, limits the scan to those directories (relative to root, "" for the root).
    """
    out = []
    for f in sorted(root.rglob("*.tf")):
        rel = f.relative_to(root)
        if ".terraform" in f.parts or (dirs is not None and tf_dir(rel) not in dirs):
            continue
        text = f.read_text(errors="replace")
        starts = sorted(m.start() for m in TF_TOP_RE.finditer(text))
        for m in TF_BLOCK_RE.finditer(text):
            end = next((s for s in starts if s > m.start()), len(text))
            body = "\n".join(l for l in text[m.end():end].splitlines() if not l.lstrip().startswith(("#", "//")))
            addr = f"{m.group(2)}.{m.group(3)}" if m.group(1) == "resource" else f"data.{m.group(2)}.{m.group(3)}"
            out.append((addr, str(rel), text.count("\n", 0, m.start()) + 1, body))
    return out


def tf_blocks(root: Path) -> dict[str, tuple[str, int, str]]:
    """address -> (file, line, body); the last block wins when two roots share an address."""
    return {addr: (file, line, body) for addr, file, line, body in tf_block_list(root)}


def tf_reference_edges(groups: dict, bodies: dict) -> list[dict]:
    """Edges src -> dst where src's block body names dst's address.

    groups maps a key (an address, or (dir, address) when several roots are scanned) to the
    fact IDs that share that block; bodies maps the same key to the block body. for_each and
    count give one plan entry per instance but one block, so edges attach to every instance.
    """
    edges = []
    for src, src_ids in groups.items():
        if src not in bodies:
            continue
        for dst, dst_ids in groups.items():
            same_root = not isinstance(src, tuple) or src[0] == dst[0]
            addr = dst[1] if isinstance(dst, tuple) else dst
            if dst != src and same_root and re.search(r"(?<![\w.])" + re.escape(addr) + r"(?![\w])", bodies[src]):
                edges += [{"from": a, "to": b, "type": "references"} for a in src_ids for b in dst_ids]
    return edges


def terraform_source_facts(tf_files: list[dict], trees: Trees) -> tuple[list[dict], list[dict], list[dict]]:
    """Resources from comparing resource/data blocks at base and head, for PRs without a plan comment.

    Only the root directories that hold a changed .tf file are compared, keyed by (dir, address)
    so a block moved between files in one root is not reported. Actions are source-level
    (added | modified | removed), never plan results.
    """
    dirs = {tf_dir(f["filename"]) for f in tf_files if f["filename"].endswith(".tf")}
    note = {"key": "terraform", "text": "No plan comment was found, so Terraform resources come from comparing "
                                        "resource and data blocks at base and head. Their actions are source-level "
                                        "(added, modified, removed), not plan results: count/for_each instances, module "
                                        "internals, moved/import/removed blocks, variable/local-driven changes and "
                                        "forced replacements are not resolved."}
    if not dirs:
        return [], [], [{"key": "terraform", "text": "No plan comment was found and only .tfvars, .tf.json or lock "
                                                     "files changed; no Terraform resources were derived."}]

    def norm(body: str) -> str:
        return "\n".join(l.strip() for l in body.splitlines() if l.strip())

    def index(root: Path) -> dict:
        return {(tf_dir(file), addr): (file, line, body) for addr, file, line, body in tf_block_list(root, dirs)}

    base, head = index(trees.base), index(trees.head)
    tf = []
    for key in sorted(base.keys() | head.keys(), key=lambda k: (head.get(k) or base[k])[:2]):
        if key not in base:
            action, side = "added", head
        elif key not in head:
            action, side = "removed", base
        elif norm(base[key][2]) != norm(head[key][2]):
            action, side = "modified", head
        else:
            continue
        file, line, _ = side[key]
        address = key[1]
        rtype, _, rname = address.removeprefix("data.").partition(".")
        tf.append({"id": f"t{len(tf) + 1}", "address": address, "action": action, "source": "source-diff",
                   "type": rtype, "name": rname, "file": file, "lines": [line]})
    groups = {(tf_dir(t["file"]), t["address"]): [t["id"]] for t in tf}
    bodies = {k: v[2] for k, v in head.items()}
    return tf, tf_reference_edges(groups, bodies), [note]


def parse_plan(body: str, environment: str | None, source: str) -> dict:
    """One plan comment: resource entries, totals, and the commit and run it came from."""
    entries: dict[str, str] = {}  # a comment can repeat the plan (one block per workspace); first wins
    for m in PLAN_LINE_RE.finditer(body):
        entries.setdefault(m.group(1), TF_ACTIONS[m.group(2)])
    totals = None
    if m := IAC_SUMMARY_RE.search(body):
        totals = dict(zip(("add", "change", "destroy", "replace"), map(int, m.groups())))
    elif m := list(PLAN_TOTALS_RE.finditer(body))[-1:]:
        totals = dict(zip(("add", "change", "destroy"), map(int, m[0].groups())))
    commit, run = IAC_COMMIT_RE.search(body), IAC_RUN_RE.search(body)
    failed = "plan **failed**" in body
    return {"environment": environment, "source": source, "entries": entries, "totals": totals,
            "status": "failed" if failed else "no-changes" if totals and not any(totals.values()) else "changes",
            "commit": commit.group(1) if commit else None, "run_url": run.group(1) if run else None}


def plan_comments(comments: list[dict]) -> list[dict]:
    """Every environment's iac-pr-plan comment, or else the newest Atlantis-style plan comment."""
    by_env: dict[str, str] = {}
    for c in comments:
        if m := IAC_PLAN_MARKER_RE.search(c.get("body") or ""):
            by_env[m.group(1)] = c["body"]
    if by_env:
        return [parse_plan(body, env, "iac-pr-plan") for env, body in sorted(by_env.items())]
    legacy = [c["body"] for c in comments if PLAN_LINE_RE.search(c.get("body") or "")]
    return [parse_plan(legacy[-1], None, "atlantis")] if legacy else []


def listed(plan: dict) -> int:
    """Changed resources a plan comment names, counted the way its totals count them.

    A "Plan: N to add, ..., N to destroy" line counts a replacement once in add and once in
    destroy; the iac-pr-plan summary counts it once, under replace.
    """
    twice = plan["totals"] is not None and "replace" not in plan["totals"]
    return sum(2 if twice and a == "replace" else 1 for a in plan["entries"].values() if a != "read")


def plan_notes(plans: list[dict], head_sha: str) -> list[dict]:
    """Stale, failed, and truncated plans, so the page never presents a partial plan as whole."""
    def name(p: dict) -> str:
        return p["environment"] or "the plan comment"
    notes = []
    stale = [p for p in plans if p["commit"] and not head_sha.startswith(p["commit"])]
    if stale:
        notes.append({"key": "plan-stale", "text": "Plan is older than the PR head (" + head_sha[:7] + ") for: "
                      + ", ".join(f"{name(p)} at {p['commit']}" for p in stale) + ". Re-run the plan workflow."})
    failed = [p for p in plans if p["status"] == "failed"]
    if failed:
        notes.append({"key": "plan-failed", "text": "Plan failed for: " + ", ".join(
            f"{name(p)} ({p['run_url'] or 'no run link'})" for p in failed) + "; its resources are not mapped."})
    truncated = [p for p in plans if p["status"] == "changes" and p["totals"]
                 and listed(p) < sum(p["totals"].values())]
    if truncated:
        # opentofu-pr-plan.yaml keeps only the last 60000 characters of the plan text.
        notes.append({"key": "plan-truncated", "text": "Plan comment text is cut off, so only some changed resources "
                      "are mapped: " + ", ".join(f"{name(p)} lists {listed(p)} of "
                                                 f"{sum(p['totals'].values())}" for p in truncated)
                      + ". The summary totals are complete."})
    return notes


def terraform_facts(files: list[dict], comments: list[dict], trees: Trees,
                    head_sha: str) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Resources from plan comments, edges from head-side references, and one summary per plan.

    Detection is by file suffix, not directory, because OpenTofu roots often sit at the repo root.
    Without a plan comment, resources fall back to a base/head block comparison.
    """
    tf_files = [f for f in files if f["filename"].endswith(TF_SUFFIXES)]
    if not tf_files:
        return [], [], [], []
    plans = plan_comments(comments)
    if not plans:
        tf, edges, notes = terraform_source_facts(tf_files, trees)
        return tf, edges, [], notes
    # One node per address across environments, carrying the most destructive action any plan shows.
    merged: dict[str, dict[str, str]] = {}
    for p in plans:
        for address, action in p["entries"].items():
            merged.setdefault(address, {})[p["environment"] or "default"] = action
    blocks = tf_blocks(trees.head)
    tf = []
    for i, (address, envs) in enumerate(merged.items(), start=1):
        base = re.sub(r"\[[^\]]*\]", "", address)
        file, line, _ = blocks.get(base, (None, None, ""))
        rtype, _, rname = base.removeprefix("data.").partition(".")
        tf.append({"id": f"t{i}", "address": address, "action": min(envs.values(), key=ACTION_RANK.__getitem__),
                   "environments": envs, "source": "plan-comment", "type": rtype, "name": rname,
                   "file": file, "lines": [line] if line else None})
    by_base: dict[str, list[str]] = {}
    for t in tf:
        by_base.setdefault(re.sub(r"\[[^\]]*\]", "", t["address"]), []).append(t["id"])
    edges = tf_reference_edges(by_base, {addr: body for addr, (_, _, body) in blocks.items()})
    summaries = [{"environment": p["environment"], "source": p["source"], "status": p["status"],
                  "totals": p["totals"], "listed": listed(p),
                  "commit": p["commit"], "stale": bool(p["commit"]) and not head_sha.startswith(p["commit"]),
                  "run_url": p["run_url"]} for p in plans]
    return tf, edges, summaries, plan_notes(plans, head_sha)


def is_workflow(path: str) -> bool:
    rest = path.removeprefix(WORKFLOW_DIR)
    return path.startswith(WORKFLOW_DIR) and "/" not in rest and rest.endswith((".yml", ".yaml"))


def workflow_triggers(doc: dict) -> dict:
    """event -> config. PyYAML reads a bare `on:` key as True; `on` may be a string, list or map."""
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(e): {} for e in on}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in (on or {}).items()} if isinstance(on, dict) else {}


def step_map(steps) -> dict:
    """Steps keyed by id, name or uses, so inserting one step does not mark every later step changed."""
    out: dict[str, object] = {}
    for i, step in enumerate(steps if isinstance(steps, list) else []):
        s = step if isinstance(step, dict) else {}
        key = str(s.get("id") or s.get("name") or s.get("uses") or f"step {i + 1}")
        n, base = 2, key
        while key in out:
            key, n = f"{base} #{n}", n + 1
        out[key] = step
    return out


def workflow_elements(doc: dict) -> dict[tuple[str, str, str], tuple[object, list[str]]]:
    """(element, event, name) -> (value, key path for the line lookup)."""
    out: dict[tuple[str, str, str], tuple[object, list[str]]] = {}
    for key in WORKFLOW_SETTINGS:
        if key in doc:
            out[("setting", "", key)] = (doc[key], [key])
    for event, cfg in workflow_triggers(doc).items():
        interface = {"inputs", "outputs", "secrets"} if event in WORKFLOW_INTERFACE_EVENTS else set()
        out[("trigger", event, event)] = ({k: v for k, v in cfg.items() if k not in interface}, ["on", event])
        for section in sorted(interface):
            for name, spec in (cfg.get(section) or {}).items():
                out[(section[:-1], event, str(name))] = (spec, ["on", event, section, str(name)])
    for name, job in (doc.get("jobs") or {}).items():
        j = dict(job) if isinstance(job, dict) else {}
        if "steps" in j:
            j["steps"] = step_map(j["steps"])
        out[("job", "", str(name))] = (j, ["jobs", str(name)])
    return out


def key_line(text: str, path: list[str]) -> int | None:
    """1-based line of the last key in path, each key found nested under the one before it."""
    lines, start, parent, found = text.splitlines(), 0, -1, None
    for key in path:
        pat = re.compile(r"^\s*[\"']?" + re.escape(key) + r"[\"']?\s*:")
        for i in range(start, len(lines)):
            stripped = lines[i].lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            depth = len(lines[i]) - len(stripped)
            if depth <= parent:
                return found  # left the parent block without finding the key
            if pat.match(lines[i]):
                found, start, parent = i + 1, i + 1, depth
                break
        else:
            return found
    return found


def job_needs(job) -> list[str]:
    needs = job.get("needs") if isinstance(job, dict) else None
    return [needs] if isinstance(needs, str) else [str(n) for n in needs or []]


def workflow_facts(files: list[dict], trees: Trees) -> tuple[list[dict], list[dict], list[dict]]:
    """Jobs, triggers, settings and workflow_call/workflow_dispatch interface entries from comparing
    each changed workflow at base and head, plus `needs` edges between jobs.

    Unchanged jobs one `needs` hop from a changed job come along as context so the graph shows
    what a removed or rewired job sat between.
    """
    out, edges, notes, failed = [], [], [], []
    for f in files:
        path = f["filename"]
        if not is_workflow(path):
            continue
        sides = {}
        for side, root in (("base", trees.base), ("head", trees.head)):
            p = root / path
            try:
                doc = yaml.safe_load(p.read_text(errors="replace")) if p.is_file() else None
            except yaml.YAMLError:
                failed.append(path)
                break
            sides[side] = (doc if isinstance(doc, dict) else {}, p.read_text(errors="replace") if p.is_file() else "")
        else:
            (bdoc, btext), (hdoc, htext) = sides["base"], sides["head"]
            base, head = workflow_elements(bdoc), workflow_elements(hdoc)
            changed: dict[tuple, tuple[str, list[str]]] = {}
            for k in base.keys() | head.keys():
                if k not in base:
                    changed[k] = ("added", [])
                elif k not in head:
                    changed[k] = ("removed", [])
                elif paths := diff_paths(base[k][0], head[k][0]):
                    changed[k] = ("modified", sorted(paths)[:MAX_CHANGED_PATHS])
            job_edges = {(src, dst) for doc in (bdoc, hdoc) for src, job in (doc.get("jobs") or {}).items()
                         for dst in job_needs(job)}
            changed_jobs = {k[2] for k in changed if k[0] == "job"}
            context = {n for a, b in job_edges for n in (a, b)
                       if (a in changed_jobs) != (b in changed_jobs) and n not in changed_jobs}
            keys = list(changed) + [("job", "", n) for n in sorted(context) if ("job", "", n) in head]

            def line(k):
                action = changed.get(k, ("context",))[0]
                text, elems = (btext, base) if action == "removed" else (htext, head)
                return key_line(text, elems[k][1]) or 0

            ids = {}
            for k in sorted(keys, key=lambda k: (WORKFLOW_ELEMENT_ORDER[k[0]], line(k), k)):
                action, paths = changed.get(k, ("context", []))
                value = (base if action == "removed" else head)[k][0]
                entry = {"id": f"w{len(out) + 1}", "workflow": path, "element": k[0], "event": k[1], "name": k[2],
                         "action": action, "changed_paths": paths, "file": path, "lines": [line(k)] if line(k) else []}
                if k[0] == "job" and isinstance(value, dict) and value.get("uses"):
                    entry["uses"] = str(value["uses"])
                if k[0] == "input" and isinstance(value, dict):
                    entry["required"] = bool(value.get("required"))
                    entry["has_default"] = "default" in value
                ids[k] = entry["id"]
                out.append(entry)
            edges += [{"from": ids[("job", "", a)], "to": ids[("job", "", b)], "type": "needs"}
                      for a, b in sorted(job_edges) if ("job", "", a) in ids and ("job", "", b) in ids]
    if failed:
        notes.append({"key": "workflows", "text": "These workflow files did not parse as YAML, so their jobs were "
                                                  "not mapped: " + ", ".join(sorted(failed)) + "."})
    if out:
        notes.append({"key": "actions", "text": "GitHub Actions entries come from comparing workflow YAML at base and "
                                                "head. Expressions, matrix expansion, reusable workflows the jobs call, "
                                                "composite actions and callers in other repositories are not resolved."})
    return out, edges, notes


def workflow_hit(w: dict) -> tuple[str, str] | None:
    """(rule, callout) for an entry that always needs a human: a caller-facing interface break, or a
    change to the GITHUB_TOKEN permissions."""
    if w["element"] in ("input", "output", "secret") and w["event"] == "workflow_call":
        if w["action"] == "removed":
            return f"workflow_call {w['element']} removed", "caller interface change"
        if w["element"] == "input" and w.get("required") and not w.get("has_default") and (
                w["action"] == "added" or "required" in w["changed_paths"]):
            return "workflow_call input now required", "caller interface change"
    if w["element"] == "setting" and w["name"] == "permissions" and w["action"] != "context":
        return "workflow permissions changed", "token permissions"
    if w["element"] == "job" and any(p == "permissions" or p.startswith("permissions.") for p in w["changed_paths"]):
        return "job permissions changed", "token permissions"
    return None


def adf_text(node, limit: int) -> str:
    """Plain text from a Jira ADF document (or a plain string), capped at limit characters."""
    if isinstance(node, str):
        text = node
    else:
        out: list[str] = []

        def walk(n) -> None:
            if isinstance(n, list):
                for child in n:
                    walk(child)
            elif isinstance(n, dict):
                kind = n.get("type")
                if kind == "text":
                    out.append(n.get("text", ""))
                elif kind == "hardBreak":
                    out.append("\n")
                elif kind == "listItem":
                    out.append("- ")
                walk(n.get("content", []))
                if kind in ("paragraph", "heading", "codeBlock", "blockquote", "rule"):
                    out.append("\n")
        walk(node)
        text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"


def jira_facts(pr: dict) -> tuple[dict | None, list[dict]]:
    """The IFS ticket the PR names (branch, then title, then body), read through acli.

    The branch wins because CHG branch names carry the ticket by convention; a body can cite
    several tickets. Every failure degrades to a note instead of stopping the run.
    """
    for source, text in (("branch", pr["head"]["ref"]), ("title", pr["title"]), ("body", pr.get("body") or "")):
        if m := JIRA_KEY_RE.search(text):
            key = m.group(0).upper()
            break
    else:
        return None, [{"key": "jira", "text": "No IFS ticket key was found in the branch name, title or body."}]
    if not shutil.which("acli"):
        return None, [{"key": "jira", "text": f"{key} is referenced but acli is not installed, so the ticket was not read."}]
    try:
        data = json.loads(sh("acli", "jira", "workitem", "view", key, "--json", "--fields", JIRA_FIELDS))
    except (RuntimeError, json.JSONDecodeError) as e:
        return None, [{"key": "jira", "text": f"{key} is referenced but could not be read with acli ({type(e).__name__})."}]
    try:
        site = re.search(r"Site:\s*(\S+)", sh("acli", "jira", "auth", "status"))
    except RuntimeError:
        site = None
    f = data.get("fields") or {}
    parent = f.get("parent") or None
    comments = ((f.get("comment") or {}).get("comments") or [])[-JIRA_MAX_COMMENTS:]
    url = f"https://{site.group(1)}/browse/{key}" if site else None
    # j* ids let the explainer cite a comment as evidence for work done outside the PR.
    comments_out = [{"id": f"j{i}", "author": (c.get("author") or {}).get("displayName"),
                     "created": (c.get("created") or "")[:10],
                     "url": f"{url}?focusedCommentId={c['id']}" if url and c.get("id") else url,
                     "body": adf_text(c.get("body") or "", JIRA_COMMENT_CHARS)} for i, c in enumerate(comments, start=1)]
    return {"key": key, "source": source, "url": url,
            "summary": f.get("summary"), "status": (f.get("status") or {}).get("name"),
            "type": (f.get("issuetype") or {}).get("name"),
            "parent": {"key": parent.get("key"), "summary": (parent.get("fields") or {}).get("summary")} if parent else None,
            "description": adf_text(f.get("description") or "", JIRA_DESCRIPTION_CHARS),
            "comments": comments_out}, []


def collect(repo: str, pr: dict, files: list[dict], comments: list[dict], trees: Trees) -> dict:
    policy = read_policy(trees)
    policy_found = policy is not None
    policy = policy or {}
    read = policy.get("always_read") or {}
    read_kinds, read_globs = set(read.get("kinds") or []), read.get("paths") or []
    callouts = policy.get("risk_callouts") or {}

    found_base, found_head = find_applications(trees.base), find_applications(trees.head)
    apps_base, apps_head, scoped = applications(found_base, found_head)
    changed = [f["filename"] for f in files] + [f["previous_filename"] for f in files if f.get("previous_filename")]
    watched = {name: watched_files(trees.head if name in apps_head else trees.base, doc, repo)
               for name, (_, doc) in {**apps_base, **apps_head}.items()}
    # A values file in a shared chart directory affects only the apps that list it, not every app
    # rendering that chart (one values file per environment).
    all_value_files = set().union(*(vf for _, vf in watched.values()))
    affected: dict[str, list[str]] = {}
    for name, (afile, doc) in {**apps_base, **apps_head}.items():
        dirs, vfiles = watched[name]
        hits = [p for p in changed if p == afile or p in vfiles
                or (any(p.startswith(d + "/") for d in dirs) and p not in all_value_files)]
        if hits:
            affected[name] = hits

    apps_out, base_univ, head_univ, owner, where = [], {}, {}, {}, {}
    handled: set[str] = set()
    for name in sorted(affected):
        b, h = apps_base.get(name), apps_head.get(name)
        afile, adoc = h or b
        ns = (adoc["spec"].get("destination") or {}).get("namespace") or ""
        scope = str(Path(afile).parent) if scoped else ""
        entry = {"app": name, "application_file": afile,
                 "source_kind": "unknown", "render": "rendered", "render_note": ""}
        try:
            entry["source_kind"] = app_source_kind(trees.head if h else trees.base, adoc)
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
                k = res_key(d, ns, scope)
                univ[k], owner[k] = d, name
                where.setdefault(k, {})[side] = f
        for side, pair, univ in (("base", b, base_univ), ("head", h, head_univ)):
            if pair:  # the Application object itself, so spec-only edits (syncPolicy, ...) show up
                k = res_key(pair[1], "argo-cd", scope)
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
            sk = ("Secret", k[1], target, k[3])
            if sk not in universe:
                universe[sk] = {"kind": "Secret", "metadata": {"name": target, "namespace": k[1]}}
                owner[sk] = owner.get(k)
                generated.add(sk)
    by_scope: dict[str, dict[tuple, dict]] = {}
    for k, d in universe.items():
        by_scope.setdefault(k[3], {})[k] = d
    edges = [e for part in by_scope.values() for e in build_edges(part)]
    neighbors = {b2 for a, b2, _ in edges if a in changes} | {a for a, b2, _ in edges if b2 in changes}
    order = sorted(changes, key=lambda k: (owner.get(k) or "", k)) + sorted(n for n in neighbors if n not in changes)

    ids, resources = {}, []
    for i, k in enumerate(order, start=1):
        ids[k] = f"r{i}"
        action, paths = changes.get(k, ("generated" if k in generated else "context", []))
        loc = where.get(k, {})
        side = "base" if action == "removed" else "head"
        file = loc.get(side) or loc.get("head") or loc.get("base")
        resources.append({"id": ids[k], "app": owner.get(k), "scope": k[3], "kind": k[0], "namespace": k[1], "name": k[2],
                          "action": action, "changed_paths": paths, "file": file,
                          "lines": find_lines(trees.base if side == "base" else trees.head, file, k[0], k[2]),
                          "risk": callouts.get(k[0])})
    edges_out = [{"from": ids[a], "to": ids[b2], "type": t} for a, b2, t in edges if a in ids and b2 in ids]

    tf, nm, notes = [], [], []
    if not policy_found:
        notes.append({"key": "policy", "text": "No .github/review-policy.yaml found; no always-read checks were applied."})
    # .tf files stay in non_manifest_changes: a plan lists only changed resources, so locals,
    # variables and tfvars edits would otherwise vanish from the facts.
    tf, tf_edges, tf_plans, tf_notes = terraform_facts(files, comments, trees, pr["head"]["sha"])
    notes += tf_notes
    # Workflow files also stay in non_manifest_changes, so a hunk the comparison cannot name
    # (a run: script body) is still citable.
    wf, wf_edges, wf_notes = workflow_facts(files, trees)
    notes += wf_notes
    jira, jira_notes = jira_facts(pr)
    notes += jira_notes
    for f in files:
        if f["filename"] not in handled:
            nm.append({"id": f"f{len(nm) + 1}", "file": f["filename"], "status": f["status"],
                       "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                       "hunks": hunk_ranges(f.get("patch") or "")})
    mapped_workflows = {w["file"] for w in wf}
    unrendered_yaml = [n for n in nm if n["file"].endswith((".yaml", ".yml")) and n["file"] not in mapped_workflows]
    if unrendered_yaml and not affected:
        # Without this note an empty resource map looks like "nothing to render" instead of "nothing found".
        where = (f"{len(apps_base | apps_head)} Argo CD Applications were found, but none deploys them"
                 if apps_base or apps_head else "no Argo CD Application manifest was found in the repository")
        notes.append({"key": "apps", "text": f"{len(unrendered_yaml)} changed YAML files were not rendered: {where}. "
                                             "They are summarized from the raw diff."})

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
        # Replacing or destroying infrastructure (a removed resource block destroys it unless a
        # moved or removed block says otherwise) always needs a human; other entries only
        # when the repo's own policy globs claim the file.
        if t["action"] in ("replace", "destroy") or (t["action"] == "removed" and not t["address"].startswith("data.")) or (t["file"] and matched_glob(t["file"], read_globs)):
            candidates.setdefault(("terraform", ""), []).append(
                {"ref": t["id"], "rule": ("terraform plan " if t["source"] == "plan-comment" else "terraform source ")
                 + t["action"], "callout": "infrastructure change"})
    for w in wf:
        if hit := workflow_hit(w):
            candidates.setdefault(("workflow", w["file"], hit[0]), []).append(
                {"ref": w["id"], "rule": hit[0], "callout": hit[1]})
        elif w["action"] != "context" and (pat := matched_glob(w["file"], read_globs)):
            rule = f"always_read.paths ({pat})"
            candidates.setdefault(("workflow", w["file"], rule), []).append({"ref": w["id"], "rule": rule, "callout": "always read"})
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
        "triage": triage, "apps": apps_out, "resources": resources, "edges": edges_out + tf_edges + wf_edges,
        "non_manifest_changes": nm, "terraform": tf, "terraform_plans": tf_plans, "workflows": wf,
        "jira": jira, "policy_hits": policy_hits, "notes": notes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect deterministic PR facts for pr-explainer")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--repo", help="owner/name (default: origin of the current checkout; required elsewhere)")
    ap.add_argument("--out", required=True, help="work directory for facts.json and diff.patch")
    args = ap.parse_args()
    repo = args.repo or repo_from_origin()
    if not repo:
        sys.exit("collect: the current directory is not a GitHub checkout; pass --repo owner/name")
    pr = json.loads(sh("gh", "api", f"repos/{repo}/pulls/{args.pr}"))
    files = gh_pages(f"repos/{repo}/pulls/{args.pr}/files?per_page=100")
    comments = gh_pages(f"repos/{repo}/issues/{args.pr}/comments?per_page=100")
    comments = trusted_comments(comments, sh("gh", "api", "user", "--jq", ".login").strip())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "diff.patch").write_text(sh("gh", "pr", "diff", str(args.pr), "-R", repo))
    trees = Trees(repo, args.pr, pr["base"]["sha"], pr["head"]["sha"])
    try:
        facts = collect(repo, pr, files, comments, trees)
    finally:
        trees.close()
    (out / "facts.json").write_text(json.dumps(facts, indent=2))
    changed = sum(r["action"] not in ("context", "generated") for r in facts["resources"])
    unrendered = [a["app"] for a in facts["apps"] if a["render"] != "rendered"]
    wf_changed = sum(w["action"] != "context" for w in facts["workflows"])
    print(f"collect: {changed} changed resources, {len(facts['terraform'])} terraform resources, "
          f"{wf_changed} workflow entries, {len(facts['edges'])} edges, "
          f"{len(facts['non_manifest_changes'])} non-manifest files, {len(facts['policy_hits'])} policy hits, "
          f"unrendered apps: {unrendered or 'none'}")
    print(f"collect: plans: {[p['environment'] or p['source'] for p in facts['terraform_plans']] or 'none'}, "
          f"ticket: {(facts['jira'] or {}).get('key') or 'none'}")
    print(f"collect: wrote {out / 'facts.json'} and {out / 'diff.patch'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
