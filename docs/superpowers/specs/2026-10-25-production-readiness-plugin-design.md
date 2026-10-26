# Production readiness plugin — Design

**Date:** 2026-10-25
**Status:** Draft for the owner's review. §2 lists what the owner decided. The owner skipped the
design questions, so everything else here is the designer's call, and is marked as such where it
matters.
**Repos:** `arigsela/claude-agents` (the plugin), `arigsela/backstage` (the portal: scorecard and
MCP server), `arigsela/kubernetes` (one catalog annotation and a version bump). The repo under
review (first one: `arigsela/hk-demo`) is only read, never changed.

## 1. Why

Before an app is called "production", someone should walk it against a known list:

- **Owner:** who owns it?
- **Reliability:** will it survive a node drain?
- **Secrets:** are they out of Git?
- **Vulnerabilities:** does the image carry critical CVEs?
- **Alerting:** will anyone know when it breaks?

Today that walk is done from memory, one app at a time. The evidence for it is spread over four
places:

- the app repo (CI, Dockerfile, tests);
- the GitOps repo (probes, limits, network policy, runbook);
- the Backstage portal (owner, dependencies, CVEs);
- the live cluster (restarts, real usage).

A skill can gather that evidence, sort it under the six AWS Well-Architected pillars, and say
plainly what is missing. Add an Operational Readiness Review (ORR) checklist for the questions only
a person can answer.

Backstage should become the place where the continuous part of this lives. A scorecard on each
entity page keeps the checks that change hour to hour (open Dependabot alerts, open PRs, missing
runbook) visible between reviews. The skill reads that scorecard as one more source.

## 2. Decisions taken (owner)

| Question | Decision |
|---|---|
| Scorecard | Red Hat Developer Hub (RHDH) Scorecard plugin, version **4.2.0**. Its core dependencies (`backend-defaults` ^0.17.3, `catalog-model` ^1.9.0, `backend-plugin-api` ^1.9.2) are already in the portal's lockfile. 4.5.2 needs `backend-defaults` ^0.17.8 (the lockfile tops out at 0.17.4), which would add a second copy of a core package. Moving past 4.2.0 waits for a Backstage upgrade. |
| Output | Printed in the terminal for now. No HTML page. |
| Where the skill lives | This repo, as a plugin. |

## 3. Goals, non-goals, anti-goals

**Goals**
- `/production-readiness <path-to-repo>` prints a readiness report. It covers the six pillars plus
  the ORR checklist, and ends with a verdict and the fixes ranked by impact.
- Every pass or fail in the report cites its evidence: a file and line, an API URL, or a kubectl
  command.
- The portal runs the RHDH Scorecard: an entity-page tab, the REST API, and a `readiness` MCP
  server that serves the scorecard and catalog tools to agents.
- The report degrades gracefully. When a source is down (Backstage, the cluster, a checkout), the
  checks that needed it say "unknown" and why, and the rest of the report still prints.

**Non-goals (v1)**
- **Fixing findings.** The skill reports and does not edit the repo it reviews.
- **Recording reviews in the AWS Well-Architected Tool.** That needs an AWS workload, and this is a
  homelab cluster.
- **Fixing the portal's auth.** `backend.auth.dangerouslyDisableDefaultAuthPolicy: true` is a known
  gap, tracked in §10.
- **The OpenSSF module.** It only reads published OpenSSF results, which exist only for public
  repos. hk-demo is private, and its public API lookup returns 404.
- **DORA metrics, the catalog module, and the Jira and SonarQube modules.** The DORA and catalog
  modules have no Backstage 1.52-compatible release. There is no Jira or SonarQube in this setup.
- **Wiring a kagent agent to the new MCP server.** That is a follow-up.
- **A numeric overall score.**

**Anti-goals** (would make it a failure even if it runs)
- **A pass with nothing behind it.** A check the skill could not evaluate must say "unknown", never
  "pass". This is the same rule as hk-demo's "every ✓ comes from data".
- **Invented AWS best-practice IDs.** A check with no real match says so.
- **Writing to anything while reviewing.** No kubectl verbs other than `get` and `top`, no `POST`
  to Backstage except the CVE report lookup (which is a read), and no GitHub writes.
