# docs-checker: morning handoff (2026-10-19)

You asked for the whole plan (`docs/superpowers/plans/2026-10-18-docs-checker-plan.md`) to be
built overnight. It is built and tested offline. Nothing was pushed, applied, deployed or run
against a paid API.

## Where things stand

- **The agent works offline.** `cd docs-checker && .venv/bin/pytest -q` gives 975 passed,
  0 skipped. Ruff and black are clean. The branch `feature/docs-checker` has 52 commits
  (`f4b7735..dafb17f`), plus this file's commits. The last four are the final review's fix
  round ("What the final fix round changed" below).
- **The image builds and completes a real A2A task.** The smoke test (`scripts/smoke.sh`) ends
  `smoke ok`, re-run after the final fix round. It ran in a throwaway colima profile, as
  linux/amd64 under emulation. The image is not pushed.
- **Evals are preregistered and dry-run only.** The plan is in `evals/plan.md`. The dry run
  estimates $18.70 of the $20 cap. No paid run happened, because
  `DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY` was not set. So there are no measured precision,
  recall or lever numbers yet.
- **Labels are done but provisional.** There are 943 rows over 11 instances. Two labellers
  wrote them, and Claude decided 105 rows (73 disagreements and 32 audited overrides). You have
  reviewed none of them, so the precision gate stays provisional until you do.
- **Drift demo (offline only).** θ1 is 37.44° and θ2 is 38.29°, so θ1 < θ2 by 0.85°. This
  demonstrates the method; it does not calibrate a gate. Production ships the rules gate,
  which refuses 10 of 10 bad fixes and 4 of 7 good ones (the 4 human PR rewrites); the
  digest-pinned version passes since F2.
