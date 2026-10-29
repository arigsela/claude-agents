"""Check every claim's evidence before anything is posted; drop what fails.

commit: exists in the app (or deploy) checkout. pr/issue: exists (a PR claimed merged is merged).
file: exists, line in range, quote within ±3 lines. doc: quote verbatim (whitespace-normalized).
logql/promql: the shared scope check, then a re-run in [start, end] (default: report window ±2 h,
at most 24 h) through Grafana (`--telemetry grafana`, the Action) or straight against Loki and
Prometheus (`--telemetry direct`, the in-cluster trigger: no token); "found" needs data, "none" none.
ui: valid steps (steps.py), then a replay through `Ctx.ui_replay` (the in-cluster trigger only; the
Action and n8n mode have no browser): `fails_at` k needs step k to be the first failure, with a
failure kind that can show a bug (an allowlist, steps.EVIDENCE_FAILURES: `missing`, `mismatch`,
`error`), never because its target matched more than one element (`ambiguous`), because the step
cannot run on any page (`invalid`), because the replay ran out of time (`timeout`) or with no or an
unknown kind; null needs every step to pass.
The result must show exactly steps 1..k (null: all of them), in order, every one before the claimed
step passing. The verified item keeps the commit and per-step outcomes; the screenshots go to
`ctx.ui_shots[id]`, never the JSON.
Then: hypotheses without verified evidence become untested; likely_cause without a supported
hypothesis becomes unclear; secrets are scrubbed from every string.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import timedelta
from typing import Callable

from bug_investigator import grafana, scope, telemetry
from bug_investigator import steps as stepfmt
from bug_investigator.tickets import Gh, label_names
from bug_investigator.util import (CommandError, Runner, iso, ms, parse_time, read_json, read_secret, run, scrub,
                                   utc_now, window, write_json)

SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
NUM_RE = re.compile(r"^\s*(?:PR\s*|issue\s*)?#?(\d{1,7})\s*$", re.I)
LINE_SUFFIX_RE = re.compile(r"^(.*?)(?::|#L)(\d+)(?:-L?\d+)?$")
PAD = timedelta(hours=2)
DEFAULT_GRAFANA_URL = "https://grafana.arigsela.com"


class Ctx:
    def __init__(self, *, mode: str, repo: str, app_dir: str, deploy_dir: str | None = None,
                 deploy_repo: str = "arigsela/kubernetes", issue: int = 0, issue_created: str | None = None,
                 grafana_url: str = "", token: str = "", namespace: str = scope.NAMESPACE,
                 runner: Runner = run, gquery: Callable | None = None, telemetry_mode: str = "grafana",
                 ui_replay: Callable[[list, int | None], dict] | None = None):
        self.mode, self.repo, self.app_dir, self.deploy_dir = mode, repo, app_dir, deploy_dir
        self.deploy_repo, self.issue, self.namespace = deploy_repo, issue, namespace
        self.issue_created = parse_time(issue_created)
        if telemetry_mode not in ("grafana", "direct"):
            raise ValueError(f"telemetry_mode must be grafana or direct, got {telemetry_mode!r}")
        self.telemetry_mode = telemetry_mode
        # Direct mode has no Grafana token; its links still open Grafana Explore.
        self.grafana_url = grafana_url or (DEFAULT_GRAFANA_URL if telemetry_mode == "direct" else "")
        self.token = token
        self.run = runner
        self.gh = Gh(repo, runner)
        if gquery is None and telemetry_mode == "direct":
            gquery = lambda kind, expr, s, e: telemetry.query(kind, expr, s, e, namespace)  # noqa: E731
        self.gquery = gquery or (lambda kind, expr, s, e: grafana.query(grafana_url, token, kind, expr, s, e, namespace))
        self.heads = {k: self._head(d) for k, d in (("app", app_dir), ("deploy", deploy_dir)) if d}
        self.repos = {"app": repo, "deploy": deploy_repo}
        self._cache: dict = {}
        # ui evidence: replay(steps, fails_at) -> mcp_client.replay_via_mcp's dict; None = no browser in this run.
        self.ui_replay = ui_replay
        self.ui_shots: dict[str, list[tuple[int, bytes]]] = {}  # verified ui item id -> [(step, PNG)]

    def _head(self, d: str) -> str | None:
        try:
            return self.run(["git", "-C", d, "rev-parse", "HEAD"]).strip()
        except CommandError:
            return None

    def roots(self, prefer: str | None) -> list[tuple[str, str]]:
        order = ["deploy", "app"] if prefer == "deploy" else ["app", "deploy"]
        dirs = {"app": self.app_dir, "deploy": self.deploy_dir}
        return [(k, dirs[k]) for k in order if dirs.get(k)]


# ---------------------------------------------------------------------------------- helpers


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[`*]", "", s or "").split())


def _resolve(ctx: Ctx, ref: str, prefer: str | None) -> tuple[str, str, str] | None:
    """(root key, path relative to that root, absolute path) for an existing file, else None."""
    ref = (ref or "").strip()
    if not ref:
        return None
    for key, root in ctx.roots(prefer):
        rr = os.path.realpath(root)
        if os.path.isabs(ref):
            cand = os.path.realpath(ref)
        else:
            cand = os.path.realpath(os.path.join(rr, ref[2:] if ref.startswith("./") else ref))
        if not (cand == rr or cand.startswith(rr + os.sep)):
            continue
        if os.path.isfile(cand):
            return key, os.path.relpath(cand, rr), cand
    return None


def _lines(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def _find_quote(lines: list[str], quote: str, lo: int = 1, hi: int | None = None) -> int | None:
    """1-based line where the normalized quote starts within lines[lo..hi], else None."""
    q = _norm(quote)
    if not q:
        return None
    hi = min(hi or len(lines), len(lines))
    starts, parts, pos = [], [], 0
    for i in range(max(lo, 1), hi + 1):
        t = _norm(lines[i - 1])
        starts.append((pos, i))
        parts.append(t)
        pos += len(t) + 1
    text = " ".join(parts)
    idx = text.find(q)
    if idx < 0:
        return None
    line = starts[0][1] if starts else None
    for p, i in starts:
        if p <= idx:
            line = i
        else:
            break
    return line


def _blob_link(ctx: Ctx, key: str, rel: str, line: int | None) -> str:
    sha = ctx.heads.get(key) or "HEAD"
    return f"https://github.com/{ctx.repos[key]}/blob/{sha}/{rel}" + (f"#L{line}" if line else "")


def _split_line(ref: str, line) -> tuple[str, int | None]:
    """`path:42` or `path#L42` → (path, 42); an explicit line wins."""
    explicit = None
    if isinstance(line, int) and not isinstance(line, bool):
        explicit = line
    elif isinstance(line, str) and line.strip().isdigit():
        explicit = int(line)
    m = LINE_SUFFIX_RE.match(ref or "")
    if m:
        return m.group(1), explicit if explicit is not None else int(m.group(2))
    return ref, explicit


# ---------------------------------------------------------------------------------- checks


def check_commit(ctx: Ctx, ref: str, prefer: str | None = None) -> tuple[str | None, dict]:
    sha = (ref or "").strip()
    if not SHA_RE.match(sha):
        return "not a commit SHA", {}
    for key, root in ctx.roots(prefer):
        try:
            ctx.run(["git", "-C", root, "cat-file", "-e", f"{sha}^{{commit}}"])
            full = ctx.run(["git", "-C", root, "rev-parse", f"{sha}^{{commit}}"]).strip()
        except CommandError:
            continue
        return None, {"repo": key, "sha": full, "link": f"https://github.com/{ctx.repos[key]}/commit/{full}"}
    return "commit not found in the checkouts", {}


def check_pr(ctx: Ctx, ref: str, detail: str = "") -> tuple[str | None, dict]:
    m = NUM_RE.match(ref or "")
    if not m:
        return "not a PR number", {}
    n = int(m.group(1))
    st = ctx._cache.setdefault(("pr", n), ctx.gh.pr_state(n))
    if not st:
        return f"PR #{n} not found", {}
    if re.search(r"\bmerged\b", detail or "", re.I) and st.get("state") != "MERGED" and not re.search(r"\bnot merged\b", detail, re.I):
        return f"PR #{n} is {st.get('state')}, not merged", {}
    return None, {"number": n, "state": st.get("state"), "title": st.get("title"),
                  "link": st.get("url") or f"https://github.com/{ctx.repo}/pull/{n}"}


def check_issue(ctx: Ctx, ref: str) -> tuple[str | None, dict]:
    m = NUM_RE.match(ref or "")
    if not m:
        return "not an issue number", {}
    n = int(m.group(1))
    st = ctx._cache.setdefault(("issue", n), ctx.gh.issue_state(n))
    if not st:
        return f"issue #{n} not found", {}
    if "rehearsal" in label_names(st):
        return f"issue #{n} is a rehearsal", {}
    return None, {"number": n, "state": st.get("state"), "title": st.get("title"),
                  "link": st.get("url") or f"https://github.com/{ctx.repo}/issues/{n}"}


def check_file(ctx: Ctx, ref: str, line, quote: str | None, prefer: str | None) -> tuple[str | None, dict]:
    path, ln = _split_line(ref, line)
    found = _resolve(ctx, path, prefer)
    if not found:
        return f"file {path} not found in the checkouts", {}
    key, rel, full = found
    lines = _lines(full)
    if ln is not None and not (1 <= ln <= max(len(lines), 1)):
        return f"line {ln} is outside {rel} ({len(lines)} lines)", {}
    if quote:
        at = _find_quote(lines, quote, ln - 3, ln + 3) if ln else _find_quote(lines, quote)
        if at is None:
            return f"quote not found {'near line ' + str(ln) if ln else 'in the file'} of {rel}", {}
        ln = ln or at
    return None, {"repo": key, "path": rel, "line": ln, "link": _blob_link(ctx, key, rel, ln)}


def check_doc(ctx: Ctx, ref: str, quote: str | None, prefer: str | None) -> tuple[str | None, dict]:
    path, _ = _split_line(ref, None)
    found = _resolve(ctx, path, prefer)
    if not found:
        return f"doc {path} not found in the checkouts", {}
    if not quote or not _norm(quote):
        return "doc evidence needs a verbatim quote", {}
    key, rel, full = found
    at = _find_quote(_lines(full), quote)
    if at is None:
        return f"quote not found verbatim in {rel}", {}
    return None, {"repo": key, "path": rel, "line": at, "link": _blob_link(ctx, key, rel, at)}


def report_window(findings: dict, ctx: Ctx):
    rep = findings.get("report") or {}
    s, e = parse_time(rep.get("when_start")), parse_time(rep.get("when_end"))
    if s and e:
        return window(s - PAD, e + PAD, None)
    if s or e:
        return window((s or e) - PAD, (e or s) + PAD, None)
    return window(None, None, ctx.issue_created or utc_now())


def check_query(ctx: Ctx, item: dict, findings: dict) -> tuple[str | None, dict]:
    kind, expr = item.get("kind"), item.get("ref")
    bad = scope.check_query(kind, expr, ctx.namespace)
    if bad:
        return f"out of scope: {bad}", {}
    if ctx.mode != "full" or (ctx.telemetry_mode == "grafana" and not ctx.token):
        return "telemetry is not available in this run", {}
    s, e = parse_time(item.get("start")), parse_time(item.get("end"))
    if s or e:
        start, end = window(s, e, None)
    else:
        start, end = report_window(findings, ctx)
    try:
        resp = ctx.gquery(kind, expr, ms(start), ms(end))
    except grafana.GrafanaError as err:  # telemetry.TelemetryError is a subclass
        source = "Grafana" if ctx.telemetry_mode == "grafana" else "Loki/Prometheus"
        return f"{source} query failed: {err}", {}
    n = grafana.count_results(resp)
    expect = item.get("expect") or "found"
    if expect == "found" and n == 0:
        return f"query returned nothing in {iso(start)}..{iso(end)}", {}
    if expect == "none" and n > 0:
        return f"query returned {n} results in {iso(start)}..{iso(end)}, expected none", {}
    return None, {"count": n, "start": iso(start), "end": iso(end),
                  "link": grafana.explore_link(ctx.grafana_url, kind, expr, ms(start), ms(end))}


def _ui_step(s: dict) -> dict:
    """One replayed step as JSON-safe fields only (the replay result may carry more)."""
    n, err, failure = s.get("n"), s.get("error"), s.get("failure")
    return {"n": n if isinstance(n, int) and not isinstance(n, bool) else None, "text": str(s.get("text") or ""),
            "ok": s.get("ok") is True, "error": None if err in (None, "") else str(err),
            "failure": failure if isinstance(failure, str) else None}


def _ui_shape(ran: list[dict], want: int, fails_at: int | None) -> str | None:
    """Why the replayed steps are not exactly what the verdict rests on, or None. They must be steps 1..want in
    order (want: every step for a null claim, k for a claim of step k), each passing but the claimed one, which
    failed: an empty, partial or reordered result proves nothing."""
    ns = [s["n"] for s in ran]
    if ns != list(range(1, want + 1)):
        return f"replay failed: the result shows steps {', '.join(map(str, ns)) or 'none'}, not 1 to {want}"
    bad = next((s["n"] for s in ran if not s["ok"] and s["n"] != fails_at), None)
    if bad is not None and fails_at is None:
        return f"replay failed: the result says every step passed, but step {bad} did not"
    if bad is not None:
        return f"replay failed: step {bad} did not pass, yet the result names step {fails_at} as the first failure"
    if fails_at is not None and ran[-1]["ok"]:
        return f"replay failed: the result names step {fails_at} as the first failure, yet it passed"
    return None


def check_ui(ctx: Ctx, item: dict) -> tuple[str | None, dict]:
    """Replay the item's steps; verified when the replay fails exactly where `fails_at` says (null: nowhere)."""
    steps, fails_at = item.get("steps"), item.get("fails_at")
    problems = stepfmt.validate(steps, fails_at)
    if problems:
        return "; ".join(problems), {}
    if ctx.ui_replay is None:
        return "the browser is not available in this run", {}
    try:
        r = ctx.ui_replay(copy.deepcopy(steps), fails_at)
    except Exception as e:  # noqa: BLE001 - an unreachable server or a protocol error fails this item only
        return f"replay failed: {e}", {}
    if not isinstance(r, dict):
        return "replay failed: the browser returned no result", {}
    if r.get("error"):
        return f"replay failed: {r['error']}", {}
    ran = [_ui_step(s) for s in r.get("steps") if isinstance(s, dict)] if isinstance(r.get("steps"), list) else []
    ok, failed_at = r.get("ok") is True, r.get("failed_at")
    failed = next((s for s in ran if s["n"] == failed_at), None) if failed_at is not None else None
    error = (failed or {}).get("error") or "no error reported"
    what = f"step {failed_at} failed: {error}" if failed_at is not None else "the replay failed without naming a step"
    if fails_at is None:
        if not ok or failed_at is not None:
            return what, {}
    elif ok:
        return f"expected step {fails_at} to fail; every step passed", {}
    elif failed_at != fails_at:
        return f"expected step {fails_at} to fail; {what}", {}
    elif failed is None:
        return f"replay failed: the result does not show step {fails_at}", {}
    shape = _ui_shape(ran, len(steps) if fails_at is None else fails_at, fails_at)
    if shape:
        return shape, {}
    kind = failed["failure"] if failed else None
    if fails_at is not None and kind not in stepfmt.EVIDENCE_FAILURES:  # an allowlist (ruling R16)
        if kind == "ambiguous":  # ruling R8: a step that matched two elements proves nothing
            return f"step {fails_at} failed only because its target matched more than one element: {error}", {}
        if kind == "invalid":  # ruling R13: nor does one that can never pass on any code
            return f"step {fails_at} failed only because the step itself is invalid: {error}", {}
        if kind == "timeout":  # ruling R14b: nor a replay that ran out of time there
            return f"step {fails_at} failed only because the replay ran out of time: {error}", {}
        return f"step {fails_at} failed with failure kind {kind!r}, which is never evidence: {error}", {}
    shots = r.get("screenshots") if isinstance(r.get("screenshots"), list) else []
    ctx.ui_shots[str(item.get("id"))] = [(x[0], bytes(x[1])) for x in shots if isinstance(x, (list, tuple))
                                         and len(x) == 2 and isinstance(x[0], int)
                                         and isinstance(x[1], (bytes, bytearray))]
    commit = r.get("commit")
    return None, {"commit": commit if isinstance(commit, str) else None, "failed_at": failed_at, "steps": ran}


