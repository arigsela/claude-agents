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

Requirements:
- Required: `gh`, `git`, `uv`.
- Optional: `helm`, for Helm-sourced apps (`brew install helm`).
- Kustomize apps use `kubectl kustomize`.

Terraform/OpenTofu changes (any `.tf` file, at any depth) get their own resource map. Resources
come from the newest plan comment on the PR (`# <address> will be created` lines). Without one,
`collect.py` compares the `resource` and `data` blocks at base and head in each changed root and
marks them added, modified or removed. Those are source-level changes, not plan results.

Apps that cannot be rendered are listed under "Not covered".

Design: `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md` §6.

Install: `/plugin install pr-explainer@claude-agents-marketplace`