- **A wall of text.** A busy reader should get the verdict and the top fixes from the first screen.

## 4. Overview and order

| Part | Repo | What |
|---|---|---|
| A | `arigsela/backstage` | Install the scorecard (backend 4.2.0 and three modules, frontend 4.2.0), and add the `readiness` MCP server. Release a new portal image. |
| B | `arigsela/kubernetes` | Bump the portal image. Add the `github.com/dependabot: 'true'` annotation to hk-demo's catalog entry, and update Backstage's docs. |
| C | `arigsela/claude-agents` | The `readiness` plugin: scripts, checks catalog, skill and tests. |

C does not depend on A or B. The scorecard is one optional source, and the checks that read it say
"unknown" until it exists. So C can be built first or in parallel. The owner also turns on
Dependabot alerts for `arigsela/hk-demo`, which is a repo setting, off today (§6).

## 5. Part A — scorecard in the portal (`arigsela/backstage`)

**Packages, pinned exactly with no caret.** A caret would let yarn take 4.5.x, which needs a newer
Backstage.

| Workspace | Package | Version |
|---|---|---|
| backend | `@red-hat-developer-hub/backstage-plugin-scorecard-backend` | `4.2.0` |
| backend | `…-scorecard-backend-module-github` (open PRs) | `4.2.0` |
| backend | `…-scorecard-backend-module-filecheck` (file existence) | `1.0.2` |
| backend | `…-scorecard-backend-module-dependabot` (alerts by severity) | `1.0.2` |
| app | `@red-hat-developer-hub/backstage-plugin-scorecard` | `4.2.0` (needs `core-plugin-api` ^1.12.7; 1.52 ships 1.12.7) |

All of these were released 2026-08-07, and their `-scorecard-node` and `-scorecard-common`
dependencies are `^4.2.0`. Those carets can resolve to 4.5.x. If they do, add root `resolutions`
pinning both to `4.2.0`.

**Done means** two things:
- The `yarn.lock` diff adds only `@red-hat-developer-hub/*` packages and their non-Backstage
  dependencies, with no new version of any `@backstage/*` package.
- The backend starts with the scorecard loaded.

The lockfile already holds `backend-plugin-api` 1.9.0, 1.9.2 and 1.10.1 (since PR #43, the CVE
fix). That is fine: the bar is "no new copies", not "one copy".

**Wiring**
- **Backend.** In `packages/backend/src/index.ts`, add four `backend.add(import(...))` lines after
  the catalog.
- **Frontend.** The app uses the legacy `createApp` from `@backstage/app-defaults`. In
  `packages/app/src/components/catalog/EntityPage.tsx`, add an
  `<EntityLayout.Route path="/scorecard" title="Scorecard">` with `EntityScorecardContent`,
  imported from `@red-hat-developer-hub/backstage-plugin-scorecard/legacy`. The route goes on the
  service, website and default entity pages.
- **Database.** None to set up: the portal creates each plugin's database itself
  (`backstage_plugin_cve` appeared that way), so `backstage_plugin_scorecard` will too.

**Config.** In `app-config.yaml`. `app-config.production.yaml` defines neither `backend.actions`
nor `mcpActions`, so production inherits both. Re-check that before merging: arrays are replaced,
not merged.

```yaml
backend:
  actions:
    pluginSources:
      - catalog
      - scorecard          # new: lets mcp-actions see scorecard:get-entity-metrics / list-metrics

mcpActions:
  namespacedToolNames: false   # unchanged
  servers:
    catalog: { ... }           # unchanged; kagent's backstage-catalog RemoteMCPServer uses it
    readiness:                 # new: /api/mcp-actions/v1/readiness
      name: readiness
      filter:
        include:
          - id: 'scorecard:*'
          - id: 'catalog:get-catalog-entity'
          - id: 'catalog:query-catalog-entities'

scorecard:
  metricProviders:
    filecheck:
      fileExistence:
        options:
          files:
            runbook: runbook.md
            docs: docs.md
        schedule:                # daily, not the hourly default: see below
          frequency: { cron: '0 6 * * *' }
          timeout: { minutes: 15 }
          initialDelay: { minutes: 5 }
```

