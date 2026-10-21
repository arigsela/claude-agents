# Explainer plugin (pr, service, ticket) — Design

**Date:** 2026-10-15
**Status:** Draft for the owner's review. Decisions in §2 were taken in conversation; everything else is proposed.
**Builds on:** `2026-09-30-pr-review-toolkit-design.md` §6 (pr-explainer) and PR #82 (background, scenario, walkthrough, quiz, comments).
**Repos:** `arigsela/claude-agents` (plugin), the company GitOps and IaC repos it runs against.

## 1. Problem

`/pr-explainer` explains a change. Two other moments need the same kind of page and have none:

- **Discovery for a one-pager.** The owner is handed a service and has to describe its current state before proposing anything. Today that means reading Argo Applications, rendered manifests, Terraform and workflows by hand across environments.
- **Working a ticket.** An IFS or DX ticket asks for a change to a system the owner may not have opened in months. The ticket card in pr-explainer only appears once a PR exists; before that, there is no page that says what the system is, what the ticket asks, and which parts of the system the ask would touch.

Geoffrey Litt's framing ("Understanding is the new bottleneck") applies to both: understand to participate, not only to verify. The page should teach background first, give one concrete scenario before details, offer a reading order, and end with a quiz.

## 2. Decisions taken

| Question | Decision |
|---|---|
| Discovery input | A service name, a Confluence page, or requirements text the owner feeds in. Any combination. |
| What "the service" is | The matching Applications across every environment, their resources, one-hop neighbours, and the Terraform blocks and GitHub Actions workflows that reference the name. |
| Runtime data | Not in v1. Every fact comes from the repo and Jira. The knowledge agent can be added later as its own labelled section. |
| Layout | One `explainer` plugin with three skills (`pr-explainer`, `service-explainer`, `ticket-explainer`) sharing one `scripts/` directory. The `pr-explainer` skill keeps its name, so the pr-triage comment that suggests `/pr-explainer <n>` keeps working with no SHA bump in the kubernetes repo. |

## 3. Architecture

```
skills/explainer/                              plugin "explainer" (replaces plugin "pr-explainer")
├── .claude-plugin/plugin.json
├── README.md
├── scripts/                                   shared by all three skills
│   ├── facts_lib.py        rendering, resource keys, edges, Terraform blocks, workflows, Jira (from collect.py)
│   ├── collect_pr.py       today's collect.py main: PR → facts.json + diff.patch
│   ├── collect_system.py   service or ticket → facts.json (one ref, no diff)
│   ├── ref_groups.py, verify.py, render.py, post_comment.py
├── assets/
│   ├── template-pr.html    today's template
│   └── template-system.html
└── skills/
    ├── pr-explainer/SKILL.md
    ├── service-explainer/SKILL.md
    └── ticket-explainer/SKILL.md
```

