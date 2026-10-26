# Portal Scorecard and Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Backstage portal runs the RHDH Scorecard (4.2.0) with GitHub open-PR, Dependabot and file-check metrics, a Scorecard tab and a `readiness` MCP server. hk-demo opts in to Dependabot metrics.

**Architecture:** Config and package wiring in `arigsela/backstage`, checked by a contract script in the repo's existing `scripts/check-*-contract.sh` style. Then a portal image release, and a GitOps PR in `arigsela/kubernetes` that pins the image and adds one catalog annotation.

**Tech Stack:** Backstage 1.52 (new backend system, legacy `createApp` frontend), Yarn 4, bash and curl contract script, Argo CD GitOps.

**Spec:** `docs/superpowers/specs/2026-10-25-production-readiness-plugin-design.md`, §5 and §6 (in `arigsela/claude-agents`).

## Global Constraints

**Packages, pinned exactly with no caret:**

| Package | Version |
|---|---|
| `@red-hat-developer-hub/backstage-plugin-scorecard-backend` | `4.2.0` |
| `@red-hat-developer-hub/backstage-plugin-scorecard-backend-module-github` | `4.2.0` |
| `@red-hat-developer-hub/backstage-plugin-scorecard-backend-module-filecheck` | `1.0.2` |
| `@red-hat-developer-hub/backstage-plugin-scorecard-backend-module-dependabot` | `1.0.2` |
| `@red-hat-developer-hub/backstage-plugin-scorecard` (app) | `4.2.0` |

**Lockfile:** the `yarn.lock` diff may add no new version of any `@backstage/*` package. If `-scorecard-node` or `-scorecard-common` resolve above `4.2.0`, pin both in root `resolutions`.

**Not in scope:**
- No OpenSSF, DORA, catalog, Jira or SonarQube modules.
- No change to `backstage.io/source-location` or `backstage.io/techdocs-ref` on any entity.
- No change to the existing `catalog` MCP server or to the `externalAccess` token.

**Config placement:** new config goes in `app-config.yaml` only. Before merging, check that `app-config.production.yaml` defines none of `backend.actions`, `mcpActions` or `scorecard`, since Backstage replaces arrays.

**Filecheck settings:**
- Files: `runbook: runbook.md`, `docs: docs.md`.
- Schedule: cron `0 6 * * *`, timeout 15 minutes, initial delay 5 minutes.
- Thresholds stay at their defaults.

**Annotation:** `github.com/dependabot: 'true'`, the exact string.

**Secrets:** never print `GITHUB_TOKEN`, `MCP_TOKEN` or any Vault value.

**Owner approvals:** pushing an image to ECR, merging PRs, and changing the hk-demo repo setting are owner actions. Ask before each one.

## Review Focus

These are the inputs most likely to bite that no other test covers. Each has its check in the named task.

1. **Production config drops a new array:** the prod contract run in Task 4 fails loudly, rather than the tab silently missing.
2. **Entities with no `github.com/project-slug`** (11 of 42 components have no source-location at all): metrics for them are `status: error` and the backend keeps running. Task 4 reads the first collection's logs.
3. **The first daily filecheck run straining the 1 Gi pod:** Task 4 watches `kubectl top` during the 06:00 run, with the fallback "remove the module" spelled out.
4. **The existing kagent `backstage-catalog` RemoteMCPServer breaking** after the image bump: Task 4 asserts `Discovered 3 MCP tools`.
5. **The Scorecard tab on a component with no GitHub slug and no metrics** (11 components have no source-location): it renders an empty state, not an error boundary. Task 1 Step 4 opens one such component.

---

### Task 1: Scorecard in the portal (`arigsela/backstage`)

Work in a worktree branched from `origin/main` (`feat/scorecard`). The local checkout sits on the merged `feat/kagent-token`.

**Files:**
- Create: `scripts/check-scorecard-contract.sh`
- Modify:
  - `packages/backend/package.json`, `packages/app/package.json`, `yarn.lock` (and root `package.json` `resolutions` if needed)
  - `packages/backend/src/index.ts`: add four `backend.add(import(...))` lines after the MCP Actions block, with a comment block in the file's style.
  - `packages/app/src/components/catalog/EntityPage.tsx`: add a `scorecardRoute`, mirroring `securityRoute` at line 193.
  - `app-config.yaml`: `backend.actions.pluginSources` at about line 41, `mcpActions.servers` at about line 341, and a new top-level `scorecard:` block.
  - `CLAUDE.md`: one paragraph on the scorecard and the contract script.