Why daily (designer's call, measured 2026-10-25): filecheck calls `readTree` on each entity's
`source-location`. The GitHub reader downloads the whole repo archive for that, then filters to the
subpath. The kubernetes repo's archive is 105 MB, and 25 of the 42 components point into it. An
hourly run after any commit to `main` would pull about 2.6 GB. Daily keeps it to one burst at
06:00. If the first run strains the portal (2 CPU / 1 Gi), remove the filecheck module: the skill
checks `runbook.md` and `docs.md` itself.

> **Amended 2026-10-26: filecheck removed (portal v1.6.1, arigsela/backstage#45).** It ran 5
> minutes after the v1.6.0 pod started, not only at 06:00 (`initialDelay` applies to cron tasks
> too). That run stalled the event loop and the DB pool (`KnexTimeoutError`, GitHub socket
> hang-ups). `/healthcheck` stopped answering, and the liveness probe killed the pod with exit
> 137. Memory stayed flat at about 520 Mi, so this was not an OOM. The killed run retries when its
> 15-minute task lock expires, so the pod would loop. The contract script now fails if a
> `filecheck.*` metric is registered. The skill's `ops.runbook` still reads `filecheck.runbook`
> as a fallback when the deploy folder is unreadable, and treats the absent metric as unknown.

Why only `runbook` and `docs` (designer's call): filecheck reads the folder named by the entity's
`backstage.io/source-location`.

- For apps whose catalog entry lives in the kubernetes repo, that folder is `base-apps/<app>/`.
  For hk-demo it is `url:https://github.com/arigsela/kubernetes/tree/main/base-apps/hk-demo/`,
  checked live.
- The agent-docs contract puts `docs.md` and `runbook.md` there for every app, so those two checks
  mean the same thing for every entity.
- App-repo files (CODEOWNERS, SECURITY.md, dependabot.yml) are checked by the skill from the local
  checkout instead.
- `source-location` must not be repointed at the app repo. TechDocs resolves
  `backstage.io/techdocs-ref: dir:.` against it (`transformDirLocation` →
  `getEntitySourceLocation`), so repointing it would break hk-demo's Docs tab.

Keep the default thresholds. Keep the hourly schedule for the GitHub and Dependabot modules (API
calls, well under the PAT's 5000/hour).

**The portal's GitHub token.** The Dependabot module reads alerts with the portal's
`GITHUB_TOKEN`. For private repos, that token needs Dependabot alerts read access (classic PAT:
`repo` or `security_events`). Verify by calling the alerts API with that token, and never print the
token.

**Static token.** The existing `externalAccess` static token (subject `kagent-catalog-reader`) has
no `accessRestrictions`, so it already reaches the scorecard. Leave it as it is. The skill uses
`BACKSTAGE_TOKEN` when it is set, and sends no header when it isn't (§7.6).

**Release.** Portal `v1.6.0` (a minor bump for a new plugin). The image tag bump in kubernetes is
Part B.

**Done when (checked live after deploy)**
1. `GET /api/scorecard/metrics/catalog/component/hk-demo/hk-demo` returns `github.openPRs`,
   `filecheck.runbook` and `filecheck.docs` with values. The Dependabot metrics return values once
   §6 is done.
2. An MCP `tools/list` on `/api/mcp-actions/v1/readiness` shows `get-entity-metrics`,
   `list-metrics`, `get-catalog-entity` and `query-catalog-entities`.
3. `/api/mcp-actions/v1/catalog` still lists its three tools, and kagent's `backstage-catalog`
   RemoteMCPServer still reports `Discovered 3 MCP tools`.
4. The hk-demo entity page shows a Scorecard tab.

## 6. Part B — kubernetes repo and GitHub setting

- **Portal image.** Bump the image in `base-apps/backstage/deployments.yaml` to `v1.6.0`, pinned by
  digest like today.
- **Backstage docs.** Update `base-apps/backstage/docs.md`: the scorecard, the `readiness` MCP
  server, and the filecheck folder rule from §5. Regenerate the TechDocs mirror with
  `scripts/gen-techdocs.py`, because CI runs it with `--check`.
- **hk-demo catalog entry.** In `base-apps/hk-demo/catalog-info.yaml`, add
  `github.com/dependabot: 'true'`. The exact string is required to opt in. Change nothing else.
- **Owner action.** Turn on Dependabot alerts for `arigsela/hk-demo`. They are disabled today: the
  API answered "Dependabot alerts are disabled for this repository". It is a reversible repo setting
  (Settings → Code security, or `gh api -X PUT repos/arigsela/hk-demo/vulnerability-alerts`).
  Adding a `.github/dependabot.yml` to hk-demo is a finding the skill will report, not part of this
  work.

## 7. Part C — the plugin (`arigsela/claude-agents`)

### 7.1 Layout

```
skills/readiness/                         plugin "readiness"
├── .claude-plugin/plugin.json
├── README.md
├── checks.yaml                           the check catalog (§8): data, not code
├── scripts/
│   ├── collect.py      repo path → facts.json (app repo, deploy folder, Backstage, cluster)
│   ├── evaluate.py     facts.json + checks.yaml → results.json (rule checks decided, judgment checks stubbed)
│   ├── verify.py       report.json vs facts/results → ok, or the list of violations
│   └── render.py       report.json → the terminal report (markdown on stdout)
└── skills/production-readiness/SKILL.md
tests/readiness/                          pytest, fixtures only, no network
```

**Conventions:**
- Same as the explainer plugin: Python run with `uv run --script` and PEP 723 inline dependencies
  (`pyyaml` is fine).
- SKILL.md calls scripts as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py`.
- Register the plugin in `.claude-plugin/marketplace.json` and `skills/skills-catalog.json`.
- Add it to the projects table and Key files in `CLAUDE.md`.

### 7.2 Invocation

```
/production-readiness <repo-path> [--ref REF] [--entity kind:ns/name] [--deploy-ref REF] [--no-live] [--out DIR]
```

- **`<repo-path>`:** a local checkout of the app repo (for example `~/git/hk-demo`). The default is
  the current directory.
- **`--ref`:** which commit of the app repo to review. The default is the checkout's HEAD.
  Reviews read committed trees only: never the working tree, never untracked files.
- **`--entity`:** skips the lookup when the repo is not in the catalog, or maps to more than one
  entity.
- **`--deploy-ref`:** which revision of the deploy repo to review. The default is what Argo CD
  deploys (§7.3). Use this to review a deploy-repo branch or PR instead.
- **`--no-live`:** skips the cluster. Live reads are on by default (designer's call): they are
  read-only, and restarts and real usage are the strongest reliability evidence there is.
- **`--out`:** where `facts.json`, `results.json` and `report.json` go. The default is a new temp
  directory, so nothing lands in the reviewed repo. Its path is printed at the end.

### 7.3 Finding everything from one repo path

1. **Repo slug.** Read `git remote get-url origin` and turn it into `owner/name`. Also record the
   branch, the reviewed SHA, and whether that commit is on origin's default branch (`git ls-remote`;
   never fetch into the user's checkout). Read files at that commit the way the explainer's
   `Trees.at` does.
2. **Catalog entity.** Call
   `GET {BACKSTAGE_URL}/api/catalog/entities/by-query?filter=metadata.annotations.github.com/project-slug=<slug>`,
   URL-encoded (unencoded, it returns an empty body). This was checked live: `arigsela/hk-demo`
   resolves to `component:hk-demo/hk-demo`.
   - **No match:** the catalog check fails, and the report continues on the app repo alone.
   - **Several matches:** list them and stop, asking for `--entity`.
3. **Deploy folder.** It comes from the entity's `backstage.io/managed-by-location`, for example
   `url:https://github.com/arigsela/kubernetes/tree/main/base-apps/hk-demo/catalog-info.yaml` →
   repo `arigsela/kubernetes`, folder `base-apps/hk-demo/`.

   The deploy repo is always read from a temp blobless clone made through `gh` and deleted
   afterwards. Never read the user's local checkout (designer's call). That checkout may sit on
   another branch, and may hold untracked files. `~/git/kubernetes` has both today: branch
   `feat/hk-demo-valkey`, and an untracked `app-token.txt`.

   When the catalog entry sits in the app repo itself, the deploy folder is unknown.
4. **Rendered manifests.** On the default branch, find the Argo CD Application whose source is
   that folder (for hk-demo, `base-apps/hk-demo.yaml`). Then read the folder at that Application's
   `targetRevision`, or at `--deploy-ref`, so the review matches what is deployed. Render it the
   way the explainer does: plain directory, kustomize or Helm. The explainer's `facts_lib.py`
   already does this (`find_applications`, `render_app`). How to share it is left to the builder
   (§12); do not write a second renderer. If rendering fails, fall back to the raw YAML in the
   folder and say so.
5. **Workloads in scope** (designer's call). The review covers every workload the Application
   renders: for hk-demo, the app and its Valkey (`valkey.yaml`, merged 2026-10-25). The report
   groups per-container findings by workload. Images are the container images in those workloads.
6. **Live reads.** These cover the entity's `backstage.io/kubernetes-namespace` and match pods to
   the rendered workloads by owner (Deployment/StatefulSet name). They do not use the entity's
   label selector: hk-demo's `app=hk-demo` misses Valkey (`app: valkey`). A rendered workload that
   the cluster doesn't have gets unknown for the live checks, with the reason "not found live".

### 7.4 Facts (`facts.json`)

Every fact has:
- a stable `id` (for example `deploy.container.hk-demo.readinessProbe`);
- a `source`: `app`, `deploy`, `backstage`, `cluster` or `github`;
- the `value`;
- `evidence`: `file:line`, an API URL, or the exact read-only command run.

**Sources and their failures:**

| Source | Read | When it fails |
|---|---|---|
| App repo | Dockerfile; workflows (triggers, steps, `permissions`, `uses:` pins); lockfiles; tests dir; README, CODEOWNERS, SECURITY.md, `.github/dependabot.yml` / `renovate.json`; observability deps (OpenTelemetry, prometheus client) | Always available (it's the input) |
| Deploy folder | Rendered workloads (replicas, probes, resources, securityContext, image refs, SA token automount), NetworkPolicy, PDB, HPA, Secret/ExternalSecret kinds, HTTPRoute, runbook.md, docs.md | The checks that need it are unknown ("no deploy folder") |
| Backstage | Entity (owner, lifecycle, system, dependsOn, providesApis); each dependsOn entity's lifecycle; `POST /api/cve/report {"images":[…]}`; `GET /api/scorecard/metrics/catalog/{kind}/{ns}/{name}` | The checks that need it are unknown, with the HTTP status. A 404 from scorecard means "not installed yet" |
| Cluster | `kubectl get pods,deploy,statefulset,hpa,pdb -n <ns> -o json`; `kubectl top pods -n <ns>` (matched to rendered workloads, §7.3) | The checks that need it are unknown. They are also unknown with `--no-live`, or when the context can't reach the namespace within 5s |
| GitHub | `gh api repos/<slug>/vulnerability-alerts` (204 = Dependabot alerts on; 404 on a repo `gh` can read = off); branch protection on the default branch | Unknown on 403, or when the repo itself isn't readable |
| Alert rules | `base-apps/logging/grafana-alerting.yaml` in the deploy checkout: rules that name the namespace or workload, and generic rules over all namespaces | Unknown if the file is absent |

Never put secret values, tokens, or Secret `data` into facts. Only kinds, names and keys go in.

### 7.5 Checks, statuses, verdict

- **Check kinds.** Each check in `checks.yaml` (§8) has a `kind`:
  - **`rule`:** `evaluate.py` decides the status from facts.
  - **`judgment`:** the model decides it from facts that `evaluate.py` lists as candidates.
  - **`person`:** an ORR question only a human can answer. The script lists what it found that
    might help (for example, docs lines mentioning "rollback" or "SLO").
- **Statuses:** `pass`, `partial`, `fail`, `unknown`, `n/a`.
- **Verdict:**
  - **Not ready:** any `blocker` check fails.
  - **Ready with gaps:** otherwise, when any check fails or is partial, or any blocker is unknown.
  - **Ready:** none of the above.

  Person checks never change the verdict. They are listed under "Needs a person".
- **What the model writes** (`report.json`): the status and a reason (with fact ids) for each
  judgment check, a one-line note for each pillar, and up to five ranked fixes, each tied to check
  ids. It never changes a rule check's status.
- **What `verify.py` rejects:**
  - a changed rule status;
  - a judgment pass or fail without at least one existing fact id;
  - a pass whose cited facts are all missing values;
  - a fix that names no failing or partial check;
  - a check missing from the report.

  The skill fixes the report and re-verifies before printing. If it still fails, it prints with an
  "unverified" banner.

### 7.6 Backstage access

- **URL.** `BACKSTAGE_URL`, default `https://backstage.arigsela.com`.
- **Token.** `Authorization: Bearer $BACKSTAGE_TOKEN` when the variable is set, and no header
  otherwise. The API answers without a token today, because the default auth policy is off, but
  the skill must keep working once that is fixed.
- **REST, not MCP** (designer's call). The facts come from scripts, and a script can't call Claude
  Code's MCP tools. REST also keeps facts deterministic and testable against recorded responses.
  The `readiness` MCP server (Part A) is for agents and interactive sessions.

### 7.7 Report (terminal)

`render.py` prints markdown, and the skill shows it as is. Order:

1. **Header:** the entity ref, owner, lifecycle, and the reviewed ref of each repo (branch, SHA,
   whether it is on the default branch; for the deploy repo, the Application's `targetRevision`).
   Also the scorecard timestamp, and which sources answered and which did not.
2. **Verdict** and the **top fixes**: at most five, each one line with the check id and where to
   fix it.
3. **Pillar summary:** one table row per pillar, with counts of each status.
4. **Findings by pillar:** fail and partial first, then unknown. Passes are collapsed to one line
   per pillar listing the check ids.
5. **Needs a person:** the ORR questions, with any hints found.
6. **Not checked:** the sources that were unavailable, and why.

Aim for the verdict and the fixes to fit on the first screen.

### 7.8 Tests (`tests/readiness/`)

- **Fixtures.** A tiny app repo and deploy folder built in `tmp_path`; recorded Backstage JSON
  (entity, CVE report, scorecard with one metric in error); recorded kubectl JSON. No network.
- **Rule checks.** Every rule check has at least one passing and one failing fixture.
- **Degradation.** Backstage returning 500, scorecard returning 404, and no kubectl each give
  unknowns and still produce a report.
- **`verify.py`.** It rejects each violation listed in §7.5.
- **`render.py`.** A golden-file test of the output.
- **Safety.** A test that fails if any fixture secret value or token appears in `facts.json` or the
  output.

**Live acceptance** (manual, not in CI): `/production-readiness ~/git/hk-demo`. It should run end
to end, covering both workloads (the app and Valkey), and its findings should match a hand check
done at build time.

The hand check from 2026-10-25 predates Valkey and hk-demo v0.7.0, so re-observe before comparing.
On 2026-10-25 it showed:
- the app's images pinned by digest;
- non-root, read-only root filesystem;
- startup, liveness and readiness probes;
- one replica, intentional per the manifest comment, and no PDB;
- Dependabot alerts off;
- no `dependabot.yml`;
- CI actions pinned by SHA;
- alerting covered only by the generic CPU and memory rules.

Expected verdict on that state: **Ready with gaps** (`ops.alerts` partial; no blocker fails).

## 8. Check catalog v1

Each entry has `id`, `pillar`, `title`, `kind`, `blocker`, `sources`, and `wa_ref`. The `wa_ref` is
the Well-Architected best practice the check supports: its ID and docs URL, looked up by the builder
on docs.aws.amazon.com. A check with no real match carries `wa_ref: none`; never a guess. Each
`person` check carries an `orr` tag. The list below is the starting set; adding a check is a data
change.

| id | pillar | check | kind | blocker |
|---|---|---|---|---|
| ops.catalog | Operational excellence | In the catalog with an owner, lifecycle and system | rule | yes |
| ops.runbook | Operational excellence | A runbook exists in the deploy folder (scorecard `filecheck.runbook` only when the folder is unreadable) | rule | yes |
| ops.docs | Operational excellence | Service docs exist (README in the app repo, docs.md in the deploy folder) | rule | no |
| ops.ci | Operational excellence | CI runs on pull requests, with test and lint steps | judgment | yes |
| ops.release | Operational excellence | Release and deploy are automated and versioned (tagged images, GitOps pin) | judgment | no |
| ops.alerts | Operational excellence | Pass: a rule fires when this workload is down, crash-looping or erroring, whether specific (like `model-gateway-down`) or generic over all namespaces. Partial: only resource-pressure rules cover it (`pod-cpu-starved`, `container-near-memory-limit`). Fail: none. v1 reads Grafana rules only; the dispatcher acts on those same rules | judgment | yes |
| ops.telemetry | Operational excellence | Emits logs, metrics or traces that the platform collects | judgment | no |
| ops.open_prs | Operational excellence | Open PR count is within threshold (scorecard `github.openPRs`) | rule | no |
| sec.image_digest | Security | Every container image is pinned by digest | rule | no |
| sec.base_digest | Security | Dockerfile base images are pinned by digest | rule | no |
| sec.nonroot | Security | Runs as non-root (pod or container `runAsNonRoot`, Dockerfile `USER`) | rule | yes |
| sec.hardening | Security | `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, capabilities dropped | rule | no |
| sec.netpol | Security | A NetworkPolicy selects the pods | rule | no |
| sec.secrets | Security | No Secret manifests with data in Git, and secrets come from ExternalSecrets | rule | yes |
| sec.cve | Security | From `/api/cve/report`, which only keeps fixable CRITICAL/HIGH findings in images the weekly scan saw. Fail: any fixable critical. Partial: fixable highs. Unknown: any rendered image in `unmatchedRefs` (not scanned), named per image, or `ok:false`. The status is the worst of these (fail > partial > unknown > pass). Unfixable criticals aren't visible here; the report lists that under "Not checked" | rule | yes |
| sec.dependabot | Security | Dependabot alerts are on, and the open critical/high counts are within threshold | rule | no |
| sec.dep_updates | Security | A dependency update tool is configured (`dependabot.yml` or `renovate.json`) | rule | no |
| sec.actions_pinned | Security | Workflow `uses:` are pinned by SHA | rule | no |
| sec.token_perms | Security | Workflows declare least-privilege `permissions` | rule | no |
| sec.exposure | Security | Anything exposed (HTTPRoute) has auth in front (sidecar proxy, AuthorizationPolicy, or allow-list) | judgment | yes |
| sec.sa_token | Security | The service-account token is not mounted, or a dedicated SA is used | rule | no |
| sec.repo_hygiene | Security | CODEOWNERS and SECURITY.md exist; the default branch is protected | rule | no |
| rel.probes | Reliability | Readiness and liveness probes on every container | rule | yes |
| rel.resources | Reliability | CPU and memory requests and limits on every container | rule | yes |
| rel.replicas | Reliability | Two or more replicas, or one with a stated reason (the model reads the manifest comment) | judgment | no |
| rel.pdb | Reliability | A PodDisruptionBudget exists (n/a when one replica is justified) | rule | no |
| rel.restarts | Reliability | No restarts or OOMKills in the pods' current lifetime (live) | rule | no |
| rel.dependencies | Reliability | Every `dependsOn` entity is itself `production` (n/a for entities with no `lifecycle`, such as `resource:vault/vault`) | rule | no |
| rel.state | Reliability | Stateful dependencies (PVCs, databases) have backup/restore (n/a when stateless) | judgment | no |
| perf.scaling | Performance efficiency | An HPA exists, or the fixed size is justified | judgment | no |
| perf.rightsize | Performance efficiency | Live usage is under requests and nothing runs near its limits | rule | no |
| cost.overprovision | Cost optimization | Requests are not far above live usage (the threshold is the builder's call) | rule | no |
| cost.registry | Cost optimization | The image registry has a retention rule (Terraform in the deploy repo) | judgment | no |
| sus.utilization | Sustainability | Shares the usage facts; flags idle or oversized workloads | rule | no |
| orr.oncall | Operational excellence | Who gets paged, and how? | person | — |
| orr.slo | Reliability | Is there an SLO or an agreed error budget? | person | — |
| orr.rollback | Reliability | Has a rollback been done or rehearsed recently? | person | — |
| orr.load | Performance efficiency | Expected load and the plan when it is exceeded | person | — |
| orr.dep_failure | Reliability | What happens when each dependency is down? | person | — |
| orr.incident | Operational excellence | Has the runbook been used in an incident or drill? | person | — |

Sustainability and cost have few signals in a homelab. The report should say so, not pad them.

## 9. Risks and gotchas

- **Version drift.** Yarn carets can pull scorecard 4.5.x, which needs Backstage 1.54 or later.
  Pin exactly, and check with `yarn why`.
- **Config arrays.** Backstage config replaces arrays. Any array added to `app-config.yaml` must
  not also exist in `app-config.production.yaml`. If it does, add it to both.
- **mcp-actions 0.1.14.** With `servers` configured there is no default `/v1` endpoint. That is
  fine here, because both servers are named.
- **`source-location`.** It drives both filecheck and TechDocs (§5). Don't change it to make
  filecheck look at the app repo.
- **The Dependabot module needs three things:** the annotation, the repo setting, and token scope.
  Missing any one gives an error metric, which the skill shows as unknown, not as a pass.
- **The CVE endpoint** keys on image refs, not entities, so the skill must send the exact refs from
  the rendered manifests.
- **The wrong tree.** A review of a working tree or a feature branch can disagree with what runs.
  For example, `~/git/kubernetes` pins hk-demo v0.6.0 on its branch while `main` deploys v0.7.0.
  So the deploy repo is read at the Application's `targetRevision`, and the header names every
  reviewed ref.

## 10. Follow-ups (not in this work)

- **Portal auth.** Replace `dangerouslyDisableDefaultAuthPolicy` with real service-to-service
  keys, and give the skill its own static token (`subject: readiness-skill`,
  `accessRestrictions: [catalog, scorecard, cve]`). Today the IP allow-list is the only gate on the
  whole Backstage API, write endpoints included.
- **kagent.** Point a kagent agent (homelab-knowledge, or a readiness agent) at
  `/api/mcp-actions/v1/readiness`.
- **Upgrade.** After a Backstage 1.54+ upgrade, move to scorecard 4.5.x and consider the DORA
  module.
- **Write-back.** Write the skill's results back to Backstage (a custom metric provider reading a
  results file), so the review shows on the entity page.
- **Scaffolder.** Add `github.com/dependabot: 'true'` to the New Application template and the
  agent-docs contract, so new apps opt in by default.

## 11. Calls made after the builder review (designer's, for the owner to check)

1. **Alerting bar.** Only an availability rule (down, crash-looping or erroring) passes
   `ops.alerts`, and resource-pressure rules alone are partial. hk-demo lands at "Ready with gaps"
   on that.
2. **Scorecard 4.2.0 stays.** The reason is corrected in §2, and the "done" check in §5 changed
   from "one copy" to "no new copies".
3. **Workloads in scope.** A review covers every workload the Application renders (hk-demo plus
   Valkey). Live reads are by namespace, not by the entity's label selector.
4. **Which tree.** The deploy repo is read at the Application's `targetRevision` from a temp clone.
   The app repo is read at committed HEAD (or `--ref`), never the working tree.
5. **`sec.cve`.** It means "no fixable critical in scanned images", and unscanned images make it
   unknown.
6. **Daily file check.** Filecheck runs daily at 06:00, not hourly, because each run can download
   the 105 MB kubernetes archive once per entity (§5). Superseded 2026-10-26: its first run stalled
   the portal, so v1.6.1 removes it (§5).

## 12. Left to the builder

- **Sharing the renderer.** How the explainer's Application rendering is shared: a vendored copy
  with a sync check (the hk-demo `vendor_sync.py` pattern), or a shared module, given that plugins
  install separately.
- **Thresholds** for "far above usage" and "near limits".
- **The exact `checks.yaml` schema**, and the `wa_ref` lookups.
- **Wording** of the report, within §7.7's order.
- **Splitting the work into PRs** across the three repos, keeping §4's independence.
