# explainer

One plugin, four skills that share one facts pipeline:

- `/pr-explainer <PR>` explains a GitOps PR (below).
- `/service-explainer <name>` explains a service under discovery (below).
- `/ticket-explainer <KEY>` explains a ticket's system and maps its asks onto it (below).
- `/plan-explainer <file> --repo R` explains where a plan (a one-pager) lands in a repo (below).

Layout: `scripts/` (shared: `facts_lib.py`, `collect_pr.py`, `verify.py`, `render.py`,
`ref_groups.py`, `post_comment.py`), `assets/` (one page template per mode), `skills/<name>/SKILL.md`.

## pr-explainer

`/pr-explainer <PR>` explains a GitOps PR without reading code. It renders the changed Argo CD
apps at the PR's base and head, so a one-line chart bump shows its real resource changes.
Applications are found anywhere in the repo (`base-apps/`, `argo/<env>/`, ...), including
multi-source Helm apps with `$values` files; the same app in several environments draws once.
Then it publishes a private page with:

- a TL;DR
- the background: what was already there, for a reader who has not opened the app in months
- one concrete scenario (a request, a restart, a push) walked before and after the change
- a resource map built by a script, never drawn by the model
- a before→after table
- risk callouts from `.github/review-policy.yaml`
- the hunks you must still read
- a walkthrough in dependency order, one note per item with its hunk inline (must-read hunks
  start open; items rendered from a chart or plan list their changed paths instead)
- a quiz of 3–5 multiple-choice questions, each answerable from the page and cited to facts; the
  bar for approving is passing it

It also posts the page link as a sticky PR comment. Every section has a Comment button that opens
the claude.ai composer on that section, so questions land next to what they are about; threads are
posted and shown by claude.ai, never by the page.

The shape follows Geoffrey Litt's "Understanding is the new bottleneck": background first,
intuition before details, a literate diff instead of files in alphabetical order, and a quiz as the
speed regulator. Unlike his `/explain-diff`, every sentence here cites a fact the scripts
collected, and `verify.py` rejects a page that cites nothing.

Run it from anywhere. Inside a checkout of the PR's repo, `/pr-explainer <PR>` uses that checkout
and its `.github/review-policy.yaml`. Anywhere else, pass the repo (`/pr-explainer <PR> --repo
owner/name`): `collect.py` fetches the PR into a temporary blobless bare repo, authenticated with
`gh`, and deletes it afterwards.

Requirements:
- Required: `gh`, `git`, `uv`.
- Optional: `helm`, for Helm-sourced apps (`brew install helm`).
- Optional: `acli`, authenticated to Jira, for the IFS or DX ticket card.
- Kustomize apps use `kubectl kustomize`.

Terraform/OpenTofu changes (any `.tf` file, at any depth) get their own resource map. Resources
come from plan comments on the PR: every environment's `<!-- iac-pr-plan:<env> -->` comment from
`chg-opentofu-workflows`' `opentofu-pr-plan.yaml`, or else the newest Atlantis-style comment
(`# <address> will be created` lines). The page shows each plan's totals and flags plans that are
stale (older than the PR head), failed, or cut off (the workflow keeps only the last 60000
characters of the plan, so large plans map only some resources). Without a plan comment,
`collect.py` compares the `resource` and `data` blocks at base and head in each changed root and
marks them added, modified or removed. Those are source-level changes, not plan results.

GitHub Actions workflow changes (files directly under `.github/workflows/`) get their own map
too. `collect.py` compares each changed workflow at base and head: jobs drawn in run order from
`needs`, plus grouped nodes for `workflow_call`/`workflow_dispatch` inputs, outputs and secrets,
triggers and workflow-level settings. A removed `workflow_call` input, output or secret, a newly
required input, and a `permissions` change are always-read policy hits, because they break callers
or change what the job token can do. Expressions, matrix expansion, the reusable workflows a job
calls, composite actions and callers in other repositories are not resolved.

If the branch name, title or body names an IFS or DX ticket (branch first), `collect.py` reads it with
`acli jira workitem view` and the page adds a Ticket card: the ticket's intent and each ask marked
covered, respected (a scope limit the PR keeps), done outside this PR (cited from a ticket
comment), not covered or unclear, with the reason for anything not covered. Without `acli`, or without a key, the
run continues and says so under "Not covered".

The prose is written by Claude Opus 5.5 (`claude-opus-5-5`): the skill pins the model, delegates to
an Opus subagent when managed settings block the pin, and `verify.py` marks the page unverified if
the explainer was written by any other model. The page header names the model.

Apps that cannot be rendered are listed under "Not covered".

Design: `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md` §6 and `2026-10-15-explainer-plugin-design.md`.