**Interfaces:**
- Produces:
  - `GET /api/scorecard/metrics`
  - `GET /api/scorecard/metrics/catalog/{kind}/{ns}/{name}`
  - MCP server `/api/mcp-actions/v1/readiness` with tools `get-entity-metrics`, `list-metrics`, `get-catalog-entity`, `query-catalog-entities`
  - Entity tab `/scorecard` on the service, website and default pages
  - `scripts/check-scorecard-contract.sh`: env `BACKSTAGE_URL` (default `http://localhost:7007`), optional `ENTITY_REF` and optional `BACKSTAGE_TOKEN`. Exit codes match `check-cve-contract.sh`: 0 holds, 1 violation, 2 unreachable or not installed.

- [ ] **Step 1: Write the contract script (the failing test).** It checks, in order:
  1. `GET /api/scorecard/metrics` answers 200. A 404 exits 2 with `scorecard not installed`. The ids it lists include `github.openPRs`, `filecheck.runbook`, `filecheck.docs` and at least one id starting `dependabot.`.
  2. An MCP `tools/list` POST to `/api/mcp-actions/v1/readiness` returns exactly those four names. Send headers `Content-Type: application/json` and `Accept: application/json, text/event-stream`, and parse the `data:` line of the SSE body.
  3. `tools/list` on `/api/mcp-actions/v1/catalog` returns exactly `get-catalog-entity`, `get-catalog-model-description` and `query-catalog-entities`.
  4. Only when `ENTITY_REF` is set: `GET /api/scorecard/metrics/catalog/<kind>/<ns>/<name>` has `github.openPRs`, `filecheck.runbook` and `filecheck.docs` with top-level `status == "success"` and a non-null `result.value`. Dependabot metrics are printed but don't fail (they depend on the repo setting).

  `Authorization: Bearer $BACKSTAGE_TOKEN` is sent only when the variable is set.

- [ ] **Step 2: Run it against the current code to see it fail.**
  - Run: `docker compose up -d && yarn install && yarn start backend` (with your `.env` from `.env.example`). In another shell, run `bash scripts/check-scorecard-contract.sh`.
  - Expected: exit 2, `scorecard not installed`.

- [ ] **Step 3: Install and wire.**
  1. `yarn workspace backend add` the four backend packages at their exact versions, and `yarn workspace app add` the frontend package.
  2. Check that `git diff origin/main -- yarn.lock | grep '^+"@backstage/'` prints nothing. Add `resolutions` if it does.
  3. In `EntityPage.tsx`, add:

     ```tsx
     const scorecardRoute = (
       <EntityLayout.Route path="/scorecard" title="Scorecard"><EntityScorecardContent /></EntityLayout.Route>
     );
     ```

     The import is from `@red-hat-developer-hub/backstage-plugin-scorecard/legacy`. Place `{scorecardRoute}` right after `{securityRoute}` in `serviceEntityPage`, `websiteEntityPage` and `defaultEntityPage`, not in `kagentAgentPage`.
  4. In `app-config.yaml`, add the config exactly as spec §5 gives it, including the filecheck schedule.

- [ ] **Step 4: Run the checks.**
  - Run: `yarn tsc && yarn lint:all && yarn test && yarn build:all`. Expected: all green.
  - Restart the backend, then run `bash scripts/check-scorecard-contract.sh`. Expected: exit 0 for checks 1–3, with check 4 skipped.
  - Open `http://localhost:3000` on a component with a `github.com/project-slug`, then on one without. Expected: both Scorecard tabs render, the second as an empty or "no metrics" state with no error boundary.

- [ ] **Step 5: Commit and open the PR.** Use the message `feat(scorecard): RHDH scorecard 4.2.0 with GitHub, Dependabot and file-check metrics, and a readiness MCP server`. The PR body states the lockfile check from Global Constraints and its result. The owner merges.

---

### Task 2: Release portal `v1.6.0`

**Files:** none (a release).

**Interfaces:**
- Consumes: the Task 1 merge on `main`.
- Produces: `852893458518.dkr.ecr.us-east-2.amazonaws.com/backstage-portal:v1.6.0@sha256:<digest>`

- [ ] **Step 1: Ask the owner to approve the push.** `build-and-push.sh` pushes to ECR and ends with `kubectl rollout restart deployment/backstage`. That restart re-pulls the digest that is already pinned, so it is harmless, but it is still a cluster action.
- [ ] **Step 2: Build from merged main.** Run: `git checkout main && git pull && ./scripts/build-and-push.sh --version v1.6.0`. Expected: the push succeeds for `:v1.6.0`.
- [ ] **Step 3: Record the digest.** Run: `aws ecr describe-images --repository-name backstage-portal --image-ids imageTag=v1.6.0 --query 'imageDetails[0].imageDigest' --output text`. Expected: `sha256:` followed by 64 hex characters. It goes in Task 3.

