---
name: code-review
description: AI-powered code review for pull requests using parallel specialized agents with confidence-based scoring to filter false positives. Use when reviewing PRs, analyzing code changes, checking CLAUDE.md compliance, detecting bugs, or posting review comments. Triggers on requests like "review this PR", "code review PR #123", or "check my pull request".
version: "1.0.0"
author:
  name: "Arisela"
tags: [code-review, pull-request, github, quality, testing]
category: development
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
requires:
  tools: [gh, git]
---

# Code Review

Automated code review system using multiple specialized AI agents running in parallel to independently audit changes from different perspectives. Uses confidence-based scoring (0-100) to filter false positives.

## Workflow Overview

1. **Validate** - Check if review is needed (skip closed, draft, trivial, or already-reviewed PRs)
2. **Prepare** - Gather CLAUDE.md guidelines from the repository
3. **Summarize** - Create summary of PR changes
4. **Parallel Review** - Launch 4 independent agents
5. **Score** - Score each issue 0-100 for confidence
6. **Filter** - Remove issues below threshold (default: 80)
7. **Output** - Terminal output or PR comment

## Usage

```bash
# Review current PR, output to terminal
/code-review

# Review and post as PR comment
/code-review --comment

# Review specific PR
/code-review PR_NUMBER

# Review with custom threshold
/code-review --threshold 70
```

## Review Process

### Step 1: Validation

Before reviewing, check if review is appropriate:

```bash
gh pr view --json state,isDraft,additions,deletions
```

**Skip review if:**
- PR is closed or merged
- PR is in draft state
- Changes are trivial (automated version bumps, dependency updates only)
- PR already has a comprehensive review

### Step 2: Gather Context

Collect CLAUDE.md files from the repository:

```bash
# Find all CLAUDE.md files
find . -name "CLAUDE.md" -o -name "claude.md" | head -20

# Read each file to understand project standards
```

CLAUDE.md files contain project-specific guidelines, coding standards, and requirements that reviewers must check against.

### Step 3: Get PR Details

```bash
# Get PR diff
gh pr diff

# Get PR metadata
gh pr view --json title,body,files,commits
```

### Step 4: Parallel Agent Review

Launch 4 independent review agents simultaneously using the Task tool:

**Agent 1 & 2: CLAUDE.md Compliance (Redundancy)**
- Check all changes against CLAUDE.md guidelines
- Look for explicit rule violations
- Only flag issues where CLAUDE.md is specific

**Agent 3: Bug Detection**
- Scan for obvious bugs in the changed code
- Focus ONLY on changes, not pre-existing issues
- Look for null checks, error handling, edge cases

**Agent 4: History Analysis**
- Use git blame to understand context
- Check if changes break established patterns
- Analyze commit history for relevant context

```bash
# Git blame for context
git blame -L START,END FILE

# Recent commits affecting these files
git log --oneline -10 -- FILE
```

### Step 5: Confidence Scoring

Score each found issue on a 0-100 scale:

| Score | Meaning |
|-------|---------|
| 0 | Not confident - likely false positive |
| 25 | Somewhat confident - might be real |
| 50 | Moderately confident - real but minor |
| 75 | Highly confident - real and important |
| 100 | Absolutely certain - definitely a real issue |

**Scoring criteria:**
- Is this actually introduced by the PR? (+30)
- Does CLAUDE.md explicitly mention this? (+25)
- Would this cause runtime errors? (+25)
- Is this a security concern? (+20)
- Is there clear evidence in the diff? (+20)

### Step 6: Filter False Positives

Remove issues scoring below threshold (default: 80).

**Common false positives to exclude:**
- Pre-existing issues not introduced in this PR
- Code that looks like a bug but functions correctly
- Pedantic nitpicks not in CLAUDE.md
- Issues that linters will catch
- General code quality (unless CLAUDE.md specifies)
- Code with explicit lint ignore comments

### Step 7: Format Output

Output format for found issues:

```markdown
## Code review

Found N issues:

1. [Issue description] (CLAUDE.md says "[exact quote]" OR [bug explanation])

https://github.com/OWNER/REPO/blob/SHA/PATH#LSTART-LEND

2. [Next issue...]
```

**Link format requirements:**
- Use full commit SHA, not abbreviated
- Use `#L[start]-L[end]` for line ranges
- Link to the exact file and lines

## Configuration

### Adjusting Confidence Threshold

Modify threshold based on project needs:
- **Strict (90+)**: Only highest-confidence issues
- **Standard (80)**: Balanced approach (default)
- **Thorough (70)**: More issues, some false positives
- **Permissive (60)**: Maximum coverage

### Adding Custom Review Agents

Extend the review by adding specialized agents:

- **Security Agent**: Focus on OWASP vulnerabilities
- **Performance Agent**: Check for performance regressions
- **Accessibility Agent**: Verify a11y compliance
- **Documentation Agent**: Check doc updates match code changes

## Best Practices

**When to use:**
- All PRs with meaningful code changes
- PRs touching critical paths
- PRs from multiple contributors
- When guideline compliance matters

**When NOT to use:**
- Closed or draft PRs (auto-skipped)
- Trivial automated PRs (auto-skipped)
- Urgent hotfixes requiring immediate merge
- Already-reviewed PRs (auto-skipped)

## Requirements

- Git repository with GitHub integration
- GitHub CLI (`gh`) installed and authenticated
- CLAUDE.md files (optional but recommended)

Verify setup:
```bash
gh auth status
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Takes too long | Normal for large PRs; consider splitting PRs |
| Too many false positives | Raise threshold or make CLAUDE.md more specific |
| No comment posted | Check if PR is closed/draft/trivial or no issues >=80 |
| Link formatting broken | Ensure full SHA and `#LSTART-LEND` format |
| GitHub CLI not working | Run `gh auth login` |

## Advanced Usage

See [references/advanced-review.md](references/advanced-review.md) for:
- CI/CD integration
- Custom scoring functions
- Multi-repo setups
- Webhook automation
