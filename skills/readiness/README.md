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
`--no-live` (skip the cluster), `--out DIR` (default: a new temp directory; never the reviewed repo;
the skill puts each run in a fresh `run-<n>` folder under it).

## How it works

1. `scripts/collect.py` repo path to `facts.json`.
2. `scripts/evaluate.py` facts and `checks.yaml` to `results.json`: rule checks decided, judgment
   checks listed with candidate facts.
3. The model writes `report.json`: nine judgments (each citing fact ids), a note per pillar, up to
   five top fixes, and `item_fixes`: a specific fix for each failing or partial check.
4. `scripts/verify.py` rejects a changed rule status, an uncited judgment, a fix that names no
   failing or partial check, an `item_fixes` entry for an unknown check or of more than 25 words,
   a missing check, or a secret. It recomputes the rule checks from
   `facts.json` and `checks.yaml` rather than trusting `results.json`.
5. `scripts/render.py` prints the short markdown report and saves the full one as `<R>/report.md`
   (`--full` prints that instead; an UNVERIFIED banner comes first if verify failed). The short one
   has one line per finding, with at most one file pointer and, on a failing or partial line, the
   fix (the report's `item_fixes`, else the catalog's generic `fix`); no check titles, pillar notes
   or keyword hints. Under Security both show the Scorecard CVE cards, from the images actually
   running, next to `sec.cve`, from the images in the deploy repo. It also decides the rule checks
   itself from `facts.json`, so an edited `results.json` changes nothing.

Verdict: Not ready when any blocker check fails; Ready with gaps when any check fails or is
partial, or a blocker is unknown; otherwise Ready.

## Sources

| Source | What it gives | Access |
|---|---|---|
| app | workflows, Dockerfiles (anywhere in the tree), deps, docs of the app repo at a committed ref | `git` |
| deploy | the Application's rendered manifests, Terraform, alert rules from the GitOps repo at its `targetRevision`. The folder is where the entity is catalogued from; when that is the app repo, the folder the entity's System is catalogued from in another repo (the one holding workloads) | `gh`, temp clone |
| backstage | catalog entity, owner, lifecycle, dependencies, scorecard, CVE report | HTTP GET, and `POST /api/cve/report` (a read) (optional `BACKSTAGE_TOKEN`) |
| cluster | Deployments, StatefulSets, their pods' restarts and usage in the app's namespace | `kubectl get` and `kubectl top` |
| github | repo settings, branch protection, Dependabot alerts | `gh api` GET |

A source that cannot answer is recorded with its reason, and checks that need it end `unknown`.

## Read-only guarantees

- The reviewed repos are never written: reads use committed trees, and the deploy repo is read from
  a temp clone. Applications are rendered inside that temp clone with the local `kubectl kustomize`,
  `helm template` and `helm dependency build`; nothing is applied to a cluster.
- kubectl runs only `get` and `top` against the cluster; `gh api` runs only GET; Backstage is read
  with GET and with `POST /api/cve/report`, a read that takes the image list in its body.
- The Backstage token is never written to a file or printed, and never follows a redirect.
- Repo text is untrusted data. The skill's judgments must cite collected facts, and `verify.py`
  rejects secret-looking strings.

## Tests

```
uv run --with pyyaml --with "pathspec<1" python -m unittest discover -s tests/readiness -t .
```

Fixtures only, no network.