---

### Task 3: GitOps change (`arigsela/kubernetes`)

Work in a worktree branched from `origin/main` (`feat/backstage-scorecard`). The local checkout is on `feat/hk-demo-valkey` and has untracked files; don't touch it.

**Files:**
- Modify:
  - `base-apps/backstage/deployments.yaml`: the image becomes `…/backstage-portal:v1.6.0@sha256:<digest from Task 2>`.
  - `base-apps/backstage/docs.md`: a scorecard section covering what runs, the daily filecheck and why, the `readiness` MCP server at `/api/mcp-actions/v1/readiness`, and the rule that `source-location` drives both filecheck and TechDocs. Also update the release version line.
  - `base-apps/hk-demo/catalog-info.yaml`: add `github.com/dependabot: 'true'` under `annotations`. Nothing else changes.
  - `base-apps/backstage/docs/index.md`: generated by `gen-techdocs.py`.

**Interfaces:**
- Consumes: the Task 2 digest.

- [ ] **Step 1: Make the edits, then regenerate.** Run: `python scripts/gen-techdocs.py --repo-root .`. Expected: only `base-apps/backstage/docs/index.md` changes.
- [ ] **Step 2: Validate the way CI does.** Expected: all pass. Run:
  - `yamllint -c .yamllint.yaml base-apps/backstage/deployments.yaml base-apps/hk-demo/catalog-info.yaml`
  - `python scripts/gen-techdocs.py --repo-root . --check`
  - `python scripts/validate-agent-docs.py --repo-root .`
  - `python scripts/validate-catalog-refs.py --repo-root .`
  - `python -m pytest tests/techdocs/ -q`
- [ ] **Step 3: Commit and open the PR.** Use the message `feat(backstage): portal v1.6.0 (scorecard + readiness MCP server); hk-demo opts in to Dependabot metrics`. The owner merges, and Argo CD deploys.

---

### Task 4: Turn on, then check live

**Files:** none.

- [ ] **Step 1: The owner turns on Dependabot alerts for `arigsela/hk-demo`.** Do it in Settings → Code security, or run `gh api -X PUT repos/arigsela/hk-demo/vulnerability-alerts` with the owner's OK. Run: `gh api -i repos/arigsela/hk-demo/vulnerability-alerts | head -1`. Expected: `HTTP/2.0 204`.
- [ ] **Step 2: Confirm the rollout.** Run: `kubectl -n backstage get deploy backstage -o jsonpath='{.spec.template.spec.containers[0].image}'`. Expected: `:v1.6.0@sha256:<digest>`. Then `kubectl -n backstage rollout status deploy/backstage`. Expected: `successfully rolled out`.
- [ ] **Step 3: Read the first collection's logs** (Review Focus 2). Run: `kubectl -n backstage logs deploy/backstage --since=20m | grep -i scorecard | tail -40`. Expected: no crash loop. Per-entity "missing annotation" errors are fine; repeated stack traces that stop collection are not.
- [ ] **Step 4: Run the contract against production.** Run: `BACKSTAGE_URL=https://backstage.arigsela.com ENTITY_REF=component:hk-demo/hk-demo bash scripts/check-scorecard-contract.sh`. Expected: exit 0. If `filecheck.*` values are still null before the first 06:00 run, re-run after it. Review Focus 1 is this run passing at all.
- [ ] **Step 5: Check that kagent still sees the catalog tools** (Review Focus 4). Run: `kubectl -n kagent get remotemcpservers.api.kagent.dev backstage-catalog -o jsonpath='{.status.conditions[0].message}'`. Expected: `Discovered 3 MCP tools`.
- [ ] **Step 6: Watch the first daily filecheck run** (Review Focus 3). Run `kubectl -n backstage top pod -l app=backstage` every minute from 06:00 for 15 minutes.
  - **Expected:** memory under 900Mi and no restart (`kubectl -n backstage get pod -l app=backstage` shows 0 new restarts).
  - **If not:** open a follow-up PR in `arigsela/backstage` that removes the filecheck module and its config, and note it in `base-apps/backstage/docs.md`.
- [ ] **Step 7: Check that the skill now reads the scorecard.** Run `/production-readiness ~/git/hk-demo`. Expected:
  - `sources.scorecard ok`;
  - `ops.open_prs` pass;
  - `sec.dependabot` no longer `fail (alerts off)`; it shows the alert counts' evaluation.
