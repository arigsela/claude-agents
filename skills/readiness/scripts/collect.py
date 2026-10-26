#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: one app-repo path in, <out>/facts.json out (spec §7.2–§7.4).

Usage: collect.py [<repo-path>] [--ref REF] [--entity kind:ns/name] [--deploy-ref REF] [--no-live] [--out DIR]

Reads the app repo at a commit (git archive, never the working tree); the catalog entity, its dependencies,
the CVE report and the scorecard from Backstage; the deploy folder from a temp clone of the deploy repo at the
revision Argo CD deploys; the cluster (kubectl get/top); and GitHub (gh api GET). Every source fails soft and
gets a status in meta.sources. Progress goes to stderr; the last stdout line is `facts: <out>/facts.json`.
Exits 1 when the path is not a git repo, the ref is not a commit, or several catalog entities match.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app_facts as af  # noqa: E402
import deploy_facts as df  # noqa: E402
import facts_lib as fl  # noqa: E402
import git_sources as gs  # noqa: E402
import live_facts as lf  # noqa: E402
from backstage import Backstage, BackstageError, Fetch, parse_ref, urllib_fetch  # noqa: E402
from readiness_model import SOURCES, fact, write_json  # noqa: E402

DEFAULT_BACKSTAGE_URL = "https://backstage.arigsela.com"
MANAGED_BY = "backstage.io/managed-by-location"
K8S_NAMESPACE = "backstage.io/kubernetes-namespace"
CVE_FINDINGS_CAP = 20
_SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
# url:https://github.com/<o>/<r>/(tree|blob)/<ref>/<path>/catalog-info.yaml; <path> is empty at the repo root.
_MANAGED = re.compile(r"^(?:url:)?https://github\.com/([^/\s]+)/([^/\s]+)/(?:tree|blob)/[^/\s]+/"
                      r"(?:(\S+)/)?[^/\s]+\.ya?ml$")
_NAMESPACE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


@dataclass
class Deps:
    fetch: Fetch = urllib_fetch
    run: lf.Run = lf.subprocess_run
    repo_url: Callable[[str], str] = gs.github_url
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)


class Ambiguous(Exception):
    """Several catalog entities carry this repo's slug; the caller must pick one with --entity."""

    def __init__(self, refs: list[str]):
        super().__init__(f"{len(refs)} catalog entities match; pass --entity")
        self.refs = refs


class InputError(Exception):
    """The repo path or ref cannot be read, so there is nothing to review."""


def parse_managed_by(location: str) -> tuple[str, str] | None:
    """(`owner/repo`, folder) from a GitHub `backstage.io/managed-by-location`; folder is "" at the repo root."""
    m = _MANAGED.match((location or "").strip())
    if not m:
        return None
    folder = m.group(3) or ""
    if folder and any(seg in ("", ".", "..") for seg in folder.split("/")):
        return None  # catalog data must not steer reads outside the deploy clone
    return f"{m.group(1)}/{m.group(2)}", folder


def _log(msg: str) -> None:
    print(f"collect: {msg}", file=sys.stderr, flush=True)


def _why(err: BaseException) -> str:
    """A short failure reason that cannot carry a secret: BackstageError's reason, else the exception class."""
    if isinstance(err, BackstageError):
        return err.reason
    if isinstance(err, subprocess.TimeoutExpired):
        return "timed out"
    if isinstance(err, subprocess.CalledProcessError):
        prog = Path(str(err.cmd[0])).name if isinstance(err.cmd, (list, tuple)) and err.cmd else "command"
        return f"{prog} exited {err.returncode}"
    return type(err).__name__


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def entity_ref(doc: dict) -> str:
    md = _d(doc.get("metadata"))
    return f"{str(doc.get('kind', '')).lower()}:{md.get('namespace') or 'default'}/{md.get('name')}"