Install: `/plugin install explainer@claude-agents-marketplace` (replaces `pr-explainer`; uninstall that one first).

## service-explainer

`/service-explainer <name>` explains a service before anyone changes it: for a one-pager, for
discovery, or before picking up a ticket. `collect_system.py` reads the repo at one ref (the
default branch unless `--ref`), finds every Argo CD Application whose name, directory or source
path contains the name (across every environment directory), renders them, and records:

- every resource as `focus`, each with a `summary` per kind (image, replicas, ports, probes, env
  names, hosts, paths, backends, schedule, secret store and keys, size, data keys), masked
- the config keys this repo sets per app (inline helm values, parameters, value files): keys only
- the Terraform resource/data blocks and the GitHub Actions workflows that name the service
- any `--doc` file (a Confluence page the session saved, pasted requirements), as untrusted text

The page has: TL;DR, background, components, how it works (two or three traced scenarios: a
request, a deploy, a job), the resource map, where it runs per environment, config that matters,
what the docs ask, risk callouts, the files to open first, open questions for the one-pager,
a walkthrough with each item's facts inline, and a quiz. Every sentence cites a fact; `verify.py`
enforces one component per app, one row per environment, 2–3 scenarios, cited config keys, and a
summary per doc.

No match: the collector lists the ten closest Application names and the skill asks. More than
eight matches: it asks you to narrow the name or pass `--all`. No GitHub or Jira comment is
posted; pass `--url` to update an earlier page.

The page is a private Artifact under your claude.ai account and holds the repo's view of the
service (hostnames, namespaces, images, config keys). Whether that is acceptable for your
company's material is your call; `--standalone` writes a local file instead.

## ticket-explainer

`/ticket-explainer IFS-314` explains the system a ticket is about before the change exists.
`collect_system.py --ticket` reads the ticket through `acli`, lists the PRs that name the key
(`gh pr list --search`), and infers the service deterministically: the longest Application name
(or manifest directory name) found in the ticket summary, description, or the related PRs' branch
names and titles. `--service` overrides the inference. Then it collects everything the service
explainer collects for that service.

The page adds a Ticket card to the service page: the intent, each ask with a status
(`would_change` with the resources it would touch, `already_true`, `out_of_scope`, `unclear`,
each with a reason), and links to related PRs. When an open PR names the ticket, the report
suggests `/pr-explainer <n>` for the change itself. `verify.py` requires the card in ticket mode,
a resource cited for every `would_change`, a reason for every other status, and the open PR named
in `ticket.pr`.

Without `acli` the run continues with a `jira` note and no card; with no service named anywhere,
it continues with no apps and a `match` note.

## plan-explainer

`/plan-explainer <file> --repo R` explains a plan (a project one-pager, a design doc,
requirements) against the repo it changes, before any code exists. It needs no Argo CD
Application, so it covers Terraform-only and greenfield work. `collect_system.py --plan` takes
the plan as the first `--doc` and searches the repo at one ref for every identifier the plan
quotes in backticks (placeholders such as `{env}` dropped; versions, globs, prose and plain
English words skipped), plus any `--term`:

- the Terraform resource/data blocks and the GitHub Actions workflows that name a term
- the tracked text files that name a term (`f*`: locals, backends, a Justfile, CODEOWNERS,
  READMEs), with the lines, capped at 40 files
- `query.term_hits`: each term and the ids that name it; a term with no hit gets a `terms` note

The page adds a Plan card after the background: each plan step with a status (`would_change`
citing what it edits, `already_true` citing where, `new` citing the plan, `out_of_scope`,
`unclear`) and the plan's terms, found or not in this repo. `verify.py` requires the card in plan
mode, a repo fact for `would_change` and `already_true`, the plan doc for `new`, a reason for
every status but `would_change`, and at least one open question. One run reads one repo; a plan
that changes two repos takes two runs. `--service` also renders matching Applications.

## Infographic slides (opt-in)

`--infographic` on any of the four explainers asks Codex for up to three slides of the
verified page with the `tech-infographics` skill, and `render.py --infographic <png>` inlines the
ones Claude checked against the brief in an "At a glance" section, labelled as an illustration,
not a fact source. `infographic.py` builds `brief.md` from `explainer.json` only (masked; no
`facts.json`, no repo), runs `codex exec -s workspace-write --ephemeral`, and stops it after 15
minutes. It is off by default and does nothing with `--standalone`, because the brief leaves the
machine for OpenAI. Without `codex` on PATH or the skill in `~/.agents/skills/` or
`~/.codex/skills/`, it exits 2 and the page renders without slides. On a PR page the brief holds
the TL;DR, the before and after, the changes per app and the medium and high risks; the slides
appear on the claude.ai page only, not in the sticky PR comment.
