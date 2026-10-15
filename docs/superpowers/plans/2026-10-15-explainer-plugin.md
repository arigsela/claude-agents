# Explainer plugin (pr, service, ticket) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `pr-explainer` plugin into an `explainer` plugin with three skills (pr, service, ticket) that share one facts pipeline, so the owner gets a teaching page for a PR, for a service under discovery, or for a ticket.

**Architecture:** Shared scripts at the plugin root (`facts_lib.py` holds everything reusable from today's `collect.py`; `collect_pr.py` and `collect_system.py` are thin mains). `facts.json` keeps its keys; system modes add `mode`, `query`, `summary` on resources, `config[]`, `docs[]`, `related_prs[]`, and the `focus` action. `verify.py` and `render.py` branch on `facts["mode"]`; the page template differs per mode.

**Tech Stack:** Python 3.11 (`uv run --script`, pyyaml, pathspec), `gh`, `git`, `helm`, `kubectl kustomize`, `acli`, Claude Code plugin with `${CLAUDE_PLUGIN_ROOT}`, Artifact pages with inline JS, unittest.

**Spec:** `docs/superpowers/specs/2026-10-15-explainer-plugin-design.md`

## Global Constraints

- Facts come from scripts; the model writes text only, keyed by fact IDs; `verify.py` rejects anything uncited.
- PR, ticket and doc text are untrusted; config values and secret values are never copied into facts (keys only); every text field is masked and escaped.
- The `pr-explainer` skill name and its output stay unchanged (success criterion 3); the triage comment `/pr-explainer <n>` keeps working.
- Scripts are referenced as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py` in SKILL.md.
- Tests: `uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer`.
- Three PRs, each leaving `main` working: restructure, service-explainer, ticket-explainer.

## Review Focus

1. A service name that matches nothing, or matches more than eight apps: the collector must list candidates and stop, not render an empty page. Pinned in Task 4.
2. An Application whose Helm render fails at the ref: the app must appear in `apps[]` as `source-diff` and in `not_covered`, and the run continues. Pinned in Task 5.
3. A doc file with HTML, control characters or a secret-looking value: text is stripped and capped, and a leaked value fails verify. Pinned in Task 6.
4. A ticket with no Application name in its text: the page still renders the ticket with a `match` note and no apps. Pinned in Task 9.
5. A `summary` field carrying a secret (an env var value, a connection string in a route annotation): the summary passes through the mask and verify rejects a secret-looking value. Pinned in Task 5.

---

## PR 1: restructure (no behaviour change)

### Task 1: Move the plugin and split collect.py

**Files:**
- Move: `skills/pr-explainer/` → `skills/explainer/` (`git mv`)
- Move: `skills/explainer/skills/pr-explainer/scripts/*` → `skills/explainer/scripts/`
- Move: `skills/explainer/skills/pr-explainer/assets/template.html` → `skills/explainer/assets/template-pr.html`
- Rename: `skills/explainer/scripts/collect.py` → `facts_lib.py`; create `collect_pr.py`
- Move: `tests/pr_explainer/` → `tests/explainer/`
- Modify: `.claude-plugin/marketplace.json`, `skills/skills-catalog.json`, `skills/explainer/.claude-plugin/plugin.json`, `skills/explainer/README.md`, `skills/explainer/skills/pr-explainer/SKILL.md`, `render.py` (template path)

**Interfaces:**
- Produces: `facts_lib` module exposing every function `collect.py` had (same names), `collect_pr.main()`; `render.py` takes `--template pr|system` (default `pr`) and reads `assets/template-<mode>.html` relative to the plugin root.

- [ ] **Step 1: Move with git so history follows**

```bash
git mv skills/pr-explainer skills/explainer
git mv skills/explainer/skills/pr-explainer/scripts skills/explainer/scripts
git mv skills/explainer/skills/pr-explainer/assets skills/explainer/assets
git mv skills/explainer/assets/template.html skills/explainer/assets/template-pr.html
git mv skills/explainer/scripts/collect.py skills/explainer/scripts/facts_lib.py
git mv tests/pr_explainer tests/explainer
```

- [ ] **Step 2: Create `collect_pr.py` as the thin main**

The body is today's `main()` moved verbatim, importing from `facts_lib`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "pathspec>=0.12,<1"]
# ///
"""explainer: collect deterministic facts about a PR into <out>/facts.json and <out>/diff.patch."""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

from facts_lib import Trees, collect, gh_pages, repo_from_origin, sh, trusted_comments

def main() -> int:
    ...  # today's main(), unchanged
```

`facts_lib.py` keeps its functions and loses `main()` and the `if __name__` block; `collect()` adds `"mode": "pr"` to its return value.

- [ ] **Step 3: Point render.py at the template by mode**

```python
def template_path(mode: str) -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / f"template-{mode}.html"
```
`render()` reads `template_path(facts.get("mode") or "pr")`; `main()` keeps working without a flag.

- [ ] **Step 4: Update the tests' import path and module name**

In `tests/explainer/*.py`: `sys.path.insert(0, ".../skills/explainer/scripts")` and `import facts_lib as collect` where `collect` was imported, so the test bodies stay unchanged.

- [ ] **Step 5: Run the tests**

Run: `uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/explainer`
Expected: 45 tests, OK.

- [ ] **Step 6: Update SKILL.md paths, plugin.json, marketplace, catalog, README**

SKILL.md: every `<base>/scripts/x.py` becomes `${CLAUDE_PLUGIN_ROOT}/scripts/x.py`; the "scripts live in `scripts/` next to this file" sentence becomes "scripts live in the plugin's `scripts/` directory, reached as `${CLAUDE_PLUGIN_ROOT}/scripts`". `collect.py` becomes `collect_pr.py`. plugin.json: `name: explainer`, `version: 1.0.0`. marketplace.json and skills-catalog.json: entry `explainer`, source `./skills/explainer`. README: install line and layout.

- [ ] **Step 7: Validate the plugin and run one PR explainer by hand**

Run: `claude plugin validate ./skills/explainer` → `Validation passed`.
Run the SKILL.md commands against a recent PR with `uv run --script skills/explainer/scripts/collect_pr.py --pr <n> --repo <R> --out <W>`, then verify and render; the page must match the pre-move output.

- [ ] **Step 8: Commit**

```bash
git add -A skills/explainer tests/explainer .claude-plugin/marketplace.json skills/skills-catalog.json
git commit -m "refactor(explainer): one plugin, shared scripts, pr-explainer unchanged"
```

---

## PR 2: service-explainer

### Task 2: `Trees.at` and single-ref rendering

**Files:**
- Modify: `skills/explainer/scripts/facts_lib.py` (class `Trees`)
- Test: `tests/explainer/test_system_facts.py`

**Interfaces:**
- Produces: `Trees.at(repo: str, ref: str) -> Trees` with `.head` (worktree at the ref), `.base is None`, `.sha`, `.ref`; `close()` unchanged.

- [ ] **Step 1: Failing test on a local fixture repo**

```python
def make_repo(tmp: Path) -> Path:
    """A git repo with one directory-sourced Application and its manifests."""
    (tmp / "argo/prod").mkdir(parents=True); (tmp / "apps/grafana").mkdir(parents=True)
    (tmp / "argo/prod/grafana.yaml").write_text(APP_YAML)
    (tmp / "apps/grafana/all.yaml").write_text(MANIFESTS)
    sh("git", "init", "-q", "-b", "main", cwd=tmp); sh("git", "add", ".", cwd=tmp)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init", cwd=tmp)
    return tmp

def test_trees_at_checks_out_the_ref(self):
    repo = make_repo(Path(self.tmp))
    with mock.patch.object(facts_lib, "repo_from_origin", return_value="o/r"), \
         mock.patch.object(facts_lib, "local_root", return_value=repo):
        t = facts_lib.Trees.at("o/r", "main")
    try:
        self.assertTrue((t.head / "argo/prod/grafana.yaml").is_file())
        self.assertIsNone(t.base)
    finally:
        t.close()
```

- [ ] **Step 2: Run, expect `AttributeError: type object 'Trees' has no attribute 'at'`**

- [ ] **Step 3: Implement**

```python
@classmethod
def at(cls, repo: str, ref: str) -> "Trees":
    self = cls.__new__(cls)
    self.dir = Path(tempfile.mkdtemp(prefix="explainer-")); self.base, self.head = None, self.dir / "head"
    self.ref, self.merge_base = ref, None
    origin = repo_from_origin()
    if origin and origin.lower() == repo.lower():
        self.local = local_root(); self.git = self.local; fetch = ["git", "fetch", "--quiet", "origin"]
    else:
        self.local = None; self.git = self.dir / "repo.git"
        fetch = ["git", "fetch", "--quiet", "--filter=blob:none", "origin"]
    try:
        if not self.local:
            ... # same bare-repo init and credential config as __init__
        sh(*fetch, ref, cwd=self.git)
        self.sha = sh("git", "rev-parse", "FETCH_HEAD", cwd=self.git).strip()
        sh("git", "worktree", "add", "--detach", "--quiet", str(self.head), self.sha, cwd=self.git)
    except BaseException:
        self.close(); raise
    return self
```
`local_root()` is `Path(sh("git", "rev-parse", "--show-toplevel").strip())`, extracted so tests can patch it. `close()` skips `None` trees. The fixture test uses a local checkout path with `origin` mocked; the fetch of `main` from the fixture's own `origin` needs `git remote add origin <tmp>` in `make_repo`.

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): Trees.at renders one ref`

### Task 3: Service matching

**Files:**
- Modify: `facts_lib.py` (add `match_applications`)
- Test: `tests/explainer/test_system_facts.py`

**Interfaces:**
- Produces: `match_applications(found: list[tuple[str, str, dict]], names: list[str]) -> tuple[dict[str, list[tuple[str, str, dict]]], list[dict]]`: `{app_name: [(name, file, doc), ...]}` for every match (one entry per environment file) and `matched_by` rows `{app, name, by: "name"|"directory"|"source-path"}`.

- [ ] **Step 1: Failing tests**

```python
def test_match_by_name_directory_and_source_path(self):
    found = [("grafana", "argo/prod/grafana.yaml", app("grafana", "apps/grafana")),
             ("grafana", "argo/nonprod/grafana.yaml", app("grafana", "apps/grafana")),
             ("metrics", "argo/prod/metrics.yaml", app("metrics", "apps/grafana-agent")),
             ("loki", "argo/prod/loki.yaml", app("loki", "apps/loki"))]
    apps, by = facts_lib.match_applications(found, ["grafana"])
    self.assertEqual(sorted(apps), ["grafana", "metrics"])
    self.assertEqual(len(apps["grafana"]), 2)
    self.assertIn({"app": "metrics", "name": "grafana", "by": "source-path"}, by)

def test_match_is_case_insensitive_and_empty_when_nothing_matches(self):
    found = [("Grafana-UI", "argo/prod/g.yaml", app("Grafana-UI", "apps/g"))]
    self.assertEqual(list(facts_lib.match_applications(found, ["grafana"])[0]), ["Grafana-UI"])
    self.assertEqual(facts_lib.match_applications(found, ["loki"]), ({}, []))
```

- [ ] **Step 2: Run, expect `AttributeError`. Step 3: Implement**

```python
def match_applications(found, names):
    apps, by = {}, []
    wanted = [n.lower() for n in names if n.strip()]
    for name, file, doc in found:
        hay = {"name": name.lower(), "directory": str(Path(file).parent).lower(),
               "source-path": " ".join((s.get("path") or "") for s in app_sources(doc)).lower()}
        for n in wanted:
            how = next((k for k in ("name", "directory", "source-path") if n in hay[k]), None)
            if how:
                apps.setdefault(name, []).append((name, file, doc))
                row = {"app": name, "name": n, "by": how}
                if row not in by:
                    by.append(row)
                break
    return apps, by
```

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): match applications by name, directory or source path`

### Task 4: `collect_system.py` main and the facts skeleton

**Files:**
- Create: `skills/explainer/scripts/collect_system.py`
- Modify: `facts_lib.py` (add `collect_system(repo, trees, names, docs, ticket_key, all_apps) -> dict`)
- Test: `tests/explainer/test_system_facts.py`

**Interfaces:**
- Consumes: `Trees.at`, `match_applications`, `find_applications`, `render_app`, `res_key`, `build_edges`, `find_lines`, `read_policy`, `tf_block_list`, `workflow_elements`, `key_line`, `job_needs`.
- Produces: `facts.json` with `mode: "service"`, `pr: null`, `query`, `apps`, `resources` (actions `focus|context|generated`), `edges`, `config`, `terraform` (`source: "source-ref"`, action `focus`), `workflows`, `docs`, `related_prs: []`, `jira: null`, `policy_hits: []`, `terraform_plans: []`, `non_manifest_changes: []`, `notes`.

- [ ] **Step 1: Failing test for the no-match and too-many cases**

```python
def test_no_match_lists_candidates_and_fails(self):
    repo = make_repo(Path(self.tmp))
    with self.trees(repo) as t, self.assertRaises(SystemExit) as cm:
        facts_lib.collect_system("o/r", t, ["nothing"], [], None, False)
    self.assertIn("grafana", str(cm.exception))

def test_too_many_matches_fails_without_all(self):
    repo = make_repo(Path(self.tmp), apps=[f"svc-{i}" for i in range(9)])
    with self.trees(repo) as t, self.assertRaises(SystemExit):
        facts_lib.collect_system("o/r", t, ["svc"], [], None, False)
    with self.trees(repo) as t:
        self.assertEqual(len(facts_lib.collect_system("o/r", t, ["svc"], [], None, True)["apps"]), 9)
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement the skeleton**

```python
MAX_MATCHED_APPS = 8

def collect_system(repo, trees, names, docs, ticket_key, all_apps):
    policy = read_policy(trees) or {}
    callouts = policy.get("risk_callouts") or {}
    found = find_applications(trees.head)
    matched, matched_by = match_applications(found, names)
    if names and not matched:
        close = sorted({n for n, _, _ in found}, key=lambda n: difflib.SequenceMatcher(None, n, names[0]).ratio(), reverse=True)[:10]
        sys.exit(f"collect: no Application matches {names}; closest names: {', '.join(close) or 'none'}")
    if len(matched) > MAX_MATCHED_APPS and not all_apps:
        sys.exit(f"collect: {len(matched)} Applications match {names}: {', '.join(sorted(matched))}. Narrow the name or pass --all.")
    scoped = any(len(v) > 1 for v in matched.values())
    apps_out, universe, owner, where = [], {}, {}, {}
    for name in sorted(matched):
        for _, afile, adoc in matched[name]:
            ns = (adoc["spec"].get("destination") or {}).get("namespace") or ""
            scope = str(Path(afile).parent) if scoped else ""
            entry = {"app": name, "application_file": afile, "scope": scope, "source_kind": "unknown", "render": "rendered", "render_note": ""}
            try:
                entry["source_kind"] = app_source_kind(trees.head, adoc)
                hdocs, _, hnotes = render_app(trees.head, afile, adoc, trees.dir, repo)
            except Exception as err:
                entry["render"], entry["render_note"] = "source-diff", f"{type(err).__name__}: {err}"
                apps_out.append(entry); continue
            entry["render_note"] = "; ".join(dict.fromkeys(hnotes))
            for d, f in hdocs:
                k = res_key(d, ns, scope); universe[k], owner[k], where[k] = d, name, f
            k = res_key(adoc, "argo-cd", scope); universe[k], owner[k], where[k] = adoc, name, afile
            apps_out.append(entry)
    focus = set(universe)
    # generated Secrets, edges, one-hop neighbours: as collect() does, with `focus` in place of `changes`
    ...
    return {"mode": "service", "pr": None, "triage": None,
            "query": {"service": names, "matched_by": matched_by, "ref": trees.ref, "sha": trees.sha, "repo": repo},
            "apps": apps_out, "resources": resources, "edges": edges_out + tf_edges + wf_edges,
            "config": config, "terraform": tf, "terraform_plans": [], "workflows": wf, "non_manifest_changes": [],
            "docs": doc_facts, "related_prs": [], "jira": jira, "policy_hits": [], "notes": notes}
```
In service mode every matched app's resources are in `universe` only, so neighbours one hop away only exist when another matched app provides them; `context` therefore comes from apps matched through a second name (`--service grafana --service loki`). Resource rows carry `action: "focus"`, `changed_paths: []`, `file`, `lines` from `find_lines(trees.head, ...)`, `risk`.

`collect_system.py` main:

```
collect_system.py --service NAME [--service NAME]... [--repo owner/name] [--ref main] [--doc FILE]... [--ticket KEY] [--all] --out DIR
```
`--ref` defaults to `gh api repos/<R> --jq .default_branch`. Prints the apps, scopes, resources, config keys, terraform blocks, workflow entries, docs and ticket found, and `wrote facts.json`.

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): collect_system skeleton with service matching`

### Task 5: Summaries, config keys, Terraform and workflow mentions

**Files:**
- Modify: `facts_lib.py` (`resource_summary`, `config_facts`, `terraform_mentions`, `workflow_mentions`), `collect_system` fills them
- Test: `tests/explainer/test_system_facts.py`

**Interfaces:**
- Produces: `resource_summary(doc: dict) -> dict` (per kind, values masked); `config_facts(trees, matched, repo) -> list[dict]` rows `{id: "c1", app, scope, source, file, keys}`; `terraform_mentions(root, names) -> (tf, edges)`; `workflow_mentions(root, names) -> (wf, edges)`.

- [ ] **Step 1: Failing tests**

```python
def test_resource_summary_per_kind_and_masked(self):
    dep = yaml.safe_load(DEPLOYMENT_WITH_PROBES_AND_ENV)   # env has DB_PASSWORD=hunter2hunter2
    s = facts_lib.resource_summary(dep)
    self.assertEqual(s["image"], "grafana/grafana:10.1")
    self.assertEqual(s["replicas"], 2)
    self.assertEqual(s["probes"], {"readiness": "/api/health", "liveness": "/api/health"})
    self.assertNotIn("hunter2", json.dumps(s))
    route = yaml.safe_load(HTTPROUTE)
    self.assertEqual(facts_lib.resource_summary(route)["hosts"], ["grafana.example.com"])
    cron = yaml.safe_load(CRONJOB)
    self.assertEqual(facts_lib.resource_summary(cron)["schedule"], "0 3 * * *")
    es = yaml.safe_load(EXTERNAL_SECRET)
    self.assertEqual(facts_lib.resource_summary(es), {"store": "vault", "keys": ["admin-password"]})

def test_config_facts_keys_only(self):
    repo = make_repo(Path(self.tmp), values={"adminPassword": "hunter2hunter2", "replicas": 2})
    with self.trees(repo) as t:
        found = facts_lib.find_applications(t.head)
        matched, _ = facts_lib.match_applications(found, ["grafana"])
        rows = facts_lib.config_facts(t, matched, "o/r")
    self.assertEqual(rows[0]["keys"], ["adminPassword", "replicas"])
    self.assertNotIn("hunter2", json.dumps(rows))

def test_terraform_and_workflow_mentions(self):
    repo = make_repo(Path(self.tmp), tf='resource "aws_s3_bucket" "grafana_dashboards" {\n  bucket = "grafana-x"\n}\nresource "aws_s3_bucket" "other" {}\n',
                     workflow=DEPLOY_WORKFLOW_MENTIONING_GRAFANA)
    with self.trees(repo) as t:
        tf, _ = facts_lib.terraform_mentions(t.head, ["grafana"])
        wf, edges = facts_lib.workflow_mentions(t.head, ["grafana"])
    self.assertEqual([x["address"] for x in tf], ["aws_s3_bucket.grafana_dashboards"])
    self.assertEqual(tf[0]["action"], "focus"); self.assertEqual(tf[0]["source"], "source-ref")
    self.assertEqual({w["element"] for w in wf}, {"trigger", "job"})
    self.assertTrue(all(w["action"] == "focus" for w in wf))
```

- [ ] **Step 2: Run, expect failures. Step 3: Implement**

`resource_summary`: workloads → `image` (first container), `replicas`, `ports`, `probes` (path or port per probe kind), `env_keys` (names only); Service → `ports`, `selector`; HTTPRoute/Ingress/VirtualService → `hosts`, `paths`, `backends`; CronJob → `schedule`; ExternalSecret → `store`, `keys` (remoteRef keys); PVC → `size`; ConfigMap → `keys`. Every string value runs through `render.mask`-equivalent (`SECRET_VALUE_RE.sub`) in `facts_lib`. `config_facts`: for each matched app and source: `helm.values` (inline YAML) → keys of the parsed mapping; `helm.valuesObject` → keys; `helm.parameters` → names; each `valueFiles` entry in this repo → top-level keys of the file. `terraform_mentions`: `tf_block_list(root)` filtered where any name is in `addr.lower()` or `body.lower()`; rows `{id: t*, address, action: "focus", source: "source-ref", type, name, file, lines: [line]}`; edges via `tf_reference_edges`. `workflow_mentions`: each file under `.github/workflows/` whose text contains a name → `workflow_elements`, rows like `workflow_facts` with `action: "focus"` and `needs` edges.

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): summaries, config keys, terraform and workflow mentions`

### Task 6: Docs input

**Files:**
- Modify: `facts_lib.py` (`doc_facts(paths: list[str]) -> tuple[list[dict], list[dict]]`), `collect_system.py` (`--doc`)
- Test: `tests/explainer/test_system_facts.py`

- [ ] **Step 1: Failing test**

```python
def test_docs_are_stripped_capped_and_identified(self):
    p = Path(self.tmp) / "page.md"; p.write_text("# Title\n<b>bold</b> text\x00 " + "x" * 30000)
    docs, notes = facts_lib.doc_facts([str(p), str(Path(self.tmp) / "missing.md")])
    self.assertEqual(docs[0]["id"], "d1"); self.assertEqual(docs[0]["title"], "Title")
    self.assertNotIn("<b>", docs[0]["text"]); self.assertNotIn("\x00", docs[0]["text"])
    self.assertEqual(len(docs[0]["text"]), facts_lib.DOC_CHARS); self.assertTrue(docs[0]["truncated"])
    self.assertEqual(notes[0]["key"], "docs")
```

- [ ] **Step 2: Run, expect failure. Step 3: Implement**

```python
DOC_CHARS = 20000
def doc_facts(paths):
    docs, notes = [], []
    for p in paths:
        try:
            raw = Path(p).read_text(errors="replace")
        except OSError as e:
            notes.append({"key": "docs", "text": f"{p} could not be read ({type(e).__name__})."}); continue
        text = re.sub(r"<[^>]+>", "", raw); text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ch >= " ")
        title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), Path(p).stem)
        docs.append({"id": f"d{len(docs) + 1}", "title": title[:200], "source": "file", "path": str(p),
                     "chars": len(text), "truncated": len(text) > DOC_CHARS, "text": text[:DOC_CHARS]})
    return docs, notes
```

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): --doc feeds Confluence or requirements text as untrusted facts`

### Task 7: verify and render for system mode

**Files:**
- Modify: `verify.py` (mode branch), `render.py` (mode branch, `focus` class, summary walkthrough, new sections), create `assets/template-system.html`
- Test: `tests/explainer/test_system_page.py`

**Interfaces:**
- Consumes: facts from Task 4–6; explainer fields from spec §5.
- Produces: `verify(facts, expl)` errors for the system rules in spec §6; `render(facts, expl, errors, diff)` picks `template-system.html` when `facts["mode"] != "pr"`.

- [ ] **Step 1: Failing tests** (fixture `SYSTEM_FACTS` with two apps in two scopes, one route, one config row, one doc; `GOOD_SYSTEM` explainer)

```python
def test_system_required_fields(self):
    self.assertEqual(verify.verify(SYSTEM_FACTS, GOOD_SYSTEM), [])
    errs = verify.verify(SYSTEM_FACTS, bad(components=[]))
    self.assertTrue(any("components" in e and "grafana" in e for e in errs))
    errs = verify.verify(SYSTEM_FACTS, bad(how_it_works=[GOOD_SYSTEM["how_it_works"][0]]))
    self.assertTrue(any("how_it_works has 1" in e for e in errs))
    errs = verify.verify(SYSTEM_FACTS, bad(where_it_runs=[]))
    self.assertTrue(any("where_it_runs" in e and "argo/prod" in e for e in errs))
    errs = verify.verify(SYSTEM_FACTS, bad(config_that_matters=[{"key": "x", "why": "y", "refs": ["r1"]}]))
    self.assertEqual(errs, [])  # r* allowed
    errs = verify.verify(SYSTEM_FACTS, bad(docs_summary=[]))
    self.assertTrue(any("docs_summary" in e and "d1" in e for e in errs))
    self.assertNotIn("scenario is missing", verify.verify(SYSTEM_FACTS, bad(scenario=None)))  # how_it_works[0] stands in

def test_system_page_sections(self):
    page = render.render(SYSTEM_FACTS, GOOD_SYSTEM, [], {})
    for h in ("Components", "How it works", "Where it runs", "Config that matters", "What the docs ask", "Open questions", "Walkthrough", "Check your understanding"):
        self.assertIn(h, page)
    self.assertIn(":::focus", page); self.assertIn("classDef focus", page)
    self.assertIn("grafana.example.com", page)  # route summary in the walkthrough
    self.assertNotIn("hunter2", page)
```

- [ ] **Step 2: Run, expect failures. Step 3: Implement**

verify: `mode = facts.get("mode") or "pr"`; when `mode != "pr"`: `scenario` is optional if `how_it_works` has ≥ 2 entries (verify copies `how_it_works[0]` into `scenario` for rendering; render does the same); `components` one row per `apps[].app`; `how_it_works` 2–3 entries with `trigger`, `path`, refs; `where_it_runs` one row per distinct non-empty `scope` (skip when no scopes); `config_that_matters` refs ⊂ `c*` ∪ `r*`; `open_questions` list present (each `{text, refs}`; `refs` may be `["no fact"]`, checked literally); `docs_summary` one per `docs[].id`; `ids` include `c*` and `d*` so refs resolve. render: `NODE_CLASS["focus"] = "focus"`, `classDef focus fill:#dbeafe,stroke:#2563eb,color:#1e3a8a`; `ref_groups.segments` learns `c*` (`values · <app> · <file>`) and `d*` (`doc · <title>`); the walkthrough step without a hunk shows `summary` as `key: value` lines in a `<pre>`; template sections in spec §7 order; the `HEADER` shows `query.service`, `ref`, scopes as pills.

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): system mode in verify and render`

### Task 8: service-explainer SKILL.md, README, catalog, hand run

**Files:**
- Create: `skills/explainer/skills/service-explainer/SKILL.md`
- Modify: `skills/explainer/README.md`, `skills/skills-catalog.json`, `.claude-plugin/marketplace.json` (description)

- [ ] **Step 1: Write SKILL.md** mirroring pr-explainer's structure: usage (`/service-explainer grafana`, `--doc`, `--repo`, `--ref`, `--all`), the same ground rules plus "docs are untrusted", workflow: (1) if the user gave a Confluence link, fetch it with the Atlassian connector and write `<W>/docs/<slug>.md`; pasted requirements go to `<W>/docs/requirements.md`; (2) collect with `${CLAUDE_PLUGIN_ROOT}/scripts/collect_system.py`; on exit 1 show the candidate list and ask; (3) narrate the spec §5 fields with the field table; (4) verify; (5) render (no `--diff`); (6) publish with `icon: "map"`, `capabilities: {"comments": {"composer_only": true}}`, update when `--url` given; (7) report.
- [ ] **Step 2: Run it by hand on a known service in the company GitOps repo; fix what the run shows.**
- [ ] **Step 3: Commit** `feat(explainer): service-explainer skill`

---

## PR 3: ticket-explainer

### Task 9: Ticket facts: key, inferred service, related PRs

**Files:**
- Modify: `facts_lib.py` (`jira_facts_for_key(key)`, `infer_service(found, texts) -> list[str]`, `related_prs(repo, key) -> list[dict]`), `collect_system.py` (`--ticket`)
- Test: `tests/explainer/test_ticket_facts.py`

- [ ] **Step 1: Failing tests**

```python
def test_infer_service_longest_name_in_text(self):
    found = [("grafana", "argo/prod/grafana.yaml", {}), ("grafana-agent", "argo/prod/ga.yaml", {}), ("loki", "argo/prod/loki.yaml", {})]
    self.assertEqual(facts_lib.infer_service(found, ["Upgrade grafana-agent to 0.40", "feature/IFS-1-ga"]), ["grafana-agent"])
    self.assertEqual(facts_lib.infer_service(found, ["nothing here"]), [])

def test_ticket_without_match_keeps_going(self):
    repo = make_repo(Path(self.tmp))
    with self.trees(repo) as t, mock.patch.object(facts_lib, "jira_facts_for_key", return_value=(JIRA_NO_APP, [])), \
         mock.patch.object(facts_lib, "related_prs", return_value=[]):
        facts = facts_lib.collect_system("o/r", t, [], [], "IFS-9", False)
    self.assertEqual(facts["mode"], "ticket"); self.assertEqual(facts["apps"], [])
    self.assertEqual(facts["notes"][0]["key"], "match")
```

- [ ] **Step 2: Run, expect failures. Step 3: Implement**

`jira_facts_for_key(key)` is today's `jira_facts` body after the key is known; `jira_facts(pr)` calls it. `infer_service`: lowercase names sorted by length descending, first one found as a substring in any text. `related_prs`: `gh pr list -R <R> --search "<KEY>" --state all --limit 10 --json number,title,state,url,headRefName`, rows `{number, title, state, url, head_ref}`, failures → `[]` with a `related_prs` note. In `collect_system` with `ticket_key`: `mode = "ticket"`, `jira` set, names = given `--service` or inferred from `[summary, description] + [pr.head_ref for related]`; no match → `match` note, no apps, continue.

- [ ] **Step 4: Run, expect PASS. Commit** `feat(explainer): ticket facts with inferred service and related PRs`

### Task 10: Ticket fields in verify and render, SKILL.md

**Files:**
- Modify: `verify.py` (`ticket` statuses for ticket mode: `would_change|already_true|out_of_scope|unclear`; `pr` field cites a `related_prs[].number`), `render.py` (Ticket card with related PR links; `STATUS_LABEL` additions), `template-system.html` (Ticket slot)
- Create: `skills/explainer/skills/ticket-explainer/SKILL.md`
- Test: `tests/explainer/test_system_page.py`

- [ ] **Step 1: Failing test**

```python
def test_ticket_statuses_and_related_pr_links(self):
    facts = {**SYSTEM_FACTS, "mode": "ticket", "jira": JIRA, "related_prs": [{"number": 7, "title": "x", "state": "OPEN", "url": "https://github.com/o/r/pull/7", "head_ref": "feature/IFS-9"}]}
    expl = {**GOOD_SYSTEM, "ticket": {"intent": "i", "pr": 7, "criteria": [{"text": "a", "status": "would_change", "refs": ["r1"]}, {"text": "b", "status": "covered", "refs": ["r1"]}]}}
    errs = verify.verify(facts, expl)
    self.assertTrue(any("criteria[1] status 'covered'" in e for e in errs))
    page = render.render(facts, {**expl, "ticket": {**expl["ticket"], "criteria": expl["ticket"]["criteria"][:1]}}, [], {})
    self.assertIn("would change", page); self.assertIn("pull/7", page); self.assertIn("/pr-explainer 7", page)
```

- [ ] **Step 2: Run, expect failures. Step 3: Implement** per spec §5 `ticket` row and §7 section 9; SKILL.md mirrors service-explainer with `/ticket-explainer IFS-314 [--service name] [--doc file]`, and after publishing, when `related_prs` has an open PR, suggests `/pr-explainer <n>`.
- [ ] **Step 4: Run, expect PASS. Hand run on an open ticket. Commit** `feat(explainer): ticket-explainer skill`

---

## Self-review notes

- Spec coverage: §3 → Task 1 and 8; §4 → Tasks 2–6, 9; §5–§7 → Tasks 7, 10; §8 → Task 8 and 10 SKILL.md publish steps; §9 masking → Tasks 5, 6; §10 → the three PR groupings.
- Types: `collect_system(repo, trees, names, docs, ticket_key, all_apps)` is used with the same positional order in Tasks 4, 5, 9. `match_applications` returns `(dict, list)` in Tasks 3, 4, 5. `Trees.at` has `.head`, `.sha`, `.ref`, `.base is None` in Tasks 2, 4.
- Review Focus 1–5 are pinned in Tasks 4, 5, 6, 9 and 5.