def _qualify(ref: str, namespace: str) -> str:
    """A full `kind:ns/name`: Backstage defaults a relation's kind to component and its namespace to the entity's."""
    kind, sep, rest = str(ref).partition(":")
    if not sep:
        kind, rest = "component", str(ref)
    if "/" not in rest:
        rest = f"{namespace}/{rest}"
    return f"{kind.lower()}:{rest}"


def _without_userinfo(url: str) -> str:
    """`https://user:pw@host/x` -> `https://host/x`: credentials in BACKSTAGE_URL never reach facts.json (urllib
    cannot send them anyway)."""
    parts = urllib.parse.urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urllib.parse.urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def _ref_path(ref: str) -> str:
    return "/".join(urllib.parse.quote(p, safe="") for p in parse_ref(ref))


def _app_info(repo: Path, ref: str) -> dict:
    if ref.startswith("-"):
        raise InputError(f"unsafe ref: {ref!r}")
    try:
        probe = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-dir"], capture_output=True, text=True)
    except OSError:
        raise InputError("git is not installed") from None
    if not repo.is_dir() or probe.returncode != 0:
        raise InputError(f"not a git repository: {repo}")
    try:
        return gs.app_ref_info(repo, ref)
    except subprocess.CalledProcessError:
        raise InputError(f"{ref} is not a commit in {repo}") from None


def _app_step(repo: Path, sha: str, dest: Path) -> tuple[list[dict], str]:
    try:
        gs.export_commit(repo, sha, dest)
        return af.app_facts(dest), "ok"
    except Exception as err:
        return [], f"unavailable: {_why(err)}"


def _entity_fact(doc: dict, ref: str, url: str) -> dict:
    md, spec = _d(doc.get("metadata")), _d(doc.get("spec"))
    ns = str(md.get("namespace") or "default")
    value = {"ref": ref, "owner": spec.get("owner"), "lifecycle": spec.get("lifecycle"), "system": spec.get("system"),
             "depends_on": [_qualify(r, ns) for r in _l(spec.get("dependsOn")) if isinstance(r, str)],
             "provides_apis": [str(r) for r in _l(spec.get("providesApis"))],
             "annotations": {str(k): v for k, v in _d(md.get("annotations")).items()}}
    return fact("backstage.entity", "backstage", value, url)


def _entity_step(bs: Backstage, slug: str | None, entity: str | None) -> tuple[dict | None, list[dict], str]:
    """(entity doc or None, facts, backstage status). Raises Ambiguous when several entities carry the slug."""
    try:
        if entity:
            ref = _qualify(entity, "default")
            doc = bs.entity(ref)
            if doc is None:
                _log(f"backstage: {ref} is not in the catalog")
        elif slug:
            # By project-slug, and by a component named like the repo: a stray entity that happens to carry the
            # slug (the stock create-app scaffold) must not be picked silently over the real one.
            by_slug = {entity_ref(e): e for e in bs.entities_by_slug(slug) if isinstance(e, dict)}
            by_name = {entity_ref(e): e for e in bs.components_named(slug.rsplit("/", 1)[-1])
                       if isinstance(e, dict)}
            items = {**by_name, **by_slug}
            if len(items) > 1:
                raise Ambiguous(sorted(items))
            doc = next(iter(items.values()), None)
            if doc is not None and not by_slug:
                _log(f"backstage: matched {entity_ref(doc)} by name: no entity has github.com/project-slug {slug}")
        else:
            return None, [], "skipped: no GitHub remote"
    except Ambiguous:
        raise
    except Exception as err:
        return None, [], f"unavailable: {_why(err)}"
    if doc is None:
        query = urllib.parse.urlencode({"filter": f"metadata.annotations.github.com/project-slug={slug}"})
        url = (bs.url(f"/api/catalog/entities/by-name/{_ref_path(ref)}") if entity
               else bs.url(f"/api/catalog/entities/by-query?{query}"))
        return None, [fact("backstage.entity", "backstage", None, url)], "ok"
    ref = entity_ref(doc)
    return doc, [_entity_fact(doc, ref, bs.url(f"/api/catalog/entities/by-name/{_ref_path(ref)}"))], "ok"