def check_item(ctx: Ctx, item: dict, findings: dict) -> tuple[str | None, dict]:
    kind, ref = item.get("kind"), str(item.get("ref") or "")
    prefer = item.get("repo")
    if kind == "commit":
        return check_commit(ctx, ref, prefer)
    if kind == "pr":
        return check_pr(ctx, ref, item.get("detail", ""))
    if kind == "issue":
        return check_issue(ctx, ref)
    if kind == "file":
        return check_file(ctx, ref, item.get("line"), item.get("quote"), prefer)
    if kind == "doc":
        return check_doc(ctx, ref, item.get("quote"), prefer)
    if kind in ("logql", "promql"):
        return check_query(ctx, item, findings)
    if kind == "ui":
        return check_ui(ctx, item)
    return f"unknown evidence kind {kind!r}", {}


# ---------------------------------------------------------------------------------- verify


def placeholder(reason: str) -> dict:
    return {
        "summary": f"The investigation did not finish: {reason}.",
        "verdict": "unclear", "confidence": "low",
        "report": {k: "" for k in ("who", "what", "when_start", "when_end", "where", "expected", "actual")},
        "docs_rule": None, "likely_cause": None, "hypotheses": [], "evidence": [], "similar_past_bugs": [],
        "next_step": "Re-run the investigation (workflow_dispatch) or investigate by hand.",
        "could_not_check": [reason],
    }


