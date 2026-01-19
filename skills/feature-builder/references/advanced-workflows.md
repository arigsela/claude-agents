# Advanced Workflows

Complex patterns for multi-feature development and team collaboration.

## Multi-Feature Pipeline

Chain multiple features in sequence:

```bash
# Feature 1: Data layer
/feature-builder "Add User model with CRUD operations" --auto-pr

# Feature 2: API layer (depends on Feature 1)
/feature-builder "Add REST API for User CRUD" --auto-pr

# Feature 3: UI layer (depends on Features 1-2)
/feature-builder "Add User management UI" --auto-pr
```

### Parallel Feature Development

For independent features, run in parallel branches:

```bash
# Terminal 1
git checkout -b feature/auth
/feature-builder "Add authentication"

# Terminal 2
git checkout -b feature/logging
/feature-builder "Add logging infrastructure"

# Merge when both complete
git checkout main
git merge feature/auth feature/logging
```

## CI/CD Integration

### GitHub Actions Workflow

```yaml
name: AI Feature Builder
on:
  issues:
    types: [labeled]

jobs:
  build-feature:
    if: contains(github.event.label.name, 'ai-build')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Extract feature request
        id: feature
        run: |
          echo "request=${{ github.event.issue.body }}" >> $GITHUB_OUTPUT

      - name: Run Feature Builder
        run: |
          claude feature-builder "${{ steps.feature.outputs.request }}" --auto-pr

      - name: Link PR to Issue
        run: |
          gh issue comment ${{ github.event.issue.number }} \
            --body "Feature implemented in PR #$(gh pr list --head feature/* --json number -q '.[0].number')"
```

### GitLab CI Pipeline

```yaml
feature-builder:
  stage: build
  script:
    - claude feature-builder "$FEATURE_REQUEST" --auto-pr
  rules:
    - if: $CI_PIPELINE_SOURCE == "trigger"
      when: always
```

## Custom Review Agents

Extend code review with specialized agents:

### Security-Focused Review

Add to Phase 3:

```markdown
## Security Agent

Focus areas:
1. Input validation and sanitization
2. Authentication/authorization flaws
3. SQL/NoSQL injection vectors
4. XSS vulnerabilities
5. Sensitive data exposure
6. Dependency vulnerabilities

Reference: OWASP Top 10

Scoring boost:
- Security issues: +20 to confidence score
```

### Performance Agent

```markdown
## Performance Agent

Focus areas:
1. N+1 query patterns
2. Missing indexes for queries
3. Unbounded data fetching
4. Memory leaks
5. Blocking operations in async code
6. Missing caching opportunities

Check for:
- Database query efficiency
- API response size
- Bundle size impact
```

### Accessibility Agent

```markdown
## Accessibility Agent

Focus areas:
1. ARIA attributes
2. Keyboard navigation
3. Color contrast
4. Screen reader support
5. Focus management
6. Alternative text

Reference: WCAG 2.1 AA
```

## Team Collaboration Patterns

### Feature Queue System

Manage multiple feature requests:

```markdown
# feature-queue.md

## Queued
1. [ ] Add user preferences (#123)
2. [ ] Implement notifications (#124)
3. [ ] Add export functionality (#125)

## In Progress
- [ ] Payment integration (#122) - @dev1

## Completed
- [x] Authentication (#121) - PR #45
```

### Review Rotation

```bash
# Assign reviewers based on expertise
/code-review --comment --assign-reviewer

# Review rules in .github/CODEOWNERS
/src/auth/** @security-team
/src/payments/** @payments-team
```

## Iteration Strategies

### Conservative (High Quality)

```bash
/feature-builder "Feature" \
  --max-iterations 30 \
  --fix-threshold 80 \
  --auto-review
```

- More iterations allowed
- Lower threshold triggers fixes
- Prioritizes correctness

### Aggressive (Fast Delivery)

```bash
/feature-builder "Feature" \
  --max-iterations 10 \
  --fix-threshold 95 \
  --auto-pr
```

- Fewer iterations
- Only critical issues trigger fixes
- Prioritizes speed

### Balanced (Default)

```bash
/feature-builder "Feature" \
  --max-iterations 20 \
  --fix-threshold 90 \
  --auto-review
```

## Error Recovery

### Ralph Loop Stuck

```bash
# Check current state
cat .claude/.ralph-loop.local.md

# Cancel and restart with adjusted criteria
/cancel-ralph
/ralph-loop "Simplified prompt with achievable goals" --max-iterations 10
```

### Review Loop

If code review keeps finding issues:

```bash
# After 3 fix iterations, escalate
if [ $FIX_ITERATIONS -ge 3 ]; then
  echo "Manual review required - see PR comments"
  gh pr edit --add-label "needs-human-review"
fi
```

### Partial Completion

Save progress even if not fully complete:

```bash
# Commit current progress
git add -A
git commit -m "WIP: [feature] - partial implementation"

# Create draft PR
gh pr create --draft --title "WIP: [Feature]" --body "Partial implementation, needs manual completion"
```

## Monitoring & Metrics

### Track Feature Builder Performance

```bash
# Log iteration counts
echo "$(date),${FEATURE},${ITERATIONS},${REVIEW_ISSUES}" >> ~/.feature-builder/metrics.csv

# Average iterations per feature
awk -F',' '{sum+=$3; count++} END {print sum/count}' ~/.feature-builder/metrics.csv
```

### Review Quality Metrics

```bash
# Track false positive rate
# (Issues marked "won't fix" / total issues)

# Track fix success rate
# (Issues resolved in first fix iteration / total issues)
```

## Integration with Other Skills

### With PDF Skill

```bash
# Generate technical documentation
/feature-builder "Add invoice generation" --auto-pr

# Then use PDF skill for output
/pdf create "Invoice template with dynamic fields"
```

### With DOCX Skill

```bash
# Generate feature spec document
/feature-builder "Design user dashboard" --plan-only

# Export plan to Word
/docx create "feature-spec.docx" from plan.md
```
