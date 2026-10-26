#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""readiness: the rule checks (spec §7.5, plan Task 8's rule table): RULES maps a check id to a function that
decides its status from the facts. evaluate.py runs them and re-exports RULES, Outcome and worst.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_facts import parse_quantity_cpu, parse_quantity_mem  # noqa: E402
from readiness_model import Facts  # noqa: E402

Outcome = tuple[str, str, list[str]]  # (status, reason, fact ids)

NEAR_LIMIT = 0.9
OVERPROVISION_RATIO = 4
OVERPROVISION_MIN_CPU_M = 100
OVERPROVISION_MIN_MEM_MI = 128
IDLE_RATIO = 0.10
NAMES_CAP = 5
ERROR_CAP = 120

_RANK = {"pass": 0, "unknown": 1, "partial": 2, "fail": 3}
_SHOW = {"fail": 0, "partial": 1, "unknown": 2, "n/a": 3, "pass": 4}
_EVAL = {"success": "pass", "warning": "partial", "error": "fail"}
_C, _W, _U = "deploy.container.", "deploy.workload.", "cluster.usage."
_UNITS = {"cpu": ("cpu_m", "m"), "memory": ("memory_mi", "Mi")}
_FLOORS = {"cpu": OVERPROVISION_MIN_CPU_M, "memory": OVERPROVISION_MIN_MEM_MI}


def worst(statuses: list[str]) -> str:
    """fail > partial > unknown > pass; n/a counts only when every status is n/a (or there are none)."""
    ranked = [s for s in statuses if s != "n/a"]
    return max(ranked, key=_RANK.__getitem__) if ranked else "n/a"


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _names(items: list[str]) -> str:
    more = len(items) - NAMES_CAP
    return "; ".join(items[:NAMES_CAP]) + (f"; and {more} more" if more > 0 else "")


def _n(k: int, noun: str) -> str:
    return f"{k} {noun}{'' if k == 1 else 's'}"


def _ids(facts: list[dict]) -> list[str]:
    return list(dict.fromkeys(x["id"] for x in facts))


def _clip(s, n: int = ERROR_CAP) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def _unavailable(f: Facts, *sources: str) -> Outcome | None:
    for s in sources:
        if not f.ok(s):
            return "unknown", f"{s} unavailable: {f.status(s).removeprefix('unavailable: ')}", []
    return None


def _combine(items: list[Outcome], passed: str) -> Outcome:
    """Per-item outcomes -> one: the worst status, the non-pass notes (worst first) and their fact ids."""
    status = worst([s for s, _, _ in items])
    shown = sorted((x for x in items if x[0] != "pass"), key=lambda x: _SHOW[x[0]])
    notes = ([passed] if status == "pass" else []) + [n for _, n, _ in shown]
    cited = items if status in ("pass", "n/a") else shown
    return status, _names(notes), list(dict.fromkeys(i for _, _, ids in cited for i in ids))


def _rendered(f: Facts, prefix: str, what: str, keep: Callable[[dict], bool] | None = None):
    """(gate, items): gate is an unknown Outcome when deploy is unavailable or rendered nothing of this kind."""
    gate = _unavailable(f, "deploy")
    if gate:
        return gate, []
    items = [x for x in f.prefix(prefix) if isinstance(x["value"], dict) and (keep is None or keep(x["value"]))]
    if items:
        return None, items
    app = f.get("deploy.application")
    where = _d(app["value"] if app else None).get("path") or "the deploy folder"
    return ("unknown", f"no {what} rendered from {where}", [app["id"]] if app else []), []


def _name(x: dict, prefix: str) -> str:
    return x["id"][len(prefix):]


def _metric(f: Facts, mid: str) -> tuple[str | None, str, list[str]]:
    """(evaluation or None when unreadable, a note, fact ids) for scorecard metric `mid`."""
    gate = _unavailable(f, "scorecard")
    if gate:
        return None, gate[1], []
    m = f.get(f"scorecard.{mid}")
    if m is None:
        return None, f"scorecard has no {mid} metric", []
    v = _d(m["value"])
    if v.get("status") == "error" or v.get("value") is None or not v.get("evaluation"):
        err = v.get("error")
        return None, f"scorecard {mid} errored" + (f": {_clip(err)}" if err else ""), [m["id"]]
    return str(v["evaluation"]), f"scorecard {mid} is {v['value']} ({v['evaluation']})", [m["id"]]


