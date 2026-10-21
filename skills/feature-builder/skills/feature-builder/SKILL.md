---
name: feature-builder
description: Automated end-to-end feature development using Ralph Loop for iterative implementation and AI code review for quality assurance. Use when the user asks to build, implement, create, develop, or add any feature, component, endpoint, module, or functionality to a codebase. Triggers on requests like "build me X", "implement X", "create a new X", "develop X", "add X feature", "I need X functionality", "can you build X", "help me implement X", "set up X", or any request to write substantial new code that benefits from iterative development with automated review. Also use for refactoring requests, adding tests, or any multi-step development task.
version: "1.0.0"
author:
  name: "Arisela"
tags: [feature-development, automation, iterative, code-generation, testing]
category: development
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
requires:
  tools: [git]
  skills: [code-review]
---

# Feature Builder

Orchestrates complete feature development through three integrated phases: Planning → Implementation (Ralph Loop) → Code Review. Combines iterative AI development with automated quality checks.

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    FEATURE BUILDER                          │
├─────────────────────────────────────────────────────────────┤
│  Phase 1: PLANNING                                          │
│  ├─ Analyze requirements                                    │
│  ├─ Explore codebase                                        │
│  ├─ Create implementation plan                              │
│  └─ Generate PROMPT.md for Ralph                            │
├─────────────────────────────────────────────────────────────┤
│  Phase 2: IMPLEMENTATION (Ralph Loop)                       │
│  ├─ Execute iterative development                           │
│  ├─ Run tests each iteration                                │
│  ├─ Self-correct based on failures                          │
│  └─ Exit on completion promise                              │
├─────────────────────────────────────────────────────────────┤
│  Phase 3: CODE REVIEW                                       │
│  ├─ Run parallel review agents                              │
│  ├─ Check CLAUDE.md compliance                              │
│  ├─ Detect bugs in changes                                  │
│  └─ Create PR with review comments                          │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Full automated pipeline
/feature-builder "Add user authentication with JWT tokens"

# With options
/feature-builder "Add dark mode toggle" --max-iterations 15 --auto-pr

# Planning only (review before execution)
/feature-builder "Refactor payment module" --plan-only
```

## Phase 1: Planning

### Step 1.1: Analyze Requirements

Parse the feature request to identify:
- **Core functionality**: What must the feature do?
- **Acceptance criteria**: How do we know it's done?
- **Dependencies**: What existing code/systems does it touch?
- **Constraints**: Performance, security, compatibility requirements

### Step 1.2: Explore Codebase

Before planning, understand the existing architecture:

```bash
# Find relevant patterns
find . -name "*.ts" -o -name "*.tsx" | head -30

# Search for similar implementations
grep -r "authentication\|auth\|login" --include="*.ts" -l

# Check CLAUDE.md guidelines
find . -name "CLAUDE.md" | xargs cat
```

### Step 1.3: Create Implementation Plan

Structure the plan with clear tasks:

```markdown
## Feature: [Feature Name]

### Tasks
1. [ ] Create data models/types
2. [ ] Implement core logic
3. [ ] Add API endpoints/handlers
4. [ ] Write unit tests
5. [ ] Add integration tests
6. [ ] Update documentation

### Success Criteria
- All tests pass
- No TypeScript errors
- Follows CLAUDE.md guidelines
- Feature works end-to-end
```

### Step 1.4: Generate Ralph Prompt

Create a structured prompt for Ralph Loop:

```markdown
# PROMPT.md

## Objective
[Clear, specific goal]

## Context
[Relevant codebase information]

## Requirements
1. [Requirement 1]
2. [Requirement 2]
...

## Constraints
- Follow existing patterns in src/
- Maintain backwards compatibility
- All tests must pass

