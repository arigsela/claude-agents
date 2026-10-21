# review-retro

`/review-retro <PR>` (or `--since 14d`) runs a retrospective of a `/code-review` session. It
finds the session transcript and compares the review's findings with what later needed fixing:
follow-up fix/revert PRs within 72 h, and human comments. Each miss gets a cause, cited to
transcript lines:

- not read
- no lens
- filtered
- missing context
- not diff-detectable

The report also covers token cost. It ends with up to 5 concrete edits to the `code-review`
skill or `review-policy.yaml`, and none are applied without your approval.

Transcripts are deleted after `cleanupPeriodDays`, which is 30 by default. To retro older
reviews, raise it in `~/.claude/settings.json`, for example `"cleanupPeriodDays": 90`.

Design: `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md` §7.

Install: `/plugin install review-retro@claude-agents-marketplace`
