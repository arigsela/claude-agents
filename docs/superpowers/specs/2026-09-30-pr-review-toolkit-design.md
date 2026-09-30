# PR Review Toolkit (triage, explainer, retro) — Design

**Date:** 2026-09-30
**Status:** Draft. The architecture and shared policy (§2–§4) and pr-triage (§5) were approved in conversation. The explainer (§6), retro (§7) and cross-cutting sections were written without section-by-section approval, at the owner's request. Every assumption is listed in §11.
**Repos:** `arigsela/claude-agents` (code and skills), `arigsela/kubernetes` (policy and workflow wiring)
**Components:** `pr-triage` (GitHub composite action), `pr-explainer` (skill), `review-retro` (skill)

## 1. Problem

Claude writes almost every PR in the homelab GitOps repo, and the owner merges them. Nobody submits a GitHub review.

Numbers from `arigsela/kubernetes`, measured 2026-09-30:

| Metric | Value |
|---|---|
| Merged PRs, 2026-08-12 → 2026-09-30 | 100 (77 of them in the last 7 days) |
| PRs with a GitHub review | 0 |
| Of the last 100, share touching `base-apps/` | 83% |
| Of the last 100, share touching `terraform/` | 3% |
| Of the last 200, share followed by a follow-up fix (§4) | 32% (63/200) |

The follow-up-fix rate by size bucket (lines added + removed):

| Bucket | Follow-up fix rate |
|---|---|
| tiny (≤10) | 5% |
| small (≤100) | 28% |
| medium (≤500) | 52% |
| large (>500) | 48% |

The components with the most follow-up fixes are `base-apps/istio-ingress` (14), `argo-workflow-tasks` (7) and `admission-policies` (6+7 including its tests).

The owner's attention is the scarce resource. Today it is spent evenly, which means mostly not at all.

**Goals**
- **G1 — Attention allocation.** Every PR gets `review:skip|skim|read` plus a reason, and nothing blocks.
- **G2 — Comprehension without code.** A GitOps PR can be understood from a grounded page that shows what changes and what is risky, plus an explicit list of the hunks a human must still read.
- **G3 — A reviewer that improves.** When a `/code-review` session missed something that later needed a fix, the owner learns why and gets concrete, cited edits to the reviewer.

