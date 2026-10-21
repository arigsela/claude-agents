# pr-triage

Labels every pull request `review:skip`, `review:skim` or `review:read`, and keeps one sticky
comment explaining why. Design: `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md`.

**How it decides**

1. Rules from `.github/review-policy.yaml`, read at the PR's base commit.
2. One Jev (TypeSafe) request with several questions.
3. Claude only when Jev is unsure. Claude also writes the "What to look at" note for skim/read PRs.

It only labels. It never blocks, approves or merges.

## Use

```yaml
- uses: arigsela/claude-agents/pr-triage@<commit-sha>
  env:
    GH_TOKEN: ${{ github.token }}
    TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  with:
    pr-number: ${{ github.event.pull_request.number }}
    repo: ${{ github.repository }}
    policy-ref: ${{ github.event.pull_request.base.sha }}
```

If a secret is missing or an API fails, triage falls back to the rules, then to `review:read`,
and the comment says `triage degraded: …`.

## Local runs

```bash
uv run --project pr-triage python -m pr_triage features --repo owner/name --pr 123 [--policy-file path]
uv run --project pr-triage python -m pr_triage run --repo owner/name --pr 123 --dry-run [--policy-file path]
uv run --project pr-triage python -m pr_triage calibrate --repo owner/name --limit 200 [--compare haiku] --out calibration.md
```

Re-run `calibrate` whenever the Jev model, the question text, the criteria or the thresholds change.
They are versioned as one unit.