## Completion
When ALL requirements are met and tests pass, output:
<promise>FEATURE COMPLETE</promise>
```

## Phase 2: Implementation (Ralph Loop)

### Starting Ralph Loop

```bash
/ralph-loop "[Implementation prompt]" --max-iterations 20 --completion-promise "FEATURE COMPLETE"
```

### Ralph Loop Behavior

Each iteration:
1. Claude receives the PROMPT.md
2. Makes incremental progress on implementation
3. Runs tests to verify changes
4. Sees previous work in files/git
5. Self-corrects based on failures
6. Outputs `<promise>FEATURE COMPLETE</promise>` when done

### Monitoring Progress

Track iteration progress:
- File changes per iteration
- Test results
- Error patterns
- Completion indicators

### Exit Conditions

Ralph exits when:
- Completion promise detected (`<promise>FEATURE COMPLETE</promise>`)
- Max iterations reached
- Manual cancellation (`/cancel-ralph`)

## Phase 3: Code Review

### Automatic Review Trigger

After Ralph completes, automatically run code review:

```bash
# Create branch and commit
git checkout -b feature/[feature-name]
git add -A
git commit -m "feat: [feature description]"

# Push and create PR
git push -u origin feature/[feature-name]
gh pr create --title "[Feature Title]" --body "[Generated description]"

# Run code review
/code-review --comment
```

### Review Integration

The code-review skill runs 4 parallel agents:
1. **CLAUDE.md Compliance** (x2) - Check guideline adherence
2. **Bug Detection** - Scan for issues in new code
3. **History Analysis** - Context from git history

Issues scored 80+ are posted as PR comments.

### Review-Driven Iteration

If significant issues found (score 90+):

```bash
# Re-enter Ralph Loop with fixes
/ralph-loop "Fix code review issues: [issues list]" --max-iterations 5 --completion-promise "FIXES COMPLETE"
```

## Configuration

### Feature Builder Options

| Option | Description | Default |
|--------|-------------|---------|
| `--max-iterations` | Max Ralph iterations | 20 |
| `--completion-promise` | Custom completion phrase | "FEATURE COMPLETE" |
| `--plan-only` | Stop after planning phase | false |
| `--auto-pr` | Auto-create PR after completion | false |
| `--auto-review` | Auto-run code review | true |
| `--fix-threshold` | Re-iterate if issues >= score | 90 |

### Prompt Templates

See [references/prompt-templates.md](references/prompt-templates.md) for:
- Feature implementation prompts
- Bug fix prompts
- Refactoring prompts
- Test writing prompts

## Best Practices

### Good Feature Requests

```
✓ "Add JWT authentication with refresh tokens, following the existing auth patterns in src/auth/"

✓ "Implement dark mode toggle that persists user preference to localStorage"

✓ "Add pagination to the /api/users endpoint with limit/offset parameters"
```

### Poor Feature Requests

```
✗ "Make the app better" (too vague)

✗ "Add everything for user management" (too broad)

✗ "Fix bugs" (no specific criteria)
```

### Completion Promises

Write clear, verifiable promises:

```markdown
## Good
<promise>FEATURE COMPLETE</promise>
- Only output when ALL tests pass
- Only output when feature works end-to-end

## Better (with checklist)
When complete:
- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] No TypeScript errors
- [ ] Follows CLAUDE.md
Then output: <promise>FEATURE COMPLETE</promise>
```

## Workflow Examples

### Example 1: API Endpoint

```bash
/feature-builder "Add GET /api/users/:id endpoint that returns user profile with proper error handling" --auto-pr
```

**Phase 1 produces:**
```markdown
# PROMPT.md
## Objective
Implement GET /api/users/:id endpoint

## Tasks
1. Add route handler in src/routes/users.ts
2. Create getUserById service function
3. Add input validation for user ID
4. Handle 404 for non-existent users
5. Add unit tests
6. Add integration test

## Completion
<promise>FEATURE COMPLETE</promise>
```

**Phase 2:** Ralph iterates until tests pass
**Phase 3:** PR created with AI review

### Example 2: UI Component

```bash
/feature-builder "Create a reusable Modal component with accessibility support" --max-iterations 15
```

### Example 3: Refactoring

```bash
/feature-builder "Refactor the authentication module to use the repository pattern" --plan-only
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Ralph stuck in loop | Check if completion criteria are achievable; add `--max-iterations` |
| Tests keep failing | Review test requirements; may need manual intervention |
| Review finds many issues | Lower `--fix-threshold` or address issues manually |
| Planning phase unclear | Provide more specific feature requirements |

## Advanced Usage

See [references/advanced-workflows.md](references/advanced-workflows.md) for:
- Multi-feature pipelines
- CI/CD integration
- Custom review agents
- Team collaboration patterns