def _selects(selector, labels) -> bool:
    lab = _d(labels)
    return all(k in lab and str(lab[k]) == str(v) for k, v in _d(selector).items())


def _qty(kind: str, v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return (parse_quantity_cpu if kind == "cpu" else parse_quantity_mem)(str(v))
    except ValueError:
        return None


# --- Operational excellence ---------------------------------------------------------------------------------

def ops_catalog(f: Facts) -> Outcome:
    gate = _unavailable(f, "backstage")
    if gate:
        return gate
    e = f.get("backstage.entity")
    if e is None:
        return "unknown", "no catalog lookup was recorded", []
    v = e["value"]
    if not isinstance(v, dict):
        return "fail", "not in the catalog", [e["id"]]
    missing = [k for k in ("owner", "lifecycle", "system") if not v.get(k)]
    if missing:
        return "partial", f"{v.get('ref')} has no {', '.join(missing)}", [e["id"]]
    return "pass", f"{v['ref']}: owner {v['owner']}, lifecycle {v['lifecycle']}, system {v['system']}", [e["id"]]


def ops_runbook(f: Facts) -> Outcome:
    rb = f.get("deploy.file.runbook")
    if f.ok("deploy") and rb:
        v = _d(rb["value"])
        if v.get("exists"):
            return "pass", f"{v.get('path')} exists", [rb["id"]]
        return "fail", f"no runbook at {v.get('path')}", [rb["id"]]
    deploy_note = (_unavailable(f, "deploy") or ("", "deploy has no runbook fact", []))[1]
    evaluation, note, ids = _metric(f, "filecheck.runbook")
    if evaluation == "exist":
        return "pass", f"{note}; {deploy_note}", ids
    if evaluation == "missing":
        return "fail", f"{note}; {deploy_note}", ids
    return "unknown", f"{deploy_note}; {note}", ids


def ops_docs(f: Facts) -> Outcome:
    gate = _unavailable(f, "app")
    if gate:
        return gate
    readme, docs = f.get("app.file.readme"), f.get("deploy.file.docs")
    has_readme = bool(readme and _d(readme["value"]).get("exists"))
    ids = [readme["id"]] if readme else []
    if not (f.ok("deploy") and docs):
        note = (_unavailable(f, "deploy") or ("", "deploy has no docs.md fact", []))[1]
        if has_readme:
            return "partial", f"README exists; docs.md not checked ({note})", ids
        return "fail", f"no README in the app repo; docs.md not checked ({note})", ids
    has_docs, path = bool(_d(docs["value"]).get("exists")), _d(docs["value"]).get("path") or "docs.md"
    ids.append(docs["id"])
    if has_readme and has_docs:
        return "pass", f"README and {path} exist", ids
    if has_readme or has_docs:
        return "partial", f"no {path} in the deploy folder" if has_readme else "no README in the app repo", ids
    return "fail", f"no README in the app repo and no {path}", ids


def ops_open_prs(f: Facts) -> Outcome:
    evaluation, note, ids = _metric(f, "github.openPRs")
    return _EVAL.get(evaluation or "", "unknown"), note, ids


# --- Security -----------------------------------------------------------------------------------------------

def sec_image_digest(f: Facts) -> Outcome:
    gate, cs = _rendered(f, _C, "containers")
    if gate:
        return gate
    bad = [c for c in cs if not c["value"].get("image_pinned")]
    if bad:
        return "fail", _names([f"{_name(c, _C)} uses {c['value'].get('image')} (no digest)" for c in bad]), _ids(bad)
    return "pass", f"every container image is pinned by digest ({_n(len(cs), 'container')})", _ids(cs)


def sec_base_digest(f: Facts) -> Outcome:
    gate = _unavailable(f, "app")
    if gate:
        return gate
    froms = f.prefix("app.dockerfile.from.")
    if not froms:
        return "n/a", ("the Dockerfile has no external base image" if f.get("app.dockerfile.user")
                       else "no Dockerfile"), []
    bad = [x for x in froms if not _d(x["value"]).get("pinned")]
    if bad:
        return "fail", _names([f"{x['evidence']} FROM {_d(x['value']).get('image')} has no digest"
                               for x in bad]), _ids(bad)
    return "pass", f"every Dockerfile base image is pinned by digest ({_n(len(froms), 'FROM')})", _ids(froms)


def _nonroot(c: dict, pods: dict) -> bool:
    s = _d(c["value"].get("security"))
    own, uid = s.get("runAsNonRoot"), s.get("runAsUser")
    effective = own if own is not None else pods.get(str(c["value"].get("workload")))
    return effective is True or (isinstance(uid, int) and not isinstance(uid, bool) and uid > 0)


def sec_nonroot(f: Facts) -> Outcome:
    gate, cs = _rendered(f, _C, "containers")
    if gate:
        return gate
    pods = {_name(w, _W): _d(w["value"]).get("pod_run_as_non_root") for w in f.prefix(_W)}
    bad = [c for c in cs if not _nonroot(c, pods)]
    if not bad:
        return "pass", f"every container runs as non-root ({_n(len(cs), 'container')})", _ids(cs)
    reason = _names([f"{_name(c, _C)} sets neither runAsNonRoot nor a non-zero runAsUser" for c in bad])
    user = f.get("app.dockerfile.user")
    if user:
        u = _d(user["value"]).get("user")
        reason += f" (Dockerfile USER {u})" if u else " (the Dockerfile sets no USER)"
    return "fail", reason, _ids(bad) + ([user["id"]] if user else [])


def _hardening_gaps(c: dict) -> list[str]:
    s = _d(c["value"].get("security"))
    gaps = [] if s.get("readOnlyRootFilesystem") is True else ["readOnlyRootFilesystem"]
    gaps += [] if s.get("allowPrivilegeEscalation") is False else ["allowPrivilegeEscalation: false"]
    return gaps + ([] if "ALL" in [str(x).upper() for x in _l(s.get("capabilities_drop"))] else ["drop ALL"])


def sec_hardening(f: Facts) -> Outcome:
    gate, cs = _rendered(f, _C, "containers")
    if gate:
        return gate
    gaps = {c["id"]: _hardening_gaps(c) for c in cs}
    bad = [c for c in cs if gaps[c["id"]]]
    if not bad:
        return "pass", f"every container is hardened ({_n(len(cs), 'container')})", _ids(cs)
    reason = _names([f"{_name(c, _C)} lacks {', '.join(gaps[c['id']])}" for c in bad])
    return ("fail" if len(bad) == len(cs) else "partial"), reason, _ids(bad)


def sec_netpol(f: Facts) -> Outcome:
    gate, ws = _rendered(f, _W, "workloads")
    if gate:
        return gate
    pols = f.prefix("deploy.object.NetworkPolicy/")
    hits = {w["id"]: [p for p in pols if _selects(_d(p["value"]).get("pod_selector"), w["value"].get("pod_labels"))]
            for w in ws}
    bad = [w for w in ws if not hits[w["id"]]]
    if not bad:
        return "pass", "a NetworkPolicy selects every workload", _ids(ws + [p for w in ws for p in hits[w["id"]]])
    lead = "no NetworkPolicy in the deploy folder; " if not pols else ""
    reason = lead + "no NetworkPolicy selects " + ", ".join(_name(w, _W) for w in bad)
    return ("fail" if len(bad) == len(ws) else "partial"), reason, _ids(bad)


def sec_secrets(f: Facts) -> Outcome:
    gate = _unavailable(f, "deploy")
    if gate:
        return gate
    bad = [s for s in f.prefix("deploy.object.Secret/") if _d(s["value"]).get("has_data")]
    if bad:  # key names only; facts never hold values
        return "fail", _names([f"{_name(s, 'deploy.object.')} at {s['evidence']} holds data in Git (keys: "
                               f"{', '.join(map(str, _l(s['value'].get('keys'))))})" for s in bad]), _ids(bad)
    gate, _ = _rendered(f, _W, "workloads")
    if gate:
        return gate
    es = f.prefix("deploy.object.ExternalSecret/")
    tail = f"; secrets come from {', '.join(_name(x, 'deploy.object.') for x in es)}" if es else ""
    return "pass", "no Secret manifest holds data" + tail, _ids(es)


def sec_cve(f: Facts) -> Outcome:
    gate = _unavailable(f, "backstage", "deploy")
    if gate:
        return gate
    cve = f.get("backstage.cve")
    if cve is None:
        return "unknown", "no CVE report: no rendered images to scan", []
    v = _d(cve["value"])
    totals, findings = _d(v.get("totals")), _l(v.get("findings"))
    parts: list[tuple[str, str]] = []
    for sev, status in (("critical", "fail"), ("high", "partial")):
        n = totals.get(sev)
        if isinstance(n, int) and n > 0:
            listed = [f"{x.get('id')} in {x.get('pkg')} (fixed {x.get('fixed')})" for x in map(_d, findings)
                      if str(x.get("severity", "")).lower() == sev]
            parts.append((status, f"{n} fixable {sev}" + (": " + _names(listed) if listed else "")))
    if v.get("ok") is not True:
        parts.append(("unknown", "the CVE report failed" + (f": {_clip(v['error'])}" if v.get("error") else "")))
    elif _l(v.get("unmatched")):
        parts.append(("unknown", "not scanned: " + _names([str(x) for x in v["unmatched"]])))
    elif not all(isinstance(totals.get(k), int) for k in ("critical", "high")):
        parts.append(("unknown", "the CVE report gave no critical/high totals"))
    if not parts:
        return "pass", f"no fixable critical or high CVEs in {len(_l(v.get('matched')))} scanned images", [cve["id"]]
    parts.sort(key=lambda p: _SHOW[p[0]])
    return worst([s for s, _ in parts]), "; ".join(n for _, n in parts), [cve["id"]]


def sec_dependabot(f: Facts) -> Outcome:
    da = f.get("github.dependabot_alerts")
    ids = [da["id"]] if da else []
    enabled = _d(da["value"] if da else None).get("enabled")
    if enabled is False:
        return "fail", "Dependabot alerts are off", ids
    if enabled is not True:
        gate = _unavailable(f, "github")
        http = _d(da["value"]).get("http") if da else None
        return "unknown", gate[1] if gate else f"Dependabot alerts setting unknown (HTTP {http})", ids
    gate = _unavailable(f, "scorecard")
    if gate:
        return "unknown", f"Dependabot alerts are on; {gate[1]}", ids
    items: list[Outcome] = []
    for sev in ("Critical", "High"):
        found = f.match([f"scorecard.dependabot.*{sev}"])
        if not found:
            items.append(("unknown", f"scorecard has no dependabot {sev.lower()} metric", []))
        for mid in found:
            evaluation, note, mids = _metric(f, mid[len("scorecard."):])
            items.append((_EVAL.get(evaluation or "", "unknown"), note, mids))
    status, reason, mids = _combine(items, "open critical and high alerts are within threshold")
    return status, f"Dependabot alerts are on; {reason}", ids + mids


def sec_dep_updates(f: Facts) -> Outcome:
    gate = _unavailable(f, "app")
    if gate:
        return gate
    files = [x for x in (f.get("app.file.dependabot"), f.get("app.file.renovate")) if x]
    hit = next((x for x in files if _d(x["value"]).get("exists")), None)
    if hit:
        return "pass", f"{hit['value'].get('path')} configures dependency updates", [hit["id"]]
    if not files:
        return "unknown", "no dependency-update file facts", []
    return "fail", "no Dependabot or Renovate config (.github/dependabot.yml, renovate.json)", _ids(files)


def _workflows(f: Facts):
    gate = _unavailable(f, "app")
    if gate:
        return gate, []
    wfs = [w for w in f.prefix("app.workflow.") if isinstance(w["value"], dict)]
    return (None, wfs) if wfs else (("n/a", "no GitHub Actions workflows", []), [])


def sec_actions_pinned(f: Facts) -> Outcome:
    gate, wfs = _workflows(f)
    if gate:
        return gate
    bad = [(w, u) for w in wfs for u in map(_d, _l(w["value"].get("uses"))) if not u.get("pinned")]
    if bad:
        where = [f"{w['value'].get('file')}" + (f":{u['line']}" if u.get("line") else "") + f" uses {u.get('ref')}"
                 for w, u in bad]
        return "fail", _names(where), _ids([w for w, _ in bad])
    n = sum(len(_l(w["value"].get("uses"))) for w in wfs)
    return "pass", f"every uses: ref is pinned by SHA ({_n(n, 'ref')} in {_n(len(wfs), 'workflow')})", _ids(wfs)


def _perm_gap(v: dict) -> str | None:
    if v.get("write_all"):
        return "grants write-all"
    without = _l(v.get("jobs_without_permissions"))
    if v.get("permissions") is None and without:
        return f"has no top-level permissions and jobs {', '.join(map(str, without))} set none"
    return None


def sec_token_perms(f: Facts) -> Outcome:
    gate, wfs = _workflows(f)
    if gate:
        return gate
    gaps = {w["id"]: _perm_gap(w["value"]) for w in wfs}
    bad = [w for w in wfs if gaps[w["id"]]]
    if not bad:
        return "pass", f"every workflow declares permissions ({_n(len(wfs), 'workflow')})", _ids(wfs)
    reason = _names([f"{w['value'].get('file')} {gaps[w['id']]}" for w in bad])
    all_bad = len(bad) == len(wfs) or any(w["value"].get("write_all") for w in bad)
    return ("fail" if all_bad else "partial"), reason, _ids(bad)


def sec_sa_token(f: Facts) -> Outcome:
    gate, ws = _rendered(f, _W, "workloads")
    if gate:
        return gate
    bad = [w for w in ws if w["value"].get("automount_sa_token") is not False
           and w["value"].get("service_account") in (None, "", "default")]
    if bad:
        return "partial", _names([f"{_name(w, _W)} mounts the default service account's token"
                                  for w in bad]), _ids(bad)
    return "pass", "every workload turns off the token mount or uses a dedicated service account", _ids(ws)


def sec_repo_hygiene(f: Facts) -> Outcome:
    gate = _unavailable(f, "app")
    if gate:
        return gate
    items, ids = [], []
    for key, label in (("codeowners", "CODEOWNERS"), ("security", "SECURITY.md")):
        x = f.get(f"app.file.{key}")
        ids += [x["id"]] if x else []
        items.append((label, bool(x and _d(x["value"]).get("exists"))))
    bp = f.get("github.branch_protection")
    protected = _d(bp["value"] if bp else None).get("protected")
    note = ""
    if protected is None:
        gate = _unavailable(f, "github")
        why = gate[1] if gate else f"HTTP {_d(bp['value']).get('http')}" if bp else "not read"
        note = f"; branch protection unknown ({why})"
    else:
        ids.append(bp["id"])
        items.append(("default-branch protection", protected is True))
    have, lack = [n for n, ok in items if ok], [n for n, ok in items if not ok]
    if not lack:
        return "pass", f"{', '.join(have)} in place{note}", ids
    reason = f"missing {', '.join(lack)}" + (f"; has {', '.join(have)}" if have else "") + note
    return ("partial" if have else "fail"), reason, ids


# --- Reliability --------------------------------------------------------------------------------------------

def rel_probes(f: Facts) -> Outcome:
    gate, cs = _rendered(f, _C, "non-init containers", keep=lambda v: not v.get("init"))
    if gate:
        return gate
    items = []
    for c in cs:
        missing = [k for k in ("readiness", "liveness") if not _d(c["value"].get("probes")).get(k)]
        items.append(("fail", f"{_name(c, _C)} has no {' or '.join(missing)} probe", [c["id"]]) if missing
                     else ("pass", "", [c["id"]]))
    return _combine(items, f"every container has readiness and liveness probes ({_n(len(cs), 'container')})")


def rel_resources(f: Facts) -> Outcome:
    gate, cs = _rendered(f, _C, "containers")
    if gate:
        return gate
    items = []
    for c in cs:
        r = _d(c["value"].get("resources"))
        missing = [f"{a}.{b}" for a in ("requests", "limits") for b in ("cpu", "memory")
                   if _d(r.get(a)).get(b) in (None, "")]
        items.append(("fail", f"{_name(c, _C)} has no {', '.join(missing)}", [c["id"]]) if missing
                     else ("pass", "", [c["id"]]))
    return _combine(items, f"every container sets CPU and memory requests and limits ({_n(len(cs), 'container')})")


def _replicas(w: dict, hpas: list[dict]) -> int:
    try:
        n = int(w["value"].get("replicas") or 1)
    except (TypeError, ValueError):
        n = 1
    ref = _name(w, _W)
    for h in hpas:  # an HPA's minReplicas is the floor when the manifest leaves replicas to it
        v = _d(h["value"])
        if v.get("target") == ref and isinstance(v.get("min"), int):
            n = max(n, v["min"])
    return n


def rel_pdb(f: Facts) -> Outcome:
    gate, ws = _rendered(f, _W, "workloads")
    if gate:
        return gate
    hpas = f.prefix("deploy.object.HorizontalPodAutoscaler/")
    pdbs = f.prefix("deploy.object.PodDisruptionBudget/")
    multi = [(w, n) for w in ws if (n := _replicas(w, hpas)) >= 2]
    if not multi:
        return "n/a", "every workload runs one replica", _ids(ws)
    items = []
    for w, n in multi:
        hit = [p for p in pdbs if _selects(_d(p["value"]).get("selector"), w["value"].get("pod_labels"))]
        items.append(("pass", "", [w["id"]] + _ids(hit)) if hit else
                     ("fail", f"{_name(w, _W)} runs {n} replicas with no PodDisruptionBudget selecting it", [w["id"]]))
    return _combine(items, "a PodDisruptionBudget selects every workload with two or more replicas")


def rel_restarts(f: Facts) -> Outcome:
    gate = _unavailable(f, "cluster")
    if gate:
        return gate
    ws = f.prefix("cluster.workload.")
    if not ws:
        return "unknown", "no rendered workloads were looked up live", []
    pods = f.prefix("cluster.pod.")
    items = []
    for w in ws:
        ref = _name(w, "cluster.workload.")
        mine = [p for p in pods if _d(p["value"]).get("workload") == ref]
        if not _d(w["value"]).get("found"):
            items.append(("unknown", f"{ref}: not found live", [w["id"]]))
            continue
        if not mine:
            items.append(("unknown", f"{ref}: no pods found live", [w["id"]]))
            continue
        restarts = sum(r for p in mine if isinstance(r := _d(p["value"]).get("restarts"), int))
        oom = [p for p in mine if _d(p["value"]).get("oom_killed")]
        count = f"{restarts} restarts across {len(mine)} pods"
        if oom:
            items.append(("fail", f"{ref}: OOMKilled in {', '.join(_name(p, 'cluster.pod.') for p in oom)}, {count}",
                          [w["id"]] + _ids(oom)))
        else:
            items.append(("partial" if restarts else "pass", f"{ref}: {count}", [w["id"]] + _ids(mine)))
    return _combine(items, f"no restarts or OOMKills ({_n(len(ws), 'workload')} running)")


def rel_dependencies(f: Facts) -> Outcome:
    gate = _unavailable(f, "backstage")
    if gate:
        return gate
    deps = f.prefix("backstage.dependency.")
    if not deps:
        return "n/a", "no dependsOn entities", []
    items = []
    for d in deps:
        v = _d(d["value"])
        ref, life = v.get("ref") or _name(d, "backstage.dependency."), v.get("lifecycle")
        if v.get("error"):
            why = "not found in the catalog" if v["error"] == "not found" else f"lookup failed ({_clip(v['error'])})"
            items.append(("unknown", f"{ref}: {why}", [d["id"]]))
        elif life is None:
            items.append(("n/a", f"{ref} has no lifecycle", [d["id"]]))
        else:
            items.append(("pass" if life == "production" else "partial", f"{ref} is {life}", [d["id"]]))
    return _combine(items, "every dependsOn entity with a lifecycle is production")


# --- Performance, cost, sustainability (live usage) ---------------------------------------------------------

def _usage(f: Facts):
    """(gate, [(name, usage fact, container fact or None)])."""
    gate = _unavailable(f, "deploy", "cluster")
    if gate:
        return gate, []
    rows = [(_name(u, _U), u, f.get(_C + _name(u, _U))) for u in f.prefix(_U) if isinstance(u["value"], dict)]
    if not rows:
        return ("unknown", "no live usage: kubectl top gave nothing for the rendered workloads", []), []
    return None, rows


def _res(c: dict | None, side: str, kind: str) -> int | None:
    return _qty(kind, _d(_d(_d(c["value"] if c else None).get("resources")).get(side)).get(kind))


def _row_ids(u: dict, c: dict | None) -> list[str]:
    return [u["id"]] + ([c["id"]] if c else [])


def perf_rightsize(f: Facts) -> Outcome:
    gate, rows = _usage(f)
    if gate:
        return gate
    items = []
    for name, u, c in rows:
        notes, compared = [], 0
        for kind, (key, unit) in _UNITS.items():
            used = u["value"].get(key)
            if not isinstance(used, (int, float)):
                continue
            req, lim = _res(c, "requests", kind), _res(c, "limits", kind)
            if req is not None:
                compared += 1
                if used > req:
                    notes.append(f"{kind} {used}{unit} is above its {req}{unit} request")
            if lim:
                compared += 1
                if used >= NEAR_LIMIT * lim:
                    notes.append(f"{kind} {used}{unit} is at {used / lim:.0%} of its {lim}{unit} limit")
        if notes:
            items.append(("partial", f"{name} " + ", ".join(notes), _row_ids(u, c)))
        elif compared:
            items.append(("pass", "", _row_ids(u, c)))
        else:
            items.append(("unknown", f"{name} has no requests or limits to compare with", _row_ids(u, c)))
    return _combine(items, f"live usage is under requests and below {NEAR_LIMIT:.0%} of limits "
                           f"({_n(len(rows), 'container')})")


def cost_overprovision(f: Facts) -> Outcome:
    gate, rows = _usage(f)
    if gate:
        return gate
    items = []
    for name, u, c in rows:
        over = []
        for kind, (key, unit) in _UNITS.items():
            used, req = u["value"].get(key), _res(c, "requests", kind)
            if not isinstance(used, (int, float)) or req is None:
                continue
            if req > _FLOORS[kind] and req >= OVERPROVISION_RATIO * used:
                over.append(f"requests {req}{unit} {kind} and uses {used}{unit}")
        items.append(("partial", f"{name} " + ", ".join(over), _row_ids(u, c)) if over
                     else ("pass", "", _row_ids(u, c)))
    return _combine(items, f"requests are within {OVERPROVISION_RATIO}x of live usage ({_n(len(rows), 'container')})")


def sus_utilization(f: Facts) -> Outcome:
    gate, rows = _usage(f)
    if gate:
        return gate
    used = requested = 0
    ids: list[str] = []
    for _, u, c in rows:
        cpu, req = u["value"].get("cpu_m"), _res(c, "requests", "cpu")
        if isinstance(cpu, (int, float)) and req is not None:
            used, requested, ids = used + cpu, requested + req, ids + _row_ids(u, c)
    if requested <= 0:
        return "unknown", "no CPU requests to compare live usage with", [row[1]["id"] for row in rows]
    share = used / requested
    reason = f"live CPU use {used}m is {share:.0%} of the {requested}m requested"
    if share >= IDLE_RATIO:
        return "pass", reason, ids
    return "partial", f"{reason} (under {IDLE_RATIO:.0%}: idle or oversized)", ids


RULES: dict[str, Callable[[Facts], Outcome]] = {
    "ops.catalog": ops_catalog, "ops.runbook": ops_runbook, "ops.docs": ops_docs, "ops.open_prs": ops_open_prs,
    "sec.image_digest": sec_image_digest, "sec.base_digest": sec_base_digest, "sec.nonroot": sec_nonroot,
    "sec.hardening": sec_hardening, "sec.netpol": sec_netpol, "sec.secrets": sec_secrets, "sec.cve": sec_cve,
    "sec.dependabot": sec_dependabot, "sec.dep_updates": sec_dep_updates, "sec.actions_pinned": sec_actions_pinned,
    "sec.token_perms": sec_token_perms, "sec.sa_token": sec_sa_token, "sec.repo_hygiene": sec_repo_hygiene,
    "rel.probes": rel_probes, "rel.resources": rel_resources, "rel.pdb": rel_pdb, "rel.restarts": rel_restarts,
    "rel.dependencies": rel_dependencies, "perf.rightsize": perf_rightsize,
    "cost.overprovision": cost_overprovision, "sus.utilization": sus_utilization,
}