def verify(findings: dict | None, ctx: Ctx) -> dict:
    out = copy.deepcopy(findings) if isinstance(findings, dict) else placeholder("no findings were produced")
    for key, default in (("hypotheses", []), ("evidence", []), ("similar_past_bugs", []), ("could_not_check", [])):
        if not isinstance(out.get(key), list):
            out[key] = default
    dropped, notes = [], []

    kept, seen = [], set()
    for item in out["evidence"]:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or f"E{len(seen) + 1}")
        if iid in seen:
            dropped.append({"id": iid, "kind": item.get("kind"), "ref": item.get("ref"), "reason": "duplicate id"})
            continue
        seen.add(iid)
        try:
            # With the id it will be kept under, so ctx.ui_shots pairs with the kept item.
            reason, extra = check_item(ctx, {**item, "id": iid}, out)
        except Exception as e:  # a check that crashes fails the item, not the run
            reason, extra = f"check failed: {e}", {}
        if reason:
            dropped.append({"id": iid, "kind": item.get("kind"), "ref": item.get("ref"), "reason": reason})
        else:
            kept.append({**item, "id": iid, "verified": extra})
    total = len(seen)
    out["evidence"] = kept
    ok_ids = {e["id"] for e in kept}

    for h in out["hypotheses"]:
        if not isinstance(h, dict):
            continue
        ids = [i for i in h.get("evidence_ids") or [] if i in ok_ids]
        h["evidence_ids"] = ids
        if h.get("status") in ("supported", "ruled_out") and not ids:
            notes.append(f"{h.get('id')}: {h.get('status')} → untested (no verified evidence)")
            h["status"] = "untested"
    out["hypotheses"] = [h for h in out["hypotheses"] if isinstance(h, dict)]

    dr = out.get("docs_rule")
    if isinstance(dr, dict):
        reason, extra = check_doc(ctx, dr.get("path", ""), dr.get("quote"), None)
        if reason:
            dropped.append({"id": "docs_rule", "kind": "doc", "ref": dr.get("path"), "reason": reason})
            out["docs_rule"] = None
        else:
            dr["verified"] = extra
    else:
        out["docs_rule"] = None

    lc = out.get("likely_cause")
    lc_failed = False  # a stated cause whose change and code both failed verification
    if isinstance(lc, dict):
        cref = str(lc.get("change_ref") or "")
        if NUM_RE.match(cref):
            reason, extra = check_pr(ctx, cref)
        elif SHA_RE.match(cref.strip()):
            reason, extra = check_commit(ctx, cref)
        else:
            reason, extra = "change_ref is neither #N nor a commit SHA", {}
        if reason:
            dropped.append({"id": "likely_cause.change_ref", "kind": "change", "ref": cref, "reason": reason})
        lc["change_verified"] = None if reason else extra
        creason, cextra = check_file(ctx, str(lc.get("code_ref") or ""), None, None, "app")
        if creason:
            dropped.append({"id": "likely_cause.code_ref", "kind": "file", "ref": lc.get("code_ref"), "reason": creason})
        lc["code_verified"] = None if creason else cextra
        if reason and creason:
            out["likely_cause"] = None
            lc_failed = True
    else:
        out["likely_cause"] = None

    supported = any(h.get("status") == "supported" for h in out["hypotheses"])
    if out.get("verdict") == "likely_cause" and (not supported or lc_failed):
        notes.append("verdict likely_cause → unclear (no supported hypothesis with verified evidence)")
        out["verdict"] = "unclear"
        if out.get("likely_cause"):
            out["likely_cause"]["unconfirmed"] = True
    elif out.get("verdict") == "likely_cause" and not out.get("likely_cause"):
        # The verdict stands on the supported hypothesis; only the structured details are missing.
        notes.append("likely_cause details missing; the supported hypothesis stands in for them")
    if out.get("verdict") == "not_a_bug" and not out.get("docs_rule"):
        notes.append("verdict not_a_bug → unclear (no verified docs rule saying this is intended)")
        dropped.append({"id": "verdict", "kind": "verdict", "ref": "not_a_bug",
                        "reason": "not_a_bug needs a verified docs_rule quote"})
        out["verdict"] = "unclear"

    bugs = []
    for b in out["similar_past_bugs"]:
        if not isinstance(b, dict):
            continue
        reason, extra = check_issue(ctx, str(b.get("issue") or ""))
        if not reason and extra.get("number") == ctx.issue:
            reason = "that is this issue"
        if reason:
            dropped.append({"id": "similar_past_bugs", "kind": "issue", "ref": b.get("issue"), "reason": reason})
        else:
            bugs.append({**b, "verified": extra})
    out["similar_past_bugs"] = bugs

    out["verification"] = {"verified": len(kept), "total": total, "dropped": dropped, "notes": notes,
                           "heads": ctx.heads, "checked_at": iso(utc_now())}
    return scrub(out, [ctx.token] if ctx.token else [])