def _dependency_facts(bs: Backstage, refs: list[str]) -> list[dict]:
    out = []
    for ref in refs:
        try:
            doc = bs.entity(ref)
            lifecycle = _d(_d(doc).get("spec")).get("lifecycle")
            value = {"ref": ref, "lifecycle": str(lifecycle) if lifecycle else None,
                     "error": None if doc is not None else "not found"}
        except Exception as err:
            value = {"ref": ref, "lifecycle": None, "error": _why(err)}
        out.append(fact(f"backstage.dependency.{ref}", "backstage", value,
                        bs.url(f"/api/catalog/entities/by-name/{_ref_path(ref)}")))
    return out


def _target_revision(found: tuple[str, dict] | None, repo: str, folder: str) -> str | None:
    if not found:
        return None
    for src in fl.app_sources(found[1]):
        if str(src.get("path", "")).rstrip("/") == folder and fl.same_repo(src.get("repoURL"), repo):
            rev = src.get("targetRevision")
            return None if rev in (None, "") else str(rev)
    return None


def _escapes(root: Path, folder: str) -> bool:
    """True when `folder`, or a symlink inside it, resolves outside the checkout at `root`."""
    base = root.resolve()
    top = root / folder
    if not top.resolve().is_relative_to(base):
        return True
    if top.is_dir():
        for p in top.rglob("*"):
            if p.is_symlink() and not p.resolve().is_relative_to(base):
                return True
    return False


def _deploy_step(ent: dict, app_slug: str | None, deploy_ref: str | None, deps: Deps,
                 tmp: Path) -> tuple[list[dict], str, dict | None]:
    """(deploy facts, deploy status, meta.deploy)."""
    annotations = _d(_d(ent.get("metadata")).get("annotations"))
    location = annotations.get(MANAGED_BY)
    namespace = annotations.get(K8S_NAMESPACE)
    if not location:
        return [], "unavailable: no managed-by-location", None
    target = parse_managed_by(str(location))
    if target is None:
        return [], "unavailable: managed-by-location is not a GitHub file URL", None
    repo, folder = target
    if app_slug and repo.lower() == app_slug.lower():
        return [], "unavailable: catalog entry lives in the app repo", None
    if not folder:
        return [], f"unavailable: catalog entry sits at the root of {repo}", None
    meta = {"repo": repo, "folder": folder, "ref": deploy_ref, "sha": None, "application_file": None}
    stage = "clone failed"
    try:
        url = deps.repo_url(repo)
        root = tmp / "deploy"
        sha = gs.remote_checkout(url, "HEAD", root)
        dflt = gs.default_branch(url)
        found = df.find_application(root, repo, folder)
        meta["application_file"] = found[0] if found else None
        target_rev = _target_revision(found, repo, folder)
        rev = deploy_ref or (target_rev if target_rev and target_rev not in ("HEAD", dflt) else None)
        if rev:
            meta["ref"] = rev
            stage = f"checkout of {rev!r} failed"  # repr: rev may come from repo data (targetRevision)
            root = tmp / "deploy-at-rev"
            sha = gs.remote_checkout(url, rev, root)
        meta.update(ref=rev or dflt or "HEAD", sha=sha)
        stage = "deploy facts failed"
        if _escapes(root, folder):
            return [], "unavailable: unsafe folder", meta
        if not (root / folder).is_dir():  # else every deploy check reads an empty folder: no runbook, no workloads
            return [], f"unavailable: folder not found ({folder})", meta
        work = tmp / "render"
        work.mkdir(exist_ok=True)
        return (df.deploy_facts(root, repo, folder, work, namespace=str(namespace) if namespace else None),
                "ok", meta)
    except Exception as err:
        return [], f"unavailable: {stage} ({_why(err)})", meta


