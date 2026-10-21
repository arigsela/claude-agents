# Advanced Code Review

Extended documentation for CI/CD integration, custom scoring, and automation.

## CI/CD Integration

### GitHub Actions

```yaml
name: AI Code Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  code-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run AI Code Review
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # Claude Code will run /code-review --comment
          claude code-review --comment
```

### GitLab CI

```yaml
ai-code-review:
  stage: review
  script:
    - claude code-review --comment
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

## Custom Scoring Functions

### Security-Weighted Scoring

For security-critical projects, adjust scoring weights:

```
Security scoring:
- SQL injection potential: +40
- XSS vulnerability: +35
- Authentication bypass: +50
- Hardcoded secrets: +45
- Input validation missing: +30
```

### Performance-Weighted Scoring

For performance-critical code:

```
Performance scoring:
- N+1 query pattern: +35
- Unbounded loop: +30
- Missing pagination: +25
- Large memory allocation: +30
- Blocking operation in async: +40
```

## Multi-Repository Setup

### Monorepo Configuration

For monorepos with multiple CLAUDE.md files:

```bash
# Search pattern for monorepo CLAUDE.md files
find . -name "CLAUDE.md" -path "*/packages/*" | head -20

# Priority order:
# 1. Package-level CLAUDE.md (most specific)
# 2. Root CLAUDE.md (global standards)
```

### Shared Guidelines

Create a shared CLAUDE.md at repo root with common standards:

```markdown
# Root CLAUDE.md
- All packages must have error boundaries
- Use TypeScript strict mode
- No console.log in production code

# Package overrides in packages/*/CLAUDE.md
```

## Webhook Automation

### Automatic Review on PR Creation

```javascript
// GitHub webhook handler
app.post('/webhook', (req, res) => {
  const { action, pull_request } = req.body;

  if (action === 'opened' || action === 'synchronize') {
    // Trigger review
    triggerCodeReview(pull_request.number);
  }
});
```

### Slack Integration

Post review results to Slack:

```bash
# After review completes
gh pr view --json body | jq '.body' | \
  curl -X POST -H 'Content-type: application/json' \
  --data '{"text": "Code review complete"}' \
  $SLACK_WEBHOOK_URL
```

## Agent Customization

### Security-Focused Agent Template

```markdown
## Security Agent Instructions

Focus areas:
1. Authentication and authorization flaws
2. Input validation and sanitization
3. SQL/NoSQL injection vectors
4. Cross-site scripting (XSS)
5. Sensitive data exposure
6. Security misconfiguration

Reference: OWASP Top 10
```

### Performance Agent Template

```markdown
## Performance Agent Instructions

Focus areas:
1. Database query efficiency
2. Memory leaks and allocation
3. Caching opportunities
4. Async/await patterns
5. Bundle size impact
6. API response times
```

## Filtering Strategies

### Language-Specific Filters

**JavaScript/TypeScript:**
- Ignore ESLint-covered issues
- Focus on type safety gaps
- Check for async/await misuse

**Python:**
- Ignore PEP8 formatting (handled by Black/Ruff)
- Focus on type hint consistency
- Check for resource cleanup

**Go:**
- Ignore gofmt issues
- Focus on error handling patterns
- Check for goroutine leaks

## Review Comment Templates

### Bug Found
```markdown
**Bug detected** (confidence: {score}%)

{description}

**Evidence:** Line {start}-{end} shows {pattern}
**Fix:** {suggested_fix}

Link: {github_link}
```

### CLAUDE.md Violation
```markdown
**Guideline violation** (confidence: {score}%)

CLAUDE.md states: "{exact_quote}"

This code: {violation_description}

Link: {github_link}
```

## Metrics and Tracking

Track review effectiveness:

```bash
# Issues found per PR
gh api repos/{owner}/{repo}/pulls/{pr}/reviews \
  --jq '.[] | select(.body | contains("Code review"))'

# False positive rate (manual tracking)
# Track issues marked as "won't fix" or "not applicable"
```
