# pr-explainer

`/pr-explainer <PR>` explains a GitOps PR without reading code. It renders the changed Argo CD
apps at the PR's base and head, so a one-line chart bump shows its real resource changes.
Then it publishes a private page with:

- a TL;DR
- a resource map built by a script, never drawn by the model
- a before→after table
- risk callouts from `.github/review-policy.yaml`
- the hunks you must still read

It also posts the page link as a sticky PR comment.

Run it from anywhere. Inside a checkout of the PR's repo, `/pr-explainer <PR>` uses that checkout
and its `.github/review-policy.yaml`. Anywhere else, pass the repo (`/pr-explainer <PR> --repo
owner/name`): `collect.py` fetches the PR into a temporary blobless bare repo, authenticated with
`gh`, and deletes it afterwards.

Requirements:
- Required: `gh`, `git`, `uv`.
- Optional: `helm`, for Helm-sourced apps (`brew install helm`).
- Optional: `acli`, authenticated to Jira, for the IFS ticket card.
- Kustomize apps use `kubectl kustomize`.

Terraform/OpenTofu changes (any `.tf` file, at any depth) get their own resource map. Resources
come from plan comments on the PR: every environment's `<!-- iac-pr-plan:<env> -->` comment from
`chg-opentofu-workflows`' `opentofu-pr-plan.yaml`, or else the newest Atlantis-style comment
(`# <address> will be created` lines). The page shows each plan's totals and flags plans that are
stale (older than the PR head), failed, or cut off (the workflow keeps only the last 60000
characters of the plan, so large plans map only some resources). Without a plan comment,
`collect.py` compares the `resource` and `data` blocks at base and head in each changed root and
marks them added, modified or removed. Those are source-level changes, not plan results.

If the branch name, title or body names an IFS ticket (branch first), `collect.py` reads it with
`acli jira workitem view` and the page adds a Ticket card: the ticket's intent and each ask marked
covered, not covered or unclear against the mapped resources. Without `acli`, or without a key, the
run continues and says so under "Not covered".

The prose is written by Claude Opus 5.5 (`claude-opus-5-5`): the skill pins the model, delegates to
an Opus subagent when managed settings block the pin, and `verify.py` marks the page unverified if
the explainer was written by any other model. The page header names the model.

Apps that cannot be rendered are listed under "Not covered".

Design: `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md` §6.

Install: `/plugin install pr-explainer@claude-agents-marketplace`