def _cve_fact(bs: Backstage, images: list[str]) -> dict:
    try:
        r = _d(bs.cve_report(images))
        totals = _d(r.get("totals"))
        findings = sorted((f for f in _l(r.get("findings")) if isinstance(f, dict)),
                          key=lambda f: _SEVERITY.get(str(f.get("severity", "")).upper(), len(_SEVERITY)))
        value = {"ok": r.get("ok") is True, "scanned_at": r.get("scannedAt"),
                 "matched": [str(x) for x in _l(r.get("matchedRefs"))],
                 "unmatched": [str(x) for x in _l(r.get("unmatchedRefs"))],
                 # criticalNoFix / kevFixable since portal v1.7.0; None (not 0) from an older portal
                 "totals": {"critical": totals.get("critical"), "high": totals.get("high"),
                            "critical_no_fix": totals.get("criticalNoFix"), "kev_fixable": totals.get("kevFixable")},
                 "findings": [{k: f.get(k) for k in ("id", "severity", "pkg", "fixed", "image")}
                              for f in findings[:CVE_FINDINGS_CAP]],
                 "error": None}
    except Exception as err:  # the catalog was read; only the report failed, so say so on this fact
        value = {"ok": False, "scanned_at": None, "matched": [], "unmatched": list(images),
                 "totals": {"critical": None, "high": None, "critical_no_fix": None, "kev_fixable": None},
                 "findings": [], "error": _why(err)}
    return fact("backstage.cve", "backstage", value, "POST " + bs.url("/api/cve/report"))


def _scorecard_step(bs: Backstage, ref: str) -> tuple[list[dict], str]:
    url = bs.url(f"/api/scorecard/metrics/catalog/{_ref_path(ref)}")
    try:
        rows = bs.scorecard(ref)
    except Exception as err:
        return [], f"unavailable: {_why(err)}"
    if rows is None:
        return [], "not installed (404)"
    if not isinstance(rows, list):
        return [], "unavailable: unexpected response"
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        res = _d(row.get("result"))
        value = {"value": res.get("value"), "evaluation": _d(res.get("thresholdResult")).get("evaluation"),
                 "status": row.get("status"), "error": row.get("error"), "timestamp": res.get("timestamp")}
        out.append(fact(f"scorecard.{row['id']}", "scorecard", value, url))
    return out, "ok"


def _cluster_step(namespace, workloads: list[str], run: lf.Run) -> tuple[list[dict], str]:
    if not namespace:
        return [], "unavailable: no namespace"
    if not _NAMESPACE.match(str(namespace)):
        return [], "unavailable: invalid namespace"
    if not workloads:  # pods are matched to rendered workloads (§7.3); with none there is nothing to read
        return [], "unavailable: no rendered workloads"
    try:
        return lf.cluster_facts(str(namespace), workloads, run)
    except Exception as err:
        return [], f"unavailable: {_why(err)}"