def load_findings(path: str | None, raw: str | None) -> tuple[dict | None, str | None]:
    text = raw
    if not text and path and os.path.isfile(path):
        with open(path) as f:
            text = f.read()
    if not text or not text.strip():
        return None, "Claude produced no structured findings (turn limit, error or timeout)"
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, f"the findings are not valid JSON ({e})"
    if not isinstance(data, dict):
        return None, "the findings are not a JSON object"
    return data, None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="verify")
    p.add_argument("--mode", choices=("full", "n8n"), required=True)
    p.add_argument("--findings", help="file with Claude's structured output (or env FINDINGS_JSON)")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--app-dir", required=True)
    p.add_argument("--deploy-dir")
    p.add_argument("--deploy-repo", default="arigsela/kubernetes")
    p.add_argument("--facts", help="facts.json, for the issue's created time")
    p.add_argument("--grafana-url", default="")
    p.add_argument("--token-file")
    p.add_argument("--telemetry", choices=("grafana", "direct"), default="grafana",
                   help="grafana: re-run queries through Grafana with --token-file (the Action); "
                        "direct: query Loki and Prometheus at LOKI_URL / PROMETHEUS_URL, no token (in-cluster)")
    p.add_argument("--namespace", default=scope.NAMESPACE)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    created = None
    if a.facts and os.path.isfile(a.facts):
        created = (read_json(a.facts).get("ticket") or {}).get("created_at")
    findings, problem = load_findings(a.findings, os.environ.get("FINDINGS_JSON"))
    ctx = Ctx(mode=a.mode, repo=a.repo, app_dir=a.app_dir, deploy_dir=a.deploy_dir if a.mode == "full" else None,
              deploy_repo=a.deploy_repo, issue=a.issue, issue_created=created, grafana_url=a.grafana_url,
              token=read_secret(a.token_file) if a.mode == "full" else "", namespace=a.namespace,
              telemetry_mode=a.telemetry)
    result = verify(findings if findings else placeholder(problem), ctx)
    write_json(a.out, result)
    v = result["verification"]
    print(f"verify: {v['verified']} of {v['total']} evidence items verified; verdict {result.get('verdict')}")
    for d in v["dropped"]:
        print(f"  dropped {d['id']} ({d['kind']} {str(d['ref'])[:80]}): {d['reason']}", file=sys.stderr)
    return 0
