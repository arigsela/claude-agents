# Code Review

AI-powered code review for pull requests using parallel specialized agents with confidence-based scoring to filter false positives. Use when reviewing PRs, analyzing code changes, checking CLAUDE.md compliance, detecting bugs, or posting review comments.

## Installation

```bash
# From this repository
claude skill add ./skills/code-review

# Manual installation
cp -r skills/code-review ~/.claude/skills/
```

## Documentation

See [SKILL.md](./SKILL.md) for full skill instructions and usage.

## Files

- `SKILL.md` - Claude Code skill definition
- `references/` - Extended documentation
  - `advanced-review.md` - CI/CD integration, custom scoring, multi-repo setups