def collect(repo_path: Path, out: Path, ref: str = "HEAD", entity: str | None = None,
            deploy_ref: str | None = None, live: bool = True, deps: Deps | None = None) -> dict:
    """Collect every source into a facts doc and write it to `out/facts.json`. Raises InputError when the repo
    or ref cannot be read and Ambiguous when several catalog entities match; every other failure is a status."""
    deps = deps or Deps()
    repo_path, out = Path(repo_path), Path(out)
    info = _app_info(repo_path, ref)
    base = _without_userinfo(deps.env.get("BACKSTAGE_URL") or DEFAULT_BACKSTAGE_URL).rstrip("/")
    bs = Backstage(base, deps.env.get("BACKSTAGE_TOKEN") or None, fetch=deps.fetch)
    status: dict[str, str] = {}
    facts: list[dict] = []
    meta: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "backstage_url": base, "entity_ref": None, "app": info, "deploy": None}
    tmp = Path(tempfile.mkdtemp(prefix="readiness-"))
    try:
        _log(f"app: {info['slug'] or repo_path} at {info['sha'][:7]}")
        app, status["app"] = _app_step(repo_path, info["sha"], tmp / "app")
        facts += app

        _log("backstage: catalog entity")
        ent, ent_facts, status["backstage"] = _entity_step(bs, info["slug"], entity)
        facts += ent_facts
        if ent is not None:
            meta["entity_ref"] = ent_facts[0]["value"]["ref"]
            facts += _dependency_facts(bs, ent_facts[0]["value"]["depends_on"])

        deploy: list[dict] = []
        if ent is not None:
            _log("deploy: temp clone of the deploy repo")
            deploy, status["deploy"], meta["deploy"] = _deploy_step(ent, info["slug"], deploy_ref, deps, tmp)
        elif status["backstage"] == "ok":
            status["deploy"] = "unavailable: not in catalog"
        elif status["backstage"].startswith("skipped"):
            status["deploy"] = "unavailable: no GitHub remote (pass --entity)"
        else:
            status["deploy"] = "unavailable: backstage unavailable"
        facts += deploy

        images = df.image_refs(deploy)
        if images:
            _log(f"backstage: CVE report for {len(images)} images")
            facts.append(_cve_fact(bs, images))

        if ent is not None:
            _log("scorecard")
            card, status["scorecard"] = _scorecard_step(bs, meta["entity_ref"])
            facts += card
        elif status["backstage"] == "ok":
            status["scorecard"] = "skipped: not in catalog"
        elif status["backstage"].startswith("skipped"):
            status["scorecard"] = status["backstage"]
        else:
            status["scorecard"] = "unavailable: backstage unavailable"

        if not live:
            status["cluster"] = "skipped: --no-live"
        else:
            namespace = (_d(_d(_d(ent).get("metadata")).get("annotations")).get(K8S_NAMESPACE)
                         or df.namespace_of(deploy))
            _log(f"cluster: namespace {namespace or '(none)'}")
            live_facts, status["cluster"] = _cluster_step(namespace, df.workload_refs(deploy), deps.run)
            facts += live_facts

        if not info["slug"]:
            status["github"] = "skipped: no GitHub remote"
        else:
            _log(f"github: {info['slug']}")
            try:
                gh, status["github"] = lf.github_facts(info["slug"], info["default_branch"], deps.run)
                facts += gh
            except Exception as err:
                status["github"] = f"unavailable: {_why(err)}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    meta["sources"] = {s: status.get(s, "unavailable: not collected") for s in SOURCES}
    doc = {"meta": meta, "facts": facts}
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "facts.json", doc)
    return doc


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    ap = argparse.ArgumentParser(prog="collect.py", description="Collect production-readiness facts for one app repo")
    ap.add_argument("repo_path", nargs="?", default=".", metavar="repo-path",
                    help="local checkout of the app repo (default: the current directory)")
    ap.add_argument("--ref", default="HEAD", help="app commit to review (default: HEAD); committed trees only")
    ap.add_argument("--entity", help="catalog entity kind:ns/name, when the repo is not or ambiguously in the catalog")
    ap.add_argument("--deploy-ref", help="deploy-repo revision to review (default: what Argo CD deploys)")
    ap.add_argument("--no-live", action="store_true", help="skip the cluster reads")
    ap.add_argument("--out", help="directory for facts.json (default: a new temp directory)")
    args = ap.parse_args(argv)
    made = args.out is None
    out = Path(tempfile.mkdtemp(prefix="readiness-")) if made else Path(args.out).expanduser()
    try:
        doc = collect(Path(args.repo_path).expanduser(), out, args.ref, args.entity, args.deploy_ref,
                      not args.no_live, deps)
    except Ambiguous as err:
        _log("several catalog entities match this repo; pass --entity with one of:")
        for ref in err.refs:
            print(f"  {ref}", file=sys.stderr)
    except InputError as err:
        _log(str(err))
    else:
        for source, state in doc["meta"]["sources"].items():
            _log(f"{source}: {state}")
        print(f"facts: {out / 'facts.json'}")
        return 0
    if made:
        shutil.rmtree(out, ignore_errors=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