**Non-goals**
- Auto-approve, auto-merge, or blocking checks.
- Running Terraform plans locally.
- GitLab support.
- Retros of reviewers other than the owner's `code-review` skill.
- A GitOps specialist inside `code-review`. That is the expected output of the retro, not part of this build.
- Test suites (owner's instruction; see A14).

## 2. Architecture

```
arigsela/kubernetes                                arigsela/claude-agents
───────────────────                                ──────────────────────
.github/review-policy.yaml  ◀── read by all three ──  pr-triage/ (composite action + pr_triage pkg)
.github/workflows/pr-triage.yaml ── uses @<sha> ──▶   skills/pr-explainer/  (plugin)
                                                      skills/review-retro/  (plugin)

PR opened/pushed ─▶ pr-triage ─▶ label review:{skip|skim|read} + sticky comment
                                   │ (comment on skim/read suggests the next commands)
owner or Claude ─▶ /pr-explainer <n> ─▶ private Artifact page + sticky "explainer" comment
owner or Claude ─▶ /code-review <n>  ─▶ session transcript in ~/.claude/projects
later ─▶ /review-retro <n> | --since 14d ─▶ report + proposed edits
                                            (code-review skill / review-policy.yaml)
```

- The GitOps repo holds the policy (what counts as risky) and the thin wiring.
- `claude-agents` holds all code and skills. The two skills are published through the existing marketplace (`.claude-plugin/marketplace.json`) and `skills/skills-catalog.json`.
- The kubernetes workflow pins the composite action by commit SHA. A change to triage logic takes two PRs: one for the code and one to bump the pin.

## 3. Shared review policy

**File:** `arigsela/kubernetes:.github/review-policy.yaml`.

**Who reads it:**
- Triage reads it from the **base branch**, so a PR cannot change the policy that is used to judge it. On top of that, `.github/**` is always-read.
- The skills read it from the local checkout.

```yaml
version: 1
always_read:                 # any match → review:read (Jev not called)
  paths:                     # gitignore-style globs, matched against changed paths
    - base-apps/dex/**
    - base-apps/dex.yaml
    - base-apps/cluster-rbac/**
    - base-apps/cluster-rbac.yaml
    - base-apps/admission-policies/**
    - base-apps/admission-policies.yaml
    - appsets/**
    - terraform/**
    - ansible/**
    - node-config/**           # host-level k3s config (e.g. apiserver authn, #625)
    - .github/**
    - "!**/*.md"             # docs inside those directories are not "read" on their own
  kinds:                     # kind: added/removed/modified anywhere in the diff
    - ClusterRole
    - ClusterRoleBinding
    - CustomResourceDefinition
    - ValidatingAdmissionPolicy
    - MutatingAdmissionPolicy
    - NetworkPolicy
    - AuthorizationPolicy
    - PersistentVolumeClaim
  signals: [application_deleted, k3s_version_change]
always_skip:                 # EVERY changed file must satisfy one entry
  paths: [docs/**, "**/*.md"]
  image_tag_bump_only: true  # only `image:`/`tag:` value lines changed, ≤ 4 lines. A Helm
                             # chart bump (Application `targetRevision`) never qualifies;
                             # it goes to Jev (e.g. kyverno 3.7→3.9 needed fix #585)
hot_components: {}           # component → follow-up rate; written by `pr_triage calibrate`
thresholds:
  read_if_p_read_gte: 0.30
  read_if_any_flag_gte: 0.70
  skip_if_p_skip_gte: 0.90
  escalate_if_confidence_lt: 0.50
risk_callouts:               # kind → plain-language risk, used by pr-explainer
  ClusterRole: access control
  ClusterRoleBinding: access control
  RoleBinding: access control
  NetworkPolicy: network exposure
  AuthorizationPolicy: network exposure
  HTTPRoute: network exposure
  Gateway: network exposure
  PersistentVolumeClaim: data durability
  Cluster: data durability          # CNPG
  PodDisruptionBudget: availability during drains
  CustomResourceDefinition: cluster-wide API change
  ValidatingAdmissionPolicy: cluster-wide admission
  MutatingAdmissionPolicy: cluster-wide admission
```

**Semantics**
- A *component* is `base-apps/<app>` for anything under `base-apps/<app>/` or `base-apps/<app>.yaml`. For any other path it is the first two path segments.
- `application_deleted`: a `base-apps/*.yaml` whose content is `kind: Application` was removed.
- `k3s_version_change`: a changed line matches `v\d+\.\d+\.\d+\+k3s\d+`.

## 4. Follow-up-fix heuristic (shared definition)

A merged PR **P** has a *follow-up fix* if some later merged PR **Q** meets all of these:
1. Q's title starts with `fix` or `revert` (case-insensitive).
2. Q merged within **72 h** after P.
3. P and Q share at least one component (§3).

When computing components for this purpose, ignore:
- paths under `docs/`
- basenames `index.md`, `README.md`, `CLAUDE.md`, `SPEC.md` and `agent-docs-scope.txt`

This is a **proxy**. It counts planned follow-ups, such as "step 1 of 2", as misses. Triage calibration accepts that noise. The retro filters it out (§7.4).

Two copies implement it: `pr_triage/followups.py` and `review-retro/scripts/followups.py`. They must stay behaviorally identical. The rule is defined here, not in the code.

## 5. pr-triage

### 5.1 Wiring
- **Workflow:** `kubernetes/.github/workflows/pr-triage.yaml`
  - Trigger: `pull_request` on `main`, types `[opened, synchronize, reopened, ready_for_review]`.
  - `permissions: {contents: read, pull-requests: write}`.
  - `concurrency: pr-triage-${{ github.event.pull_request.number }}` with cancel-in-progress.
  - It is not a required check.
- **Step:** `uses: arigsela/claude-agents/pr-triage@<sha>`, with inputs `pr-number`, `repo`, `policy-ref` (base SHA) and `mode` (`label`).
- **Secrets:** `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY`.
- **Skipped PRs:** fork PRs (their token is read-only, so the run could not label them anyway) and drafts until `ready_for_review`.
- **Composite action:** installs `uv`, then runs `uv run --project $GITHUB_ACTION_PATH python -m pr_triage run …`.
  - Package: `pr-triage/pyproject.toml`.
  - Dependencies: `anthropic`, `pyyaml`, `pathspec`.
  - Jev is called over plain HTTPS; see A2.

### 5.2 Features (deterministic)
All inputs come from `gh api repos/{repo}/pulls/{n}` and `…/pulls/{n}/files`, paginated. `features.py` produces:
- `size_bucket`: tiny, small, medium or large, using §1's cut-offs.
- `components` (§3) and `hot_components_touched`.
- `kinds_changed`: `kind:` values on added or removed lines. Files whose `kind:` line did not change but whose hunks changed are resolved by fetching the head version of the file and mapping hunk lines to documents.
- `application_changes`: for each `base-apps/*.yaml` Application, which of `chart`, `targetRevision`, `helm.values/valuesObject/parameters`, `path`, `destination`, `syncPolicy` and `ignoreDifferences` changed.
- `signals`: `application_deleted`, `k3s_version_change`, `image_tag_bump_only`.
- `diff_excerpt`: patches ordered with sensitive hunks first (policy hits, then hot components, then the rest), capped at **32,000 characters**. Secret material is redacted (§8).

### 5.3 Rules
- If any `always_read` item matches, the decision is `read`, `decided_by=rules`, and the reasons name each matching rule and file.
- Otherwise, if every file satisfies `always_skip`, the decision is `skip` with `decided_by=rules`.
- Otherwise go to §5.4.

### 5.4 Jev (one request, several questions)
- **Request:** `POST https://api.typesafe.ai/v1/systemone` with `model: jev-1.13.0`.
- **State:** `{title, body[:2000], size_bucket, components, hot_components_touched, kinds_changed, application_changes, signals, diff_excerpt}`. Numbers are sent as named buckets only, never raw counts, because Jev is weak at arithmetic.

**Questions**
- `attention` (choice):
  - `skip`: "Version bump, docs, or comments only; no change to what runs or who can reach it."
  - `skim`: "Changes behaviour of a single application in a way a git revert fully undoes (config values, resources, probes, replicas)."
  - `read`: "Changes access control, network exposure, data durability, cluster-wide admission or APIs, or something a git revert does not fully undo (deletions, migrations, storage, CRDs)."
- Yes/no questions:
  - `touches_access_control`: "Does this change who or what can access a resource (RBAC, auth, OIDC, service accounts, credentials wiring)?"
  - `changes_network_exposure`: "Does this change what traffic can reach a workload or leave it (routes, gateways, network or authorization policies, ports)?"
  - `risks_data_loss`: "Could applying this change delete or corrupt stored data (volumes, databases, backups, retention)?"
  - `hard_to_revert`: "Would reverting this commit fail to restore the previous state (deletions, migrations, immutable fields, CRD changes)?"
  - `cluster_wide_effect`: "Does this change affect workloads beyond the application it names (cluster-scoped resources, shared gateways, admission, node config)?"

### 5.5 Decision (code; thresholds from the policy)
```
if P(read) >= read_if_p_read_gte or max(flags) >= read_if_any_flag_gte:  read   (jev)
elif confidence(attention) < escalate_if_confidence_lt:                  claude_decide()
elif P(skip) >= skip_if_p_skip_gte:                                      skip   (jev)
else:                                                                    skim   (jev)
if decision == skip and hot_components_touched:                          skim
```

**`claude_decide()`**
- Model `claude-haiku-4-5` (action input `claude-model`), called through the Anthropic SDK with **structured outputs** (`output_config.format` json_schema) returning `{decision, reason}`. Forced `tool_choice` is not used, because it returns a 400 on Opus 5.5, Sonnet 5.5 and Fable 5.1, which would break the model input.
- Input is the same filtered state plus Jev's probabilities.
- If it errors, the decision is `read`.

**Note**
- For `skim` and `read` only, one Haiku call writes 2–4 bullets titled "What to look at".
- `skip` makes no Claude call.
- If the note call fails, the comment is posted without the note. The decision stands.

### 5.6 Output and failures
- **Labels:** exactly one of `review:skip` (`0e8a16`), `review:skim` (`fbca04`) or `review:read` (`d93f0b`). Missing labels are created and the other two are removed.
- **Sticky comment:** found by the marker `<!-- pr-triage -->`. It is edited if it exists and created otherwise.

  ```
  <!-- pr-triage -->
  ### 🔴 review:read
  **Why:** always_read.kinds ClusterRoleBinding (base-apps/dex/rbac.yaml); P(read)=0.62
  **What to look at:**
  - …
  **Next:** `/pr-explainer 650` · `/code-review 650`        (skim/read only)
  <details><summary>Signals</summary> decided_by, P(skip/skim/read), flags,
  size_bucket, components, hot components </details>
  <sub>pr-triage <action sha> · jev-1.13.0 · claude-haiku-4-5 · policy @ <base sha></sub>
  ```
- **Degraded mode:** used when Jev fails after 1 retry (5 s timeout) or when a secret is missing. The run keeps the rules-only decision, or sets `read` if the rules did not decide. The comment says `triage degraded: <reason>`. The job still exits 0.
- **Other errors:** a `gh` API error exits non-zero, so the check goes red and the label is left unchanged. That is visible, and nothing blocks on it.

### 5.7 Calibration CLI (not a test suite)
`uv run python -m pr_triage calibrate --repo arigsela/kubernetes --limit 200 [--compare haiku] [--out calibration.md]`

**Steps**
1. Fetch the last N merged PRs and their files and patches, then label each one with §4.
2. **Time split to avoid leakage.** The older half computes `hot_components`: components with rate ≥ 0.40 and ≥ 3 PRs. The newer half is the evaluation set.
3. Run rules → Jev → decision on every evaluation PR, against the policy at current `main` plus the fresh `hot_components`.
4. `--compare haiku` also runs a Claude-only backend on the same state, answering the same questions through structured outputs.

**Report**
- Follow-up PRs labeled `skip`: count and share. This is the key safety number.
- Share of all PRs labeled `skip`.
- Share of follow-up PRs labeled `read`.
- A table by size bucket and by `decided_by`.
- Jev tokens and cost.

**Suggested policy patch** for `thresholds` and `hot_components` (recomputed on all N). The owner applies it through a normal PR.

**When to re-run:** the Jev model version, question text, criteria and thresholds form one versioned unit (Jev research doc rule 10). Re-run calibration when any of them changes.

## 6. pr-explainer (skill)

### 6.1 Invocation and prerequisites
- **Command:** `/pr-explainer <number> [--repo owner/name]`. The default repo comes from `origin` in the cwd.
- **Where it runs:** in a Claude Code session inside a checkout of the target repo.
- **Required:** `gh`, `git`, `uv`.
- **Optional:** `helm`, for Helm-sourced Applications. Without it, those apps fall back to the source diff.
- **kustomize:** uses `kubectl kustomize`.

**Layout**
```
skills/pr-explainer/.claude-plugin/plugin.json
skills/pr-explainer/README.md
skills/pr-explainer/skills/pr-explainer/SKILL.md
skills/pr-explainer/skills/pr-explainer/scripts/{collect.py,render.py,verify.py,post_comment.py}
skills/pr-explainer/skills/pr-explainer/assets/template.html
```
Scripts run as `uv run --script` with inline dependencies (`pyyaml`).

### 6.2 Collect (deterministic → `facts.json`)
`collect.py` fetches the PR metadata, the diff and base/head SHAs (running `git fetch origin pull/<n>/head` if needed), and reads the policy and any `<!-- pr-triage -->` comment.

**Per-app handling**

| What changed | How it is expanded |
|---|---|
| Directory-sourced app (`spec.source.path`) | Manifests at base and head are loaded from `git show`, so the diff is already rendered. |
| Kustomize directory | `kubectl kustomize` runs at both refs. |
| Helm-sourced app with `chart`/`targetRevision`/`helm.*` changed | `helm template <app> <chart> --repo <repoURL> --version <rev> -f <values>` runs at both refs. Values come from inline `values`, `valuesObject` or `parameters`. |
| Application file itself | Changed spec fields are recorded as a resource of kind `Application`. |
| Terraform files | Resource actions are parsed from the newest Atlantis plan comment on the PR, if there is one. Otherwise the source diff is used with `render: source-diff`. |
| Anything else | Recorded as `non_manifest_changes` with its hunks. |

Resources are keyed by `(apiVersion kind, namespace, name)`. Comparing base and head gives `added`, `removed` or `modified`, with `changed_paths` limited to the 10 deepest differing paths.

**Edges** are derived from rules only; the model never adds one:

| Edge | Rule |
|---|---|
| `selects` | Service → workload, where the selector ⊆ pod template labels |
| `routes-to` | HTTPRoute, Ingress or VirtualService → Service, by backend name |
| `binds` | (Cluster)RoleBinding → Role/ClusterRole and → ServiceAccount subjects |
| `produces` | ExternalSecret → target Secret name |
| `mounts` | Workload → Secret, ConfigMap or PVC, via volumes and envFrom/valueFrom |
| `owns` | Application → each of its resources. This is drawn as subgraph membership, not as arrows. |

The graph includes every changed resource plus unchanged neighbours one hop away, which are drawn grey. The cap is 40 nodes; beyond that, nodes are collapsed per app.

**`facts.json` fields**
- `pr` and `triage`.
- `apps[]`: `{app, application_file, source_kind, render: rendered|source-diff|failed, render_note}`.
- `resources[]`: `{id, app, kind, name, namespace, action, changed_paths, file, lines, risk}`. `risk` is taken from `risk_callouts`.
- `edges[]`.
- `non_manifest_changes[]`.
- `terraform[]`: `{id, address, action, source}`.
- `policy_hits[]`: `{ref, rule, callout, more?}`. At most 5 hits per (app, rule); `more` counts the rest.
- `notes[]`: `{key, text}`, e.g. Terraform changed but no Atlantis plan was found. Each `key` must appear in `not_covered`.

### 6.3 Narrate (the session model → `explainer.json`)
The model reads `facts.json` plus diff excerpts for the referenced hunks, and writes **text only**, keyed by fact IDs:
```json
{"tldr": "...",
 "behavior_changes": [{"app": "...", "before": "...", "after": "...", "refs": ["r1"]}],
 "callouts": [{"severity": "high|medium|info", "text": "...", "refs": ["r3"]}],
 "must_read": [{"ref": "r3", "why": "..."}],
 "reading_order": ["r5", "r3", "r1", "f1"],
 "not_covered": ["..."]}
```
Reading order follows the dependency order CRDs → RBAC/identity → config/secrets → workloads → routing → everything else. The model may deviate only with a stated reason.

### 6.4 Verify (deterministic, `verify.py`)
The page fails verification if any of these hold:
- a `refs`, `must_read.ref` or `reading_order` entry is not an ID in `facts.json`
- a `policy_hits[].ref` is missing from `must_read`
- an app with `render != rendered` is missing from `not_covered`
- `tldr` is empty

**On failure:** the model gets the error list and fixes the JSON **once**. If it fails again, the page is published with a visible "Unverified" banner listing the problems.

### 6.5 Render and publish
**Render:** `render.py` fills `assets/template.html` and produces one self-contained page. The diagram is **not written by the model**; `render.py` generates it from `facts.json`.

**Page sections, in order**
1. Header: PR title, head SHA, triage label.
2. TL;DR.
3. Mermaid resource map: added resources green, modified amber, removed red, context grey.
4. Before → after table.
5. Risk callouts.
6. Must-read hunks, each linking to `https://github.com/<repo>/pull/<n>/files#diff-<sha256(path)>R<line>`.
7. Reading order.
8. Not covered.

**Page safety and conventions**
- Every text field is HTML-escaped.
- Mermaid is loaded from `cdn.jsdelivr.net/npm/mermaid@<pinned>` with `securityLevel: 'strict'`.
- Node labels are sanitized: no backticks, quotes or brackets.
- The template follows the Artifact page contract: a `<title>` "PR <n> explainer", color tokens on `:root` with dark mode, and a phone-width layout.

**Publish**
1. SKILL.md tells the model to load `artifact-design`, which the Artifact tool requires.
2. On first run it publishes with the Artifact tool, `icon: diagram`.
3. On a re-run it reads the URL from the existing `<!-- pr-explainer url=… -->` comment, runs Artifact `read`, then publishes with `url` so the same link updates.
4. If the Artifact tool is unavailable, it writes `pr-<n>.html` locally and `open`s it.

**Sticky PR comment:** `<!-- pr-explainer url=<artifact-url> sha=<head> -->` followed by `📖 Explainer for <short-sha>: <link> (private link)`.

## 7. review-retro (skill)

### 7.1 Invocation
- `/review-retro <number> [--repo owner/name]`, or
- `/review-retro --since <Nd> [--repo …]`, with N ≤ 30 because of transcript retention (A12).

**Layout:** the same plugin layout as §6.1, with `scripts/{find_sessions.py,extract.py,followups.py}`.

### 7.2 Find review sessions (`find_sessions.py`)
- It scans `~/.claude/projects/*/*.jsonl` with Python globbing, which avoids the problem of directory names that start with a dash.
- **A session is a candidate if** it has a user record containing `<command-name>/code-review</command-name>` whose `<command-args>` includes the PR number, or a `Skill` tool call to `code-review` whose args include it.
- **Repo match:** the record's `cwd` or `gitBranch` must match the repo, or the args must include `-R owner/repo`.
- **Output:** candidates with the path, session id, start time, cwd and first prompt.
- **Multiple reviews** of one PR are all analyzed.
- **No candidate:** the retro stops with "no /code-review session for PR N" and suggests running `/code-review` on `review:read` PRs.

### 7.3 Extract (deterministic → `retro-case.json`)
- **`pr`:** files and hunks, and `merged_at`.
- **Review output:** the final message in the "## Code review / Found N issues" format, and the PR comment if `--comment` was used.
- **Subagents:** from `<session>/subagents/agent-*.jsonl` and `.meta.json`, record type, description, tool call counts and **files seen**.
  - A file counts as seen if a `Read` touched it, if a `Grep` result contains it, or if a `gh pr diff` result containing it was returned in full.
  - If the tool result was cut off or spilled to `tool-results/`, the file is marked `partial`.
- **Coverage:** for each changed file, `seen`, `partial` or `unseen`.
- **Findings:** from the final output, plus subagent final messages for findings that scored below the threshold and were filtered (best effort). Each carries a transcript `path:line`.
- **Cost:**
  - The **authoritative** figures come from the session's last `cost-state` record: `totalCostUSD` and `modelUsage` per model, subagents included.
  - Per-agent tokens are summed from `message.usage` after deduplicating by `requestId`, and are labelled **approximate**.
  - Wall-clock time comes from the first and last timestamps.
  - The 10 largest tool results are listed.
- **Follow-ups:** from §4, each with its files and patches (truncated to 8,000 characters per file).
- **Human review comments** on the PR made after the review.

### 7.4 Analyze (the session model; every finding needs a citation)
Following `superpowers:diagnosing-superpowers`: **no `path:line` citation, no finding.** Transcript citations are `jsonl-path:line`. Fix citations are `PR#file:line`.

**For each follow-up PR**
1. **Relevance.** Classify it as one of:
   - `introduced-by-PR`: the fixed defect is in the reviewed diff.
   - `pre-existing`.
   - `planned-follow-up`: the reviewed PR's body or title announces it, e.g. "step 1 of 2".
   - `unrelated`.

   Only `introduced-by-PR` counts as a miss.
2. **Flagged?** Was it flagged as a kept finding, a filtered finding, or not at all?
3. **Cause**, for misses:

   | Code | Meaning |
   |---|---|
   | `C1 not-read` | The hunk was never seen, or only partly, by any agent. |
   | `C2 no-lens` | It was seen, but no agent's charter covered the concern. |
   | `C3 filtered` | It was flagged, then dropped by scoring or the threshold. |
   | `C4 missing-context` | It needed rendered manifests, cluster state or cross-file context the review never gathered. |
   | `C5 not-diff-detectable` | It only shows at runtime or in the environment. No reviewer change is proposed. |

**Also report**
- **Unconfirmed findings:** kept findings with no later change to that hunk. These are possible noise, not proven false positives.
- **Cost and process:** total cost, cost per kept finding, per-agent share, wall-clock time, largest tool results, and duplicated work between agents.
- **Recurring blind spots:** read earlier retro reports for the same repo and flag any cause or concern that repeats.

### 7.5 Proposals and output
**Proposals:** at most 5. Each one has:
- a target: `claude-agents/skills/code-review/skills/code-review/SKILL.md`, `kubernetes/.github/review-policy.yaml`, or the kubernetes `CLAUDE.md`
- a concrete diff snippet
- evidence refs
- an expected effect

**Nothing is applied without the owner's approval.** Approved edits go out as a branch plus PR in the target repo.

**Report**
- Saved to `~/.claude/review-retros/<owner>-<repo>/<YYYY-MM-DD>-pr<N>.md` or `-sweep.md`, with a summary in chat.
- **Sweep mode:**
  1. Lists merged PRs in the window.
  2. Keeps those with at least one review session.
  3. Retros each; with more than one, it uses one subagent per PR in parallel, each returning its section.
  4. Aggregates the causes and deduplicates proposals.
  5. Reviewed PRs with no follow-up appear as "clean", with cost only.
- **Missing transcripts or ground truth:** a report built only from transcripts that no longer exist says so explicitly. A PR with no follow-ups gets a cost-and-process-only retro, labelled "no ground truth".

## 8. Security and data handling
- **PR content is untrusted everywhere:**
  - In triage, the only effect is a label and comment text, and `always_read` overrides the model.
  - In the explainer, the model writes only text fields, which are escaped, and the diagram is deterministic.
  - In the retro, proposals are shown for approval and never auto-applied.
- **Secret redaction** before anything is sent to Jev, Anthropic or an Artifact:
  - drop the `data:`/`stringData:` blocks of `kind: Secret` documents
  - mask values on lines matching `(?i)(password|passwd|token|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*\S{8,}`
- **Visibility:**
  - Both repos are public, so the triage comment is public.
  - The explainer comment contains only a private Artifact link.
  - The retro posts nothing to GitHub.
- **Jev data retention:** there is no zero-data-retention on non-enterprise plans. That is acceptable because the repo content is already public.

## 9. Rollout
1. **Phase 1:**
   - Add the policy file to kubernetes.
   - Build `pr-triage` in claude-agents.
   - Run calibration and apply the suggested policy patch.
   - Add the secrets, then merge the workflow pinned to the action SHA.
2. **Phase 2:** the `pr-explainer` plugin, the marketplace/catalog entries, and a first run on a recent `base-apps` PR.
3. **Phase 3:** the `review-retro` plugin, and a first run once a `/code-review`d PR has a follow-up.

Each phase ships on its own.

## 10. Success criteria
- **Triage (calibration, evaluation half):**
  - At most 5% of follow-up-fix PRs labelled `skip`.
  - At least 20% of all PRs labelled `skip`.
  - Every `read` has a stated reason.
- **Triage (live, first 4 weeks):** the owner overrides the label on no more than 1 in 10 PRs. Overrides are visible as label events by the owner after the triage comment.
- **Explainer:** on a `base-apps` PR, the page lists every changed resource with zero unverified references. For a `skim` PR, the owner can decide without opening the diff.
- **Retro:** every `introduced-by-PR` miss gets a cause code with citations. Every sweep with at least one miss produces at least one concrete proposal.

## 11. Assumptions (made without per-section approval, at the owner's request)
- **A1 Layout:**
  - Plugin layout `skills/<name>/.claude-plugin/plugin.json` plus `skills/<name>/skills/<name>/SKILL.md`, matching `code-review`.
  - Entries in `.claude-plugin/marketplace.json` and `skills/skills-catalog.json`, and a row in `skills/README.md`.
  - No legacy top-level `SKILL.md` copy.
- **A2 Jev over HTTP, not the SDK.** The research doc flags the SDK's `probabilities`/`confidence` attribute names as unverified, while the HTTP response shape is documented. The model is pinned to `jev-1.13.0`. The owner creates the key.
- **A3 Claude model:** `claude-haiku-4-5` for triage fallback and notes, as approved in the triage section. It is the action input `claude-model`, so swapping in `claude-opus-5-5` (the Anthropic SDK default) or `claude-sonnet-5-5` is one line. It goes through the `anthropic` SDK with structured outputs and an `ANTHROPIC_API_KEY` repo secret. The skills use the session's own model.
- **A4 Thresholds:** starting values come from TypeSafe's default confidence bands and the asymmetric-cost rule. Calibration tunes them.
- **A5 Policy read from the base branch** by triage, and from the local checkout by the skills.
- **A6 Labels only.** Triage never blocks, approves or merges.
- **A7 The follow-up-fix heuristic is a proxy** (§4). The retro filters planned follow-ups; triage calibration accepts them as noise.
- **A8 The explainer runs locally,** in a kubernetes checkout.
  - Helm rendering needs `helm`, which is not installed today (`brew install helm`). Without it, Helm apps fall back to the source diff.
  - Terraform comes from Atlantis plan comments only; no local plan is run.
- **A9 Deterministic diagram.** The model writes only text keyed by fact IDs, so the diagram cannot contain made-up nodes.
- **A10 One Artifact per PR.** Its URL is stored in the sticky comment marker. A private link in a public comment is acceptable.
- **A11 The retro targets the `code-review` plugin source** in claude-agents. The copy installed at `~/.claude/skills/code-review` is older and differs; reinstalling is the owner's step. Other reviewers (gstack `/review`, the built-in Code Review) are out of scope for v1.
- **A12 Transcript retention.** Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default), so sweeps are capped at 30 days. The README recommends raising it to 90 in `~/.claude/settings.json`. The skill does not change settings itself.
- **A13 Token figures.** Per-agent token counts are approximate. Totals come from `cost-state`, which is authoritative.
- **A14 No test suites,** per the owner. Verification is by the manual runs listed in the plan, plus the calibration report, which is a measurement rather than a test.
- **A15 No Jev in the retro for v1.** The model matches findings to fixes, because the number of pairs is small. A Jev check per pair is future work.
- **A16 Repo conventions.** The explainer assumes the kubernetes repo's `base-apps` conventions: single-source Applications and inline Helm values. Other repos are unsupported in v1.
- **A17 Branching.** The spec and plan are committed on `docs/pr-review-toolkit` in a separate worktree, because the owner's `feat/homelab-agent` checkout has a staged `AGENTS.md`.

## 12. Future work
- A Jev yes/no check per pair in the retro, to match findings to fixes.
- Auto-run the explainer from the Action for `read` PRs.
- Use `argocd-diff-preview` in CI for exact rendering.
- After a few weeks of calibrated operation, let a bot approval count on `skip` PRs (branch protection currently needs an admin bypass).
- Add a GitOps specialist agent to `code-review`, which is the retro's likely first proposal.