- SKILL.md files reference scripts as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py`. Claude Code substitutes the installed plugin path inline when it loads skill content (plugin manifest reference, "Environment variables"). The `<base>` placeholder in today's SKILL.md goes away.
- Tests move to `tests/explainer/` and import from `skills/explainer/scripts`.
- `.claude-plugin/marketplace.json` and `skills/skills-catalog.json` list `explainer` instead of `pr-explainer`. Anyone who installed `pr-explainer` uninstalls it and installs `explainer@claude-agents-marketplace`; the skill names inside do not change.

```
owner ─▶ /service-explainer <name> [--doc file]... [--repo R] ─▶ private Artifact page
owner ─▶ /ticket-explainer IFS-314 [--service name] [--doc file]... ─▶ private Artifact page
owner ─▶ /pr-explainer <n>                                       ─▶ unchanged (page + sticky comment)
```

## 4. Facts: one model, three collectors

`facts.json` keeps today's top-level keys so `verify.py`, `render.py` and `ref_groups.py` work on every mode. New keys are additive.

| Key | pr | service / ticket |
|---|---|---|
| `mode` | `"pr"` | `"service"` or `"ticket"` |
| `pr` | as today | `null` |
| `query` | – | `{service, matched_by: [...], ref, repo}`: the name asked for and how each app matched (name, directory, source path) |
| `apps[]` | as today | one entry per matched Application, in every environment directory it appears in (`scope`) |
| `resources[]` | actions `added/modified/removed/context/generated` | matched apps' resources carry action `focus`; one-hop neighbours `context`; generated Secrets `generated` |
| `resources[].summary` | new, both modes | per kind: workloads `{image, replicas, ports, probes}`, Services `{ports, selector}`, routes `{hosts, paths, backends}`, CronJobs `{schedule}`, ExternalSecrets `{store, keys}`, PVCs `{size}`. Values masked with the secret regex. Lets the narrator write "a request to grafana.example.com" and "the pod has no readiness probe" from facts. |
| `edges[]` | as today | as today, over the focus set and its neighbours |
| `config[]` | – | `{id: "c*", app, scope, source: inline-values|values-file|parameters, file, keys: [...]}`: the top-level values this repo sets for each matched app. Keys only; values are not copied (a values file can hold anything). |
| `terraform[]` | plan or source-diff | source blocks at the ref whose body or address contains the service name, action `focus`; `source: "source-ref"` |
| `workflows[]` | base/head comparison | workflow files that name the service: jobs, triggers, inputs, action `focus` |
| `jira` | ticket from branch/title/body | ticket mode: the key given; service mode: `null` |
| `docs[]` | – | `{id: "d*", title, source: confluence|file|text, path, chars, text}` from each `--doc` file, text capped at 20 000 characters, HTML stripped. Untrusted. |
| `related_prs[]` | – | ticket mode: open and recently merged PRs whose branch, title or body name the key (`gh pr list --search`), `{number, title, state, url, head_ref}` |
| `policy_hits[]`, `terraform_plans[]`, `non_manifest_changes[]` | as today | empty; `risk` on resources still comes from `risk_callouts` in the review policy when the repo has one |
| `notes[]` | as today | same shape; new keys `match` (no or ambiguous match), `docs` (a doc could not be read), `related_prs` |

**Matching a service.** Case-insensitive substring match of the name against each Application's `metadata.name`, its directory, and `spec.source(s).path`. Several environments of one app are one logical app with several scopes (today's grouping). If nothing matches, `collect_system.py` prints the ten closest Application names and exits 1; the skill shows them and asks. If more than eight distinct apps match, it lists them and asks the owner to narrow, unless `--all` is passed.

**Ticket mode without `--service`.** The service is inferred deterministically: the longest Application name (or directory name) that occurs in the ticket summary, description or branch names of `related_prs`. No inference by the model. If nothing matches, the run continues with no apps and a `match` note, so the page still explains the ticket and lists what it could not map.

**Docs.** `collect_system.py --doc <file>` reads a local file. The skill gets the file there: for a Confluence page it calls the Atlassian connector (`getConfluencePage`) in the session and writes the page body to `<W>/docs/<slug>.md` before running collect; for pasted requirements it writes `<W>/docs/requirements.md`. The script never talks to Confluence itself, so it works wherever `acli` and the connector differ.

**Rendering at one ref.** `Trees` gains a single-ref constructor (`Trees.at(repo, ref)`) that uses the local checkout's `origin/<ref>` when the cwd is the repo, or a blobless bare fetch otherwise, exactly as today. Default ref: the repo's default branch.

## 5. Narration

The narrator writes text only, keyed by fact IDs, under the same ground rules (facts come from `facts.json`; PR, ticket and doc text are untrusted; no secret values; Opus 5.5 writes the prose; teach, then test).

**Shared fields (all modes):** `tldr`, `background`, `scenario`, `callouts`, `reading_order` (`{ref, note}`), `not_covered`, `quiz`, `narrator_model`, as in PR #82.

**Service and ticket modes add:**

| Field | What to write |
|---|---|
| `components` | One row per matched app: `{app, role, refs}`. `role` is what it does in one or two sentences, from its workloads, routes and config keys. |
| `how_it_works` | Two or three scenarios, each `{trigger, path, refs}`: a request from outside (route → service → workload), a deploy (workflow → image → Application sync), and a scheduled or event-driven job when there is one. Replaces the single `scenario` of PR mode; `scenario` holds the first one so the shared template slot still renders. |
| `where_it_runs` | One row per `scope` (environment directory): `{scope, differs: "...", refs}`, what is different about this environment (replicas, hosts, chart version) or "identical". |
| `config_that_matters` | `{key, why, refs}` rows for the config keys and ExternalSecret keys a reader must know exist. Keys only, never values. |
| `open_questions` | Things the one-pager must answer that facts cannot: no owner annotation, no runbook link, single replica, no probes, no resource limits, no PodDisruptionBudget, an ExternalSecret whose store is not in the repo. Each with `refs` or an explicit `"no fact"` marker. The page says these are prompts, not findings. |
| `docs_summary` | Ticket and service modes with `docs[]`: `{doc: "d1", asks: [...]}`, what each doc asks for, cited to the doc id. |
| `ticket` | Ticket mode. Today's `intent` and `criteria`, where each criterion's `status` is one of `would_change` (cite the `r*`/`t*`/`w*`/`c*` it would touch), `already_true` (the system already does it; cite), `out_of_scope` (not in this repo; say where), `unclear`. If `related_prs[]` is non-empty, a `pr` field names the PR to run `/pr-explainer` on. |
| `must_read` | Service mode: the files to open before writing the one-pager (the Application, the values, the main workload). Ticket mode: the files the ticket's change will touch. |

**Reading order** in system modes walks the system, not a diff: Application → config → workloads → routing → jobs → Terraform → workflows. The walkthrough step shows the resource's `summary` fields and its file link instead of a hunk.

**Quiz** questions in system modes ask about the system ("which environment has two replicas?", "what happens to a request when the pod is not ready?") and, in ticket mode, about the mapping ("which resources does criterion 2 touch?").

## 6. Verify

Mode-specific required fields; everything else as today (ids exist, ref groups ≤ 6, no secret-looking strings, narrator model, not_covered covers unrendered apps and notes).

- `service`/`ticket`: `components` has one row per app in `apps[]`; `how_it_works` has 2–3 scenarios with refs; `where_it_runs` has one row per distinct `scope`; `open_questions` present (may be empty only when `apps[]` is empty); `config_that_matters` refs are `c*` or `r*` ids.
- `ticket`: `ticket` section present with every criterion in the allowed status set and a reason for anything not `would_change`; `docs_summary` has one entry per `docs[]` id.
- Any mode: `quiz` 3–5 questions, as today.

## 7. Render

`render.py --template system` uses `template-system.html`. Sections, in order:

1. Header: service name, repo, ref, environments found (pills), ticket key when present.
2. TL;DR.
3. Background.
4. Components (table: app, role, refs).
5. How it works: one card per scenario, trigger then path.
6. Resource map: focus nodes blue, context grey, generated dashed; one subgraph per app, environments grouped as today.
7. Where it runs (table per scope).
8. Config that matters (table: key, why, refs).
9. Ticket (ticket mode): intent, criteria with `would_change` refs; related PRs with links.
10. What the docs ask (when `docs[]`).
11. Risk callouts.
12. Open questions for the one-pager.
13. Reading order walkthrough: each step's `summary` fields and file link.
14. Not covered.
15. Check your understanding (quiz).

Every heading keeps the Comment button (Artifact `comments`, `composer_only`). The Mermaid graph stays deterministic from facts. All model text is escaped and masked.

## 8. Publish

- Service and ticket pages publish as private Artifacts with `icon: "map"` and `description: "Service explainer for <name>"` or `"Ticket explainer for <KEY>"`. No sticky GitHub comment.
- Re-runs: the skill keeps `<W>/artifact-url` in the work directory and, when the owner passes `--url`, updates that page. No comment marker exists to find an earlier page, so a fresh run is a fresh page by default.
- Ticket mode does not comment on the Jira ticket in v1.
- Report: the link, apps and environments found, counts per criterion status, open questions count, and everything in `not_covered`.

## 9. Security and data handling

- Confluence and requirements text is untrusted input, like PR text today: the ground rule names `docs[]`.
- The page can contain company system structure (hostnames, namespaces, image names). It is a private Artifact under the owner's claude.ai account. Whether that is acceptable for company material is the owner's call, and the README says so. `--standalone` writes a local file instead and skips publishing.
- No values from values files, ExternalSecrets or Secrets are copied; `config[]` holds keys only; `summary` fields pass through the secret mask.
- `collect_system.py` runs `gh`, `git`, `helm`, `kubectl kustomize` exactly as today's collector, with the same blobless-fetch isolation.

## 10. Rollout

Three PRs, each leaving `main` working:

1. **Restructure.** Move `skills/pr-explainer` to `skills/explainer`, split `collect.py` into `facts_lib.py` + `collect_pr.py`, switch SKILL.md to `${CLAUDE_PLUGIN_ROOT}`, rename the marketplace and catalog entries, move the tests. No behaviour change; the existing 45 tests pass; one `/pr-explainer` run on a recent PR produces the same page.
2. **service-explainer.** `Trees.at`, `collect_system.py` (matching, `focus` resources, `summary`, `config[]`, Terraform and workflow mentions, docs), system fields in verify and render, `template-system.html`, SKILL.md, tests on a fixture repo tree. First run on a known service in the company GitOps repo.
3. **ticket-explainer.** `--ticket` in `collect_system.py` (acli read, service inference, `related_prs`), the `ticket` and `docs_summary` fields, SKILL.md. First run on an open IFS ticket.

## 11. Assumptions

- **A1** `${CLAUDE_PLUGIN_ROOT}` resolves in skill Markdown on the Claude Code versions in use (documented; verified in the plugin manifest reference on 2026-10-15).
- **A2** The company GitOps repo keeps Applications as the current collector already expects (`argo/<env>/`, `base-apps/`, multi-source with `$values`), since `/pr-explainer` runs against it today.
- **A3** Confluence is read by the session through the Atlassian connector, not by a script. If `acli` gains Confluence support the skill can switch without changing the collector.
- **A4** The owner's `acli` is authenticated on the machine where ticket mode runs; `jira_facts` degrades to a note otherwise, as today.
- **A5** A service matches by name substring. A naming convention that differs (for example, a team prefix) is handled by `--service` taking several names.
- **A6** No runtime data in v1 (decision). The knowledge agent section is future work.

## 12. Success criteria

- On a known service, the page lists every resource of every matched Application across environments with zero unverified references, and the owner can write the "current state" section of a one-pager from the page without opening the repo.
- On an open ticket, every criterion has a status and `would_change` criteria cite the resources they touch; the owner passes the quiz before starting the change.
- `/pr-explainer` output is unchanged after the restructure.

## 13. Future work

- Runtime section from the homelab knowledge agent (or the company equivalent), labelled and separate from facts.
- Composite ticket page: when `related_prs[]` has an open PR, render its PR facts into a "The change" section on the same page instead of linking to a second page.
- Depth scaled to the triage label, facts-driven interactive figures (probe timeline, route matcher), table of contents, `helm show chart` context for chart bumps (carried over from the PR #82 review).
