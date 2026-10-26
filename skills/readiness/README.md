# readiness

`/production-readiness <repo-path>` reviews an app repo against a Well-Architected-style check
catalog (`checks.yaml`) and prints a terminal report: a verdict, at most five ranked fixes, a
pillar summary, findings per pillar, the ORR questions only a person can answer, and what was not
checked.

Design: `docs/superpowers/specs/2026-10-25-production-readiness-plugin-design.md`.

## Usage

```
/production-readiness ~/git/hk-demo
/production-readiness ~/git/hk-demo --ref v0.7.0 --deploy-ref my-branch --no-live --out /tmp/hk
```

Flags: `--ref` (app commit, default HEAD, committed trees only), `--entity kind:ns/name` (when the
repo is not or ambiguously in the catalog), `--deploy-ref` (default: what Argo CD deploys),
`--no-live` (skip the cluster), `--out DIR` (default: a new temp directory; never the reviewed repo).

## How it works

1. `scripts/collect.py` repo path to `facts.json`.
2. `scripts/evaluate.py` facts and `checks.yaml` to `results.json`: rule checks decided, judgment
   checks listed with candidate facts.
3. The model writes `report.json`: nine judgments (each citing fact ids), a note per pillar, up to
   five fixes.
4. `scripts/verify.py` rejects a changed rule status, an uncited judgment, a fix that names no
   failing or partial check, a missing check, or a secret. It recomputes the rule checks from
   `facts.json` and `checks.yaml` rather than trusting `results.json`.
5. `scripts/render.py` prints the markdown report (with an UNVERIFIED banner if verify failed). It
   also decides the rule checks itself from `facts.json`, so an edited `results.json` changes nothing.

Verdict: Not ready when any blocker check fails; Ready with gaps when any check fails or is
partial, or a blocker is unknown; otherwise Ready.

## Sources

| Source | What it gives | Access |
|---|---|---|
| app | workflows, Dockerfile, deps, docs of the app repo at a committed ref | `git` |
| deploy | the Application's rendered manifests, Terraform, alert rules from the GitOps repo at its `targetRevision` | `gh`, temp clone |
| backstage | catalog entity, owner, lifecycle, dependencies, scorecard, CVE report | HTTP GET (optional `BACKSTAGE_TOKEN`) |
| cluster | workloads, restarts, usage in the app's namespace | `kubectl get` and `kubectl top` |
| github | repo settings, branch protection, Dependabot alerts | `gh api` GET |

A source that cannot answer is recorded with its reason, and checks that need it end `unknown`.

## Read-only guarantees

- The reviewed repos are never written: reads use committed trees, and the deploy repo is read from
  a temp clone.
- kubectl runs only `get` and `top`; `gh api` runs only GET; Backstage is read with GET.
- The Backstage token is never written to a file or printed.
- Repo text is untrusted data. The skill's judgments must cite collected facts, and `verify.py`
  rejects secret-looking strings.

## Tests

```
uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/readiness -t .
```

Fixtures only, no network.