- **kubernetes changes are ready but not pushed.** The branch `feat/docs-checker-k` has 11
  commits (K3, K2, K1, K4, K5/K6, and the final review's text fixes) and is rebased onto K0
  (PR #873, still open at `6861ada`).
  CI stays red until you pin the image digest. That is by design.
- **Your critical path:** land K0, then K3, then push the image, pin its digest, land the rest,
  and do the first live run. The eval pilot and the label review do not depend on the deploy.

The full ledger lives in this worktree at
`.superpowers/sdd/2026-10-18-docs-checker-plan/progress.md`. It is gitignored, so it exists
only locally. It has every task, review, ruling and deferred minor. This file repeats every
ruling so the ledger is not needed to decide.

## What was built

### docs-checker (`arigsela/claude-agents`, `docs-checker/`)

- **Runtime:** a kagent 1.0.0-alpha14 BYO runtime. It serves A2A over gRPC on :80 and
  `/readyz` on :8081, and uses the `kagent.runtime.v1` TaskStore. It refuses alpha11's config
  shape at startup.
- **Graph:** intake (the ref resolves to one commit) → scope → one subgraph per doc (load →
  extract → locate → judge → fix → gate) → collect → report.
  - Every node runs Haiku 5.5, except contested verdicts, which go to Sonnet 5.5.
  - The seven cost levers are switches (`levers.py`).
- **Guards:**
  - The run budget is reserved before each call: $1.00 for `all`, $0.10 per doc. Once what
    is left cannot pay a doc's first call, no further doc is started.
  - At most 12 model calls per doc (a judgement is reserved as 2 and charged as made: 1 when
    Haiku was sure, 2 when Sonnet decided), and one commit per run.
  - A soft deadline at three quarters of the 900 s turn limit (675 s): past it no doc or
    model call starts, and the run completes with what it checked (the rest
    `skipped-budget` with a time reason) instead of failing as `timeout` with nothing.
  - Docs are never evidence.
  - Everything a model or a log sees is redacted.
  - Tools: read-only `agent-docs`, with exactly `get_file_contents`, `search_code`,
    `list_commits` and `get_commit`.
- **Fix gate:** production runs rules only (`validate_replacement` plus a structural markdown
  render check).
  - It is strict. In the drift demo it refuses 10 of 10 bad fixes, and also 4 of 7 good ones:
    the 4 human PR rewrites. The digest-pinned version passes since ruling F2 landed.
  - A withheld fix still reports its finding (ruling F1).
- **Memory:** the weekly trigger sends a full JSON snapshot with each run and receives a full
  one back. Memory is honoured in `scheduled` mode only. The snapshot is capped at 960 KiB on
  both sides (C25b), under the trigger's ConfigMap budget. Pending docs go never-checked
  first, then the longest unchecked (I2), so a budget that runs out reaches every doc.
- **Evals:**
  - The harness records and replays cassettes, enforces a per-user $20 spend ledger, and
    scores the findings.
  - There are 11 instances: 7 dev and 4 holdout, including one canary.
  - Labels are under `evals/labels/`, the adjudication under `evals/labels-adjudication/`.
- **Image:**
  - Two stages: bookworm plus a uv-managed Python 3.13.
  - Runs as uid 65532 with entrypoint `/app/.venv/bin/docs-checker`. Both base images are
    pinned by digest.
  - 119 MB compressed. No key or `.env` is in the image (history and filesystem grep).

More detail: `README.md`, `evals/README.md`, `evals/plan.md`, `docs/drift-demo.md`.

### kubernetes (`~/git/kubernetes-docs-checker`, branch `feat/docs-checker-k`)

`git -C ~/git/kubernetes-docs-checker log --oneline 6861ada..HEAD`, oldest first:

| Commit | Task | Subject |
|---|---|---|
| `a843c46` | K3 | feat(ecr): docs-checker repository |
| `0bde23a` | K2 | feat(substrate): ECR pulls for sandboxes through atelet's credential provider (§T.129) |
| `9840686` | K2 | fix(substrate): IAM tag value, all-worker key retirement, seeded verify (§T.129) |
| `e1e2293` | K1 | feat(admission-policies): admit the docs-checker byo Harness under exact conditions (§T.130) |
| `c6bc431` | K1 | fix(admission-policies): soak switch, namespace-proof tests, named JSON error (§T.130) |
| `d2ec079` | K1 port | fix(admission-policies): read the alpha14 Agent template ref in the byo checks (§T.130) |
| `0efe3e6` | K4 | feat(kagent): docs-checker Harness, AgentTemplate and Agent on the byo runtime (§T.131) |
| `67cf827` | K4 | fix(kagent): docs-checker template-ref test and doc drift (§T.131) |
| `ea7bbe4` | K5/K6 | feat(kagent): docs-checker eval corpus and weekly trigger (§T.132) |
| `ec2f979` | K5/K6 | fix(kagent): docs-checker trigger delivers the report when memory can't be saved (§T.132) |
| `c3fa867` | review | docs(kagent): docs-checker deploy ordering and runbook fixes (§T.130-T.132) |

- **Base:** the branch is rebased onto K0, PR #873's head
  `6861ada892e7bd36639a5314e63fc8b93462b056`.
  - The pre-rebase branch is kept as `feat/docs-checker-k-pre-k0` (`c9c0640`).
  - The branch has no upstream.
  - K1's byo tests fail at `e1e2293` and `c6bc431` and pass from the port commit `d2ec079` on.
- **SPEC rows:** T129 (K2, V100), T130 (K1, V101), T131 (K4) and T132 (K5/K6, V102). T128 is
  K0's.
- **Tests on the branch:** everything passes except the placeholder gates, which fail on
  purpose until the digest is pinned:
  - agent-capability: 86 passed, 1 failed (`test_the_real_repo_passes`);
  - admission-policies: the session fails at setup, naming `REPLACE_WITH_DIGEST`.
  - docs_checker_trigger: 59 passed.
  - With a stand-in digest in a scratch copy at K4 (`0efe3e6`), every suite passed,
    admission-policies 197 included.
- **Not run on this machine:**
  - The admission suite ran on envtest's kube-apiserver 1.37.0, not on k3s.
  - The 8 Docker-backed ansible tests did not run, because the colima disk is full.
  - CI runs both.

## Your steps, in order

Steps 1 to 5 land the deploy. Steps 6 and 7 (evals and labels) can happen any time; do 7
before the holdout arm. Steps 8 and 9 need the deploy.

### 1. Land K0, then rebase the branch onto main

After PR #873 merges (its own clean-DB runbook):

```bash
cd ~/git/kubernetes-docs-checker
git fetch origin
git rebase --onto origin/main 6861ada892e7bd36639a5314e63fc8b93462b056 feat/docs-checker-k
for g in gen-okf gen-techdocs gen-agent-capability-policy gen-agent-audit-cronjob \
         gen-eval-gate-configmap gen-docs-checker-trigger-configmap; do
  python3 scripts/$g.py --repo-root . --check || python3 scripts/$g.py --repo-root .
done
python3 scripts/validate-agent-capability.py --repo-root .   # fails only on REPLACE_WITH_DIGEST until step 3
```

- The rebase command is the same whether K0 is merged, rebased or squashed.
- If #873 gains commits before it merges, still pass `6861ada` as the upstream argument.
- Expect conflicts only where main moved: SPEC rows and generated files.
- Commit anything the generators rewrote.

### 2. K3 first, then push the image

**K3 in its own PR (my suggestion).** The ECR repository must exist before the image can be
pushed. Landing K3 first means the main PR is pushed once, already pinned, as the repo's
"push once per PR" rule asks.

```bash
K3=$(git rev-list --reverse origin/main..feat/docs-checker-k | head -1)
git show --stat "$K3"                  # expect "feat(ecr): docs-checker repository", ecr.tf only
git branch feat/docs-checker-ecr "$K3"
git push -u origin feat/docs-checker-ecr
gh pr create --repo arigsela/kubernetes --base main --head feat/docs-checker-ecr --fill
# atlantis/plan: asela-cluster -> comment `atlantis apply` -> atlantis/apply green -> merge
git fetch origin && git rebase origin/main feat/docs-checker-k   # K3 drops out: already in main
```

**Push the image.**

- Build from the `feature/docs-checker` commit you mean to ship (the tip, after any late fixes).
- Use the `dcbuild` profile: the default colima VM's disk is full.

```bash
cd ~/git/claude-agents/.claude/worktrees/agent-aee2de46c29529766
export DOCKER_CONTEXT=colima-dcbuild
REG=852893458518.dkr.ecr.us-east-2.amazonaws.com
TAG=$(git rev-parse --short=12 HEAD)
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin "$REG"
docker build --platform linux/amd64 --provenance=false -t "$REG/docs-checker:$TAG" docs-checker
docker push "$REG/docs-checker:$TAG"
aws ecr describe-images --region us-east-2 --repository-name docs-checker \
  --image-ids imageTag="$TAG" --query 'imageDetails[0].imageDigest' --output text
# optional: the smoke test against exactly what you pushed
SMOKE_IMAGE="$REG/docs-checker@sha256:<digest hex>" bash docs-checker/scripts/smoke.sh
```

- Tags are immutable, and the lifecycle keeps the last 10 tagged images, so always push with a
  tag.
- `--provenance=false` leaves out the attestation manifest, so the digest you pin is the image
  itself.

### 3. Pin the digest

This is the admission-policies runbook's "Pin a byo image digest" procedure:

```bash
cd ~/git/kubernetes-docs-checker
D=<64 hex chars, without the sha256: prefix>
sed -i '' "s/docs-checker@sha256:REPLACE_WITH_DIGEST/docs-checker@sha256:$D/" \
  base-apps/admission-policies/agent-capability-taxonomy.yaml \
  tests/admission-policies/fixtures/agent-capability/good/good-byo-docs-checker.yaml \
  base-apps/kagent/harnesses/docs-checker.yaml \
  SPEC.md
python3 scripts/gen-agent-capability-policy.py --repo-root .
python3 scripts/gen-agent-audit-cronjob.py --repo-root .
python3 scripts/validate-agent-capability.py --repo-root .
python3 -m pytest tests/agent-capability/ -q
git commit -m "feat(kagent): pin the docs-checker image digest (§T.130, §T.131)" -- \
  base-apps/admission-policies/agent-capability-taxonomy.yaml \
  base-apps/admission-policies/agent-capability.yaml \
  base-apps/postgresql/agent-audit-cronjob.yaml \
  base-apps/kagent/harnesses/docs-checker.yaml \
  tests/admission-policies/fixtures/agent-capability/good/good-byo-docs-checker.yaml \
  SPEC.md
```

- `SPEC.md` row T131 carries `docs-checker@sha256:REPLACE_WITH_DIGEST` too (the sed above
  rewrites it), and rows T130–T132 say "PREPARED, ⊥ applied": that status flips when the PR
  merges, not here.
- `tests/admission-policies` needs a working Docker. The default VM is full, so let CI run it.

### 4. Open the main PR, apply, provision, merge

```bash
git push -u origin feat/docs-checker-k
gh pr create --repo arigsela/kubernetes --base main --head feat/docs-checker-k --fill
# atlantis/plan shows IAM user docs-checker-pull -> comment `atlantis apply` -> wait for green
scripts/provision-docs-checker-pull.sh --check
scripts/provision-docs-checker-pull.sh
```

- **Provisioning:** the script needs `VAULT_ADDR` with a token, the AWS CLI as an IAM admin,
  and `ansible-playbook`. Its verify step must pass on both workers.
- **Merge in a quiet window:** atelet restarts on both workers.
- **Bot commits:** the `okf-autosync` workflow may push a commit to the PR, so pull before you
  push again.
- **Acceptance:** after the merge, run K2's acceptance from
  `docs/superpowers/specs/2026-10-18-substrate-ecr-pulls.md`, "Acceptance":
  - an uncached digest on a fresh worker;
  - a pull after a key rotation;
  - the credential file unreadable from a sandbox.

### 5. Sync admission-policies before the Harness (first-pin ordering race)

On merge, `admission-policies` (the policy with the new digest) and `kagent-secrets` (the
Harness) auto-sync independently. If `kagent-secrets` goes first, the Harness create is denied.
Argo does not retry the same revision, because there is no `syncPolicy.retry`. So:

```bash
argocd app sync admission-policies && argocd app wait admission-policies --sync --health
argocd app sync kagent-secrets      # run it even if it already synced: a denied Harness is not retried
argocd app get kagent-secrets       # no sync errors; Harness, AgentTemplate and Agent docs-checker present
```

### 6. The eval key and the pilot

Follow `evals/README.md`, "Running the paid evals (Ari)". Steps 1 and 2 are the key and the
pilot:

- **The key:**
  - In the Anthropic Console, create a separate workspace (for example
    `docs-checker-evals`).
  - Set the workspace's spend limit to $25.
  - Create a key in it.
  - The key goes only in `DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY`, never in `ANTHROPIC_API_KEY`
    or a file.
- **The pilot:**

```bash
cd ~/git/claude-agents/.claude/worktrees/agent-aee2de46c29529766/docs-checker
read -rs DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY && export DOCS_CHECKER_EVAL_ANTHROPIC_API_KEY
.venv/bin/python -m docs_checker.evals spend   # expect: cap $20.00 ... headroom $20.0000, no open: line
.venv/bin/python -m docs_checker.evals run --instances lever --levers all --mode record-missing --arm pilot
.venv/bin/python -m docs_checker.evals spend
```

- **When to stop after the pilot:** stop and bring back the numbers if any of these holds:
  - the exit code is not 0;
  - a doc's status is not `checked`;
  - `spend` shows an `open:` line;
  - the pilot's cash is over $0.45.

  Otherwise continue with the README's steps 3 to 7.
- **Before the pilot's first priced call:** the preregistration freezes then. Change any of
  the choices listed under "Other calls" below before that, or not at all.
- **Cache lever:** the cache lever may be a no-op, because the system prompts may be below the
  minimum cacheable length. The pilot's cache-write tokens will show it.

### 7. Review the labels

The labels are in `docs-checker/evals/labels/eval-set.json`, with the adjudication in
`evals/labels-adjudication/` (`decisions.json`, `audit.json`). What each labeller wrote is in
`evals/labels-raw/{a,b}/`. Review them before the holdout arm (README step 5).

Review in this order:

1. **`h658-vault-runbook:40`.** Both labellers said `true`. An audit made it `stale` (ruling
   R1f): on a rebuilt cluster, the documented fix cannot run.
2. **The 8 positives only one labeller gave:**
   - `h656-donetick-docs:47`, `48` and `89`;
   - `h751-agent-audit-web-docs:71`;
   - `h751-kagent-runbook:241` and `242`;
   - `kagent-live:353` and `354`.
3. **`labels-adjudication/audit.json`, as one set.** It holds 32 overrides. Its 11 holdout
   true→uncertain rows (R1d) and the one true→stale row (R1f) all move precision the same way.
4. **`h751-suc-docs:51` and `h751-agent-audit-web-docs:71`, against the list rule (R1g).**

```bash
cd ~/git/claude-agents/.claude/worktrees/agent-aee2de46c29529766/docs-checker
jq -c '.[] | select(.label=="stale" or .label=="missing" or .adjudicated_by=="claude")
       | {instance,line,label,source,note}' evals/labels/eval-set.json
.venv/bin/python -m docs_checker.evals.curate packets --out /tmp/dc-packets   # numbered docs, overlays applied
# then edit eval-set.json: set reviewed_by_ari true, change label/note where you disagree
.venv/bin/python -m docs_checker.evals.curate validate
```

- **Recording the review:** no command marks rows reviewed; it is a hand edit.
- **Quoting holdout precision:** always quote it with the per-instance TP breakdown.
  - 5 of the 9 holdout positives come from `h751-suc-docs`.
  - The 9 positives are about 7 independent facts.

### 8. The first live run (after K0 and this branch are deployed)

```bash
~/git/kubernetes/scripts/ask-hk --agent kagent/docs-checker "check base-apps/kagent/docs.md"
```

- **Limits:** at most $0.10 and 15 minutes. Keep the `context:` id for follow-ups.
- **Expect:** a report on 1 doc. The Harness table row
  ``| `kagent-stateless` | none | none | k8s-reader |`` (with the backticks around
  `kagent-stateless`, as the file has it) should come back stale: implementer and restarter
  run on kagent-stateless too.
  That row is line 220 on the branch, and was line 198 at `c08a1b0` (label `kagent-live:198`).
- **If the session fails at start:** see the kagent runbook, "Symptom: `docs-checker` sessions
  fail at start".

### 9. The first manual trigger run

```bash
RUN=docs-checker-trigger-manual-$(date +%s)
kubectl -n kagent create job --from=cronjob/docs-checker-trigger "$RUN"
kubectl -n kagent logs -f "job/$RUN" | jq -cR 'fromjson? | select(.posted or .error)'
```

- **Acceptance:** the log has a line with `"posted":"report"`, and the digest appears in
  `#oncall-alerts` ("Investigation: Weekly docs check").
- **Cost:** one paid run, at most $1.00.
- **Expect `skipped-budget` docs on the first run.**
  - Memory starts empty, so every in-scope doc is checked: 56 on the branch, under the 80 cap.
  - The per-doc cost is unmeasured, so some docs may end `skipped-budget`. A doc the run never
    started says `not started: ...` (the budget could not pay its first call, or the 675 s
    soft deadline passed); a doc cut off mid-way says how many claims were judged.
  - Later weeks skip unchanged docs and take the never-checked docs first, then the longest
    unchecked, so the whole set is reached.
- **Failure modes:**
  - "completed without a report … Request refused": the gateway dropped the data part
    (T132 (a)).
  - A timeout: the 1200 s blocking send (T132 (b)).
  - In both cases memory is untouched, and the kagent runbook's "Weekly docs check" symptom
    applies.

## What the final fix round changed

The whole-branch review (`.superpowers/sdd/.../final-review-docs-checker.md`, local only)
found no critical issue and three Important ones about the first live runs. All three are
fixed, with the minors it marked "fix now". Each item has a test; 975 pass, 0 skipped.

| Commit | What |
|---|---|
| `51e311c` | I1: a judgement is reserved as 2 calls and charged as made (1 or 2), so a doc with more than five Haiku-judged claims fits the cap of 12 (the pilot stop rule "a doc is not `checked`" no longer trips on that). I2: pending docs go never-checked first, then by the memory's `run` of their last check. I3: a soft deadline at 0.75 × `run_timeout_s`; past it, and once the budget cannot pay a doc's first call, no doc or model call starts, docs not started are `skipped-budget` with a `not started: ...` reason, and the run still delivers its report and memory. `finish` fingerprints only `checked` docs. |
| `62cbb75` | F2: rule 8 also reads the evidence with image digests stripped, so a tag before `@sha256:...` is a whole token (G1 untouched, pinned). `_BLOCK_PREFIX`: an ordered-list marker needs a following space, tab or line end, so a line that starts with a version may change. `evidence._token`: `example.com` is not a hit in `mail.example.com`; tests for quoted values, `8080` vs `18080`, `@sha256`. The drift page is regenerated (no embedding needed; the Rules column comes from `gate.build_fix_gate`; θ1, θ2 and the margin in `.2f`; one sentence on what rules and angle do together: the rules refuse all 10 bad fixes, the angle refuses none more; of 7 good fixes the rules refuse 4, the angle asks about 1 and 2 pass). |
| `243a8b3` | C25b: `memory.MAX_INPUT_BYTES` = 960 KiB on both sides. M1: map sources are fingerprinted. M2: one spelling per source path on both sides of a dir listing (`./x/`, `/x/`). README Memory. |
| `dafb17f` | M4: an error attempt with an HTTP status settles to $0 (only connection and timeout errors keep their reservation). M10: at most 200 tool-event part pairs per artifact plus a `docs-checker/tool-events` count. T10: an "audit" of nothing is off-topic. T2: `anthropic` declared, `protovalidate` in the dev extra (`uv lock`). T5, T8, T11, T16, T20, M9. README: the recursion default (80), the soft deadline and the cap, and M3: a `missing` finding carries a hint, not a proposed fix, in v1. |

Not changed: the model request bodies (the smoke cassettes replay as before), the prompts,
`CHECKER_VERSION`, the eval plan (the dry run still estimates $0.15 for the pilot and
$18.70 in all).

## Known stale lines left for docs-checker's first live run

The eval set pins its commits, so fixing these on main changes no label.

| Line | What is stale | Can docs-checker see it? |
|---|---|---|
| `index.md:39` | "Seven agents" (10 with docs-checker) | No. Its front matter has no `sources:`, and the repo root is not a discovery root. Fix it by hand. |
| `base-apps/ollama/docs.md:45` | "six of the seven agents … all but `k8s-reader`": nine Agents exist, and implementer and restarter also run on kagent-stateless | Yes: `check base-apps/ollama/docs.md` |
| `docs/adp-engineering-deep-dive.md:201` | an Agent names its AgentTemplate with `templateRef`; alpha12+ uses `spec.template.ref` | No. The file has no front matter. Fix it by hand. |

## Overnight calls to confirm or reverse

### The plan's R1–R5

| Call | What was done | If you reverse it |
|---|---|---|
| R1, PoC scope | A curated set of 11 instances (5 history, 1 live, 4 planted, 1 canary); 4 are the frozen holdout. Labels are JSON. There is no review UI and no corpus builder. Two labellers plus Claude's adjudication; the gate is provisional until your review. | Re-label, or grow the set, before the paid evals. The harness takes any `labels/*.json`. |
| R2, drift angle | The angle layer is an offline demo only (`docs/drift-demo.md`). The deployed gate is rules-only. | Deploying the angle layer needs real calibration: the margin is 0.85° over 3 good and 5 bad dev fixes. |
| R3, paid evals | Preregistered with `/eval-plan` and dry-run ($18.70 of $20). Paid runs wait for the key. | Nothing to undo. The pilot is step 6. |
| R4, kubernetes | Prepared on a local branch with tests passing. Nothing pushed or applied; no live run. | Nothing to undo. You push (steps 1–5). |
| R5, in-run repeats | A single-flight judgement memo (`graph.DecisionMemo`, identity-free versioned keys), not LangGraph `CachePolicy`. | `CachePolicy` does not reach `Send` children, runs concurrent cold misses twice, and would carry another claim's id. |

### Every ledger ruling, by task

Each row is one ruling as the ledger records it. The cost column is what you pay if the
ruling is wrong.

**Preflight**

| Id | Decision | Cost if wrong |
|---|---|---|
| P1 | `NODE_TOOLS` gains an `intake` scope (`get_commit`, `list_commits`) so `resolve_commit` can run at intake. | One extra allowed node scope (read-only tools). |
| P2 | `ToolEvent` moves from the deleted Q&A `state.py` into `tools.py`; Task 8's new `state.py` imports it. | A later move. |
| P3 | Task 1 keeps a minimal `prompts.py` (`system_message`, `AGENT_DESCRIPTION`); Task 10 extends it. | None. |
| P4 | `RepoReader` methods take `node=` (defaults: read/list_dir → load, latest_commit → scope, search → locate); one reader in `RunDeps`. | Small API churn. |
| P5 | Task 14 adds `langgraph-checkpoint-sqlite==3.1.2` (+ aiosqlite) and re-locks. | None. |
| P6 | The controller runs Task 18 through `/eval-plan`; without the key it stops after the dry run and writes your commands. | The lever numbers wait for you. |
| P7 | The smoke test uses hand-built synthetic cassettes (`tests/fixtures/cassettes-smoke/`), no paid key. | It proves the runtime path, not model quality. |
| P8 | Task 5 updates every `ToolBelt.call` caller to the `(ToolResult, ToolEvent)` return. | None. |
| P9 | Tasks 21–25 ran as a parallel track in a separate kubernetes worktree (no upstream, nothing pushed). | K-track rework if the agent's I/O contract had changed after the K-track was written. |

**Task 1: rename and plumbing**

| Id | Decision | Cost if wrong |
|---|---|---|
| J | Judge (stop-hook) findings on plumbing go into Task 1's fix round; the controller does not edit code. | One extra fix round. |
| J4 | `Claim.semantic_key` includes the evidence hash, so identical claims about different manifests never share a cached verdict. | Fewer cache hits (smaller lever-3 savings). |
| J5 | The `kagent` extra stays; `dev` includes it. | None. |

**Task 2: alpha14 contract**

| Id | Decision | Cost if wrong |
|---|---|---|
| A1 | alpha14 snapshots keep only `/data`, so the checkpoint db, the paused ledger and the replay memo live under `DOCS_CHECKER_DATA_DIR` (`/data/docs-checker`). | A resume re-pays earlier calls, and its ledger is a lower bound. |
| A2 | The smoke test passes the controller URL as `runtime.control_plane_url` in `KAGENT_CONFIG_JSON` (alpha14 has no `KAGENT_API_URL`). | None. |

**Task 3: budgets**

| Id | Decision | Cost if wrong |
|---|---|---|
| B1 | A reservation is a strict upper bound. Input is priced at ceil(chars/2.5) tokens times the highest input or cache-write rate of the model's top tier, and output at the top tier's rate. `overhead_chars` covers tool and schema JSON. A warning fires when an actual cost exceeds its reservation. | Tight budgets refuse some calls earlier (settlement releases the excess). |

**Task 5: tool results**

| Id | Decision | Cost if wrong |
|---|---|---|
| S1 | GitHub code search does not index `arigsela/kubernetes`, so 0 items plus `incomplete_results` reads as unknown. The evidence fallback widens to the doc's app directory plus `base-apps/<app>.yaml`. | Evidence outside the app directory (e.g. `renovate.json5`) is not found; those claims become unsupported (lower recall). |
| S2 | No tools are bound to the intake model; the per-run search cap lives on the per-execute belt. | None. |

**Task 6: repo reader**

| Id | Decision | Cost if wrong |
|---|---|---|
| O1 | Local-fake overlays can add files and delete them (`None` means deleted). | None. |

**Task 7: scope**

| Id | Decision | Cost if wrong |
|---|---|---|
| D1 | A file that will not read stays in scope, and the load stage marks that doc failed. A failing directory listing raises after the other roots are tried, and all roots absent raises. | A flaky listing still aborts the run (visible, and retried next week). |

**Task 8: typed handoffs**

| Id | Decision | Cost if wrong |
|---|---|---|
| R8 | `parse_request` dedupes scope paths and caps them at `max_docs` (80). | None. |

**Task 10: prompts and replacement containment**

| Id | Decision | Cost if wrong |
|---|---|---|
| N1 | Node functions take a `NodeContext` Protocol; `RunDeps` satisfies it. | A small rename. |
| U1 | A replacement may keep a URL or markdown link only if it is verbatim in the old text, and may never add one. | An attacker can keep a link, not add one. |
| U2 | With `tools_on_demand` on, intake binds no tools; with it off, all four schemas are bound with `tool_choice` none (the anti-pattern row). | None. |
| U3 | The per-doc call cap reserves `judge_claim` as 2 calls (Haiku plus escalation) and, since I1, charges what it took (1 or 2). | None recorded. |
| C10 | Containment minors are folded into the fix round: near-variant fence closers are neutralised, and @mentions, `<!-- -->`, entities and backslash escapes are rejected unless already in the old text. | A larger fix round. |
| G0 | The replacement keeps old's markdown skeleton (the ordered runs of `[`, `]`, `(`, `)`, `<`, `>`, `\`, backtick and `!`) and each line's leading whitespace. | A fix that must change markup is withheld (finding still reported). |
| G1 | For image, host, namespace and name claims, a new letters-only token must appear in the comment-free evidence. | Some prose-word fixes on those kinds are rejected. |
| G2 | (a) Each line's blankness and block prefix must equal old's. (b) Task 11 adds a whole-document CommonMark render check (markdown-it-py) that refuses any new href. | One new dependency; some fixes near unusual markup are refused. |
| G3 | A per-line block-kind extension (`_` in the prefix, blank rest, leading `<` or `[`); the six probe10g cases become mandatory render-check tests. | More refused fixes near unusual markup. |
| G4 (breaker) | Per-line rules cannot see neighbour-dependent CommonMark semantics, so the whole-document render check is the authority. It renders with markdown-it-py plus linkify and refuses any new URL in href, src or srcset. All 12 probe cases are mandatory tests. | A new link or image slips through only if the render check itself is wrong; adds markdown-it-py and linkify-it-py. |

**Task 11: fix gate**

| Id | Decision | Cost if wrong |
|---|---|---|
| F1 | A containment refusal keeps the finding, with no replacement text, marked "fix withheld: <reason>". A wrong-target refusal drops the finding. Both count as refused. | An injected doc can still get its stale line reported (with no attacker text). |
| G5 | The render check is structural: the patched and original token streams must match in everything except text and code content, raw HTML must be byte-identical, and the check fails closed. | Any fix that needs a structural change is withheld (finding still reported). |

**Task 12: memory**

| Id | Decision | Cost if wrong |
|---|---|---|
| M1 | `snapshot()` hard-caps at `MAX_INPUT_BYTES` by dropping whole doc entries, largest first. `from_snapshot` needs `mode=`. The README says carried findings are marked. | Very large memories lose some doc entries (extra re-checks). |

**Task 14: the audit graph**

| Id | Decision | Cost if wrong |
|---|---|---|
| S3 | `search_enabled` is off by default (`DOCS_CHECKER_SEARCH`), so the graph never calls `search_code`. A claim with no evidence after widening is `unsupported`, and its doc is not marked incomplete. | Claims whose evidence is outside the app directory stay unsupported and are not retried. |
| K1 | `windows_for` also counts a non-comment line holding a claim's key as a hit (ranked after key-plus-value and value lines), so a changed value is still found. | More windows per claim (still at most 5); slightly more judge tokens. |
| L1 | A failed model call marks that doc `failed` with partial findings, and the run continues. A failed memo owner does not poison other docs, and a failed transcript report falls back to the typed report. | A systematic model failure yields a report of failed docs instead of a failed task (visible either way). |

**Task 15: A2A input and output**

| Id | Decision | Cost if wrong |
|---|---|---|
| (folded) | A corrupt paused row falls back to the lost-pause path; production uses an allow-all tool gate that records nothing; a durable-row cancel test was added. | None recorded. |

**Task 16: eval harness**

| Id | Decision | Cost if wrong |
|---|---|---|
| E1 | The cassette key hashes path and query, not the full URL (the harness pins `api.anthropic.com`). | Cassettes recorded against another base URL would replay (none exist). |
| E2 | The spend ledger and its lock live per user at `~/.cache/docs-checker/spend.json`, whatever the checkout or `--evals-dir`. The workspace's $25 limit is the hard backstop. | A stale per-user ledger needs a manual `spend --settle`. |

**Task 17: curated eval set**

| Id | Decision | Cost if wrong |
|---|---|---|
| R1a | Labelling ran in phases: packets, then two independent labellers (two shards each), a merge, an adjudicator subagent (`adjudicated_by: "claude"`), and finally validate and commit. | Adjudication by a fresh subagent instead of the controller's own reading (you review every positive and disagreement anyway). |
| R1b | The lever subset is the planted-version small doc, the deleted-source plant, and `kagent/runbook.md` at #751's parent, not the 477-line live doc. | The "larger doc" lever rows understate savings on the biggest doc. |
| R1c | `kagent-live` moves to dev. The holdout is `h658-vault-runbook`, `planted-wkb-namespace`, `h751-suc-docs` and `h751-agent-audit-web-docs` (4 of 11). | The live kagent positive is a dev result, not in the frozen holdout. |
| C17 | M1–M9 are folded into the fix round (labels.py split, canary `fails_if` predicates, README notes, drift-detector test). No packet, id, plant or overlay changed while labellers worked. | A larger fix round. |
| C17b | Task 17's fix round ran alongside Task 20 in the same worktree (disjoint files; each task staged only its own files). | A commit race, or a red suite caused by the other task. |
| R1d | A comment in a non-doc file is not evidence on its own; a label resting only on a comment becomes `uncertain`. | Lines the repo's comments settle score `uncertain` (excluded) instead of decisive. |
| C17c | Folded: N2–N4, an `adjudicate --overrides` path for audited changes to agreed rows, and README notes (overlap, holdout memory rule, no instance facts in prompts, R1d, multi-fact rule). | A slightly larger round. |
| (overlap verdict) | Holdout `h751-agent-audit-web-docs:63` and dev `kagent-live:393` share evidence (`deployment.yaml:34`), but the dev line is `true`; accepted, with a README note. | None recorded. |
| C17d | Folded N-A..N-D: `from: null` overrides, the note keeps "was <from>", blank-line disagreements can only be dropped, and rows past EOF are droppable. | None. |
| R1e | Docstrings and string literals count as evidence, because the agent strips only comments. | `suc:71, 76, 82, 86, 89` and `h656:33` would be `uncertain` instead of decided. |
| R1f | Audit row 32 applied: `h658-vault-runbook:40` goes from true to stale although both labellers said true. It is flagged first for your review. | One holdout positive rests on a two-hop inference. |
| R1g | A list that presents itself as the full inventory and omits an item is `stale`, otherwise `uncertain`. This keeps `suc:51` and `aaw:71` stale. | Two holdout positives rest on a completeness reading. |

**Task 18: preregistration and dry run**

| Id | Decision | Cost if wrong |
|---|---|---|
| E3 | gstack `eval-plan` does the preregistration (`evals/plan.md`), but the spend table comes from the harness's own `--dry-run` (gstack's price table has no `claude-haiku-5-5` and prices single prompts). | gstack's dry-run checklist (output budget, retry prompt) isn't run; the harness's checks cover budget and retry. |
| E4 | Arms run in priority order: pilot, baseline, quality dev, holdout, single levers, then leave-one-out. `retry_limits` uses an injected 529 replay ($0). An arm over $4 stops before the next. | If the estimates are low, the lever-alone rows are the ones cut. |
| E5 | Accepted that the implementer read the holdout's label rows (counts) to write the per-instance TP breakdown; this is disclosed in the plan. | The "never read held-out sets" boundary is bent for a label count. |

**Task 19: drift demo**

| Id | Decision | Cost if wrong |
|---|---|---|
| F2 | The rules gate falsely refused digest-pinned versions (`0.35.1` inside `ollama/ollama:0.35.1@sha256:…`). Landed in the final fix round: rule 8 also reads the evidence with each digest replaced by a space (accept-only; G1 untouched and pinned by a test). | A tag next to a digest is accepted as a whole token; nothing else widened. |

**Task 20: image and smoke**

| Id | Decision | Cost if wrong |
|---|---|---|
| D2 | The image was built in a throwaway colima profile `dcbuild` instead of pruning your full default VM; the default context was switched back at once. | About 40 GB of host disk and a VM until you delete it. |
| P7a | `DOCS_CHECKER_REPLAY_DIR` is a replay-only seam in the shipped image: it never records, never reaches the network, is logged at startup and is off by default. | A test seam in the image; misuse only yields canned answers. |
| J6 | After a judge REWORK, `smoke.sh` asserts the non-root uid, the entrypoint, the interpreter import, `/readyz` 200 and a COMPLETED task, and `tests/test_dockerfile.py` pins the Dockerfile. | None. |
| J7 | Judge rounds on the shared worktree were routed to each task's owner, with separate commits per task. | None. |
| C20 | Minors 1–5 fixed at once: the duplicate initial Task enqueue ("Task already exists"), the PID-1 uid check passing on empty, an `--internal` network, the seam's inner transport test, and the sha1 object format. The smoke was re-run green. | A short extra round. |

**Task 22 (K2): ECR pulls for Substrate**

| Id | Decision | Cost if wrong |
|---|---|---|
| C22 | Cheap security and acceptance minors folded in: a realistic verify with a seeded env, blanked `AWS_WEB_IDENTITY_TOKEN_FILE` and similar, acceptance probes, accurate isolation wording, stderr separation. | A larger fix round. |

**Task 23 (K1): admission**

| Id | Decision | Cost if wrong |
|---|---|---|
| K1a | The writer policy is cluster-wide. Metadata-only and no-op UPDATEs are allowed for anyone. byo Agents and read-only servers are confined to `kagent`, with per-namespace ref resolution. | A cluster-wide deny surprises a non-kagent writer (the inventory found none). |
| K1b | Deny from the start, not shadow-first. To soak instead: `validationActions: [Warn, Audit]` plus `failurePolicy: Ignore` (admission-policies runbook, "To soak it instead of enforcing"). | An unknown writer of Agent, AgentTemplate, Harness or RemoteMCPServer is denied after merge (visible as Argo sync errors). |
| C23 | Folded M2, M3 and M6. M1, M4, M5 and the unconstrained byo command/args/env are recorded as T130 follow-ups instead of widening a deny-from-start policy tonight. | Those residual routes stay open until you pick them up. |

**Task 24 (K4): Harness, AgentTemplate, Agent**

| Id | Decision | Cost if wrong |
|---|---|---|
| K4a | Rebased onto K0's head `6861ada` (backup `feat/docs-checker-k-pre-k0`), and K1's byo checks ported to the alpha14 Agent shape in a separate commit. | If K0 changes before it merges, re-run the rebase onto its new head. |
| K4b | Both review minors fixed now. The three pre-existing stale lines are left for docs-checker's first live run. | Three known-stale lines stay unfixed on the branch. |

**Task 25 (K5/K6): eval corpus and weekly trigger**

| Id | Decision | Cost if wrong |
|---|---|---|
| C25 | Fixed the 422 Important: a budget check, plus a claim-only fallback that still delivers the report. Folded Minors 2, 4 and 5; recorded 1, 3, 6 and 7 as T132 follow-ups. | The recorded minors stay open. |
| C25b | docs-checker's snapshot hard cap is 960 KiB on both sides, below the trigger's ConfigMap budget. Landed in the final fix round. | Memory is trimmed slightly earlier. |

**Final fix round (after the whole-branch review)**

| Id | Decision | Cost if wrong |
|---|---|---|
| FD | One final fix dispatch for the review's three Important findings (I1 the call-cap charging, I2 the pending-doc order, I3 the soft deadline and the budget floor), the pre-ruled items (F2 and the drift regeneration, C25b, the README default, `_BLOCK_PREFIX`), the minors M1–M4, M9, M10 and the triage's fix-now items; M3 as a README deviation note; M6–M8 as HANDOFF edits; M11 dropped; M12 for you alone. | A large last round, re-reviewed before finishing. |

### Other calls worth a look (not ledger rulings)

- **Break-glass group:** `homelab:kagent-break-glass` is the implementer's name; T130 asks you
  to confirm it.
- **K2 config form:** K2 uses `atelet.imageCredentialProviderConfigYAML`, an inline ConfigMap
  reviewed in git, not the plan's `atelet.imageCredentialProviderConfig` (a host path). The
  chart recommends this form when the provider's env differs from the kubelet's.
- **Eval preregistration choices** (they freeze at the pilot's first priced call):
  - the tier-5 order;
  - `--overloaded 2` plus a `none --overloaded 2` comparison row;
  - pilot gate: cash ≤ $0.45;
  - baseline projection: S + 8P + 9B;
  - `short_circuit` cold and warm count as one arm for the $4 rule.
- **Drift θ:** θ comes from dev rows only, and the holdout is only scored.
- **Model config:** the AgentTemplate binds the Sonnet ModelConfig, while most calls use
  Haiku. This relies on the key being injected per origin (see Unverified until live).
- **Two-PR landing:** landing K3 first, in step 2, is my suggestion.

## Open follow-ups

**Done in the final fix round** (the four `fix(docs-checker)` commits after `e76e451` on
this branch, and `c3fa867` on the kubernetes branch; the section "What the final fix round
changed" below has the detail):

- F2: the digest-pinned version false refusal.
- C25b, T132 (f): the snapshot hard cap is 960 KiB on both sides.
- The README's `DOCS_CHECKER_RECURSION_LIMIT` default (80).
- The kagent runbook bump step adds a NEW `byo-images` entry (no in-place swap), and the
  admission runbook's pin step syncs `admission-policies` before `kagent-secrets`.
- The trigger runbook's "memory not saved" alert points at the cap in claude-agents.

**Still open on the kubernetes branch:** the trigger's fallback does not check that its own
alert posted (T132 (c) territory).

**T130 (K1), recorded only:**

- M1: Service, Deployment and ConfigMap `agent-docs-mcp` in `kagent` are writable without
  break glass. Repointing the Service is the RemoteMCPServer-URL threat by another route.
- M4: ModelConfig (its `baseUrl` decides where the injected key goes), ModelProviderConfig and
  SandboxTemplate are not covered by the writer policy.
- M5: the `crossplane` SA holds `*` on serviceaccounts, so it can impersonate Argo's SA.
  kagent-tools has approval-gated CRUD on `argoproj.io`, pods in `argo-cd` and
  `admissionregistration`.
- byo Harness `workload.command`, `args` and `env` are not constrained by CI; this relies on PR
  review.
- A stale `velero/velero-server` cluster-admin binding exists, and its namespace is gone.
- K1's docs now cite the policy's two `# enforcing` markers instead of line numbers
  (`c3fa867`).

**T132 (K5/K6), recorded only:**

- (a) A data part through the alpha14 JSON-RPC gateway is unproven; the first run proves it.
- (b) The 1200 s blocking send is unproven. The fallback is a non-blocking send plus
  `wait_task`.
- (c) A failed post after the claim loses that week's report, and no Grafana rule alerts on a
  failed Job. Option: store the digest in the claim.
- (d) `send_request` duplicates kagent_a2a's resend loop and uses its private
  `_send_not_accepted`. Add `parts=` to kagent_a2a next time it changes.
- (e) A paused task in scheduled mode is alerted but not rejected, so its session stays paused.
- (f) The snapshot cap: done (C25b, 960 KiB on both sides).

**Deferred minors that matter:**

- Abandoned paused threads persist in the checkpoint db after the 64-entry row eviction. Add
  an age-based sweep at startup or periodically.
- Run-level tool calls (`resolve_commit`, discovery, dismissals, fingerprint) are not
  published as `function_call` parts.
- The K2 pull key has no rotation cadence and no key-age alert.
  - Optional: `aws:SourceIp` on the home WAN IP.
  - `--retire-old` re-reads Vault inside `place` (a narrow race).
  - `AWS_CONFIG_FILE=""` should be `/dev/null`.
- Files over the plan's intent: `evals/drift.py` 751 lines, `tests/smoke_stack.py` 651,
  `evals/harness.py` 587, `evals/curate.py` 564 (`labels.py` is already split out).
- `CHECKER_VERSION` does not cover the answer schemas or the token and fence rules, so a schema
  change can reuse stale cached decisions from memory.
- The `cache_prefix` lever may be a no-op: the system prompts are about 324–564 tokens,
  against a minimum cacheable prefix of about 512.
- `scope_args` does not reject `..` in sha or ref. Server-side checks stop it today.
- A hostile 256 KiB doc costs about 5–8 s of CPU in the render check, in a thread that cannot
  be cancelled.

## Unverified until live

- A data part through the alpha14 JSON-RPC gateway (T132 (a)).
- The 1200 s blocking send (T132 (b)).
- The first `all` run's wall time against the 900 s turn limit and the new 675 s soft
  deadline. The offline estimate for 56 docs is roughly 8–12 minutes (about 400 model calls
  over 4 lanes, 500–800 reads, a `list_commits` per source of every checked doc), so the
  first run may end with docs `not started: the run's time limit was reached`; they are
  taken first next week. If that repeats, raise `DOCS_CHECKER_RUN_TIMEOUT_S` on the Harness
  towards the trigger's 1200 s send and keep the trigger's "stops itself at 15 min" comment
  in step with it.
- The completed artifact's size for 56 docs against the controller TaskStore's gRPC message
  limit: the report twice (text and `docs-checker/report`), the findings, the full memory
  snapshot (up to 960 KiB) and at most 200 tool-event part pairs plus their count.
- The shared `agent-docs` PAT's GitHub API budget for one `all` run: the same 500–800 reads
  plus the `list_commits` calls, memoised per task, against the token's hourly limit.
- uid 65532 binding port 80 under gVisor. kagent's own runtime does the same.
- `/data` ownership: whether 65532 can write it under the DurableDir mount.
- Per-origin key injection for the Haiku calls, since the template binds the Sonnet
  ModelConfig.
- The controller reconciling a byo AgentTemplate with no `systemPrompt`.
- Argo not reverting the memory ConfigMap.
  - This is reasoned from SSA with no `data` in git, not observed.
  - Fallback: `ignoreDifferences` on `/data` plus `RespectIgnoreDifferences`, which the
    kagent-secrets comment warns against.
- Also:
  - a native amd64 start (the smoke ran under qemu);
  - the admission suite on real k3s (CI's first run is the proof);
  - K2's acceptance;
  - the 8 Docker-backed ansible tests (CI).

## This machine

- **The `dcbuild` colima profile** (40 GB disk, docker context `colima-dcbuild`) is still
  running. It holds `docs-checker:dev` (rebuilt by the final round's smoke run) and the smoke
  sidecar image. Use it for the step 2 push, then delete it with `colima delete -p dcbuild`.
  The current docker context is `colima`.
- **The default colima VM's docker disk is 100% full** (98G of 98G on `/var/lib/docker`).
  `docker system df` shows about 62 GB of images and 8 GB of build cache reclaimable. Nothing
  was pruned. That is why the CI-only Docker tests (admission suite on k3s, ansible) were not
  run locally.
