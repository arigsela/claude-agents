# Prompt Templates

Ready-to-use templates for common development scenarios.

## Feature Implementation

### Basic Feature

```markdown
# PROMPT.md

## Objective
Implement [FEATURE_NAME]: [one-line description]

## Context
- Project uses [FRAMEWORK/LANGUAGE]
- Existing patterns in [RELEVANT_DIRS]
- Must follow guidelines in CLAUDE.md

## Requirements
1. [Functional requirement 1]
2. [Functional requirement 2]
3. [Non-functional requirement]

## Acceptance Criteria
- [ ] Feature works as specified
- [ ] Unit tests written and passing
- [ ] No linter errors
- [ ] Follows existing code patterns

## Constraints
- Do not modify [PROTECTED_FILES]
- Maintain backwards compatibility
- Keep changes focused on the feature

## Completion
When ALL acceptance criteria are met, output:
<promise>FEATURE COMPLETE</promise>
```

### API Endpoint

```markdown
# PROMPT.md

## Objective
Implement [METHOD] [ENDPOINT] endpoint

## Requirements
1. Create route handler in [routes file]
2. Implement service function for business logic
3. Add input validation
4. Handle error cases (400, 404, 500)
5. Return proper response format

## Request/Response
**Request:**
- Method: [GET/POST/PUT/DELETE]
- Path: [/api/resource/:id]
- Body: [schema if applicable]

**Response:**
- Success: [200/201] with [response schema]
- Error: [4xx/5xx] with error message

## Tests Required
- [ ] Success case
- [ ] Invalid input (400)
- [ ] Not found (404)
- [ ] Server error handling

## Completion
<promise>FEATURE COMPLETE</promise>
```

### UI Component

```markdown
# PROMPT.md

## Objective
Create [COMPONENT_NAME] component

## Requirements
1. Create component in [components directory]
2. Support props: [list props]
3. Handle states: [loading, error, success]
4. Accessibility: [ARIA requirements]

## Design Specs
- [Visual/behavior specifications]
- [Responsive breakpoints if any]

## Tests Required
- [ ] Renders without crashing
- [ ] Props work correctly
- [ ] User interactions work
- [ ] Accessibility passes

## Completion
<promise>FEATURE COMPLETE</promise>
```

## Bug Fix

```markdown
# PROMPT.md

## Objective
Fix: [Bug description]

## Current Behavior
[What happens now]

## Expected Behavior
[What should happen]

## Root Cause Analysis
1. Investigate [suspected area]
2. Check [related files]
3. Identify the actual cause

## Fix Requirements
- [ ] Identify root cause
- [ ] Implement minimal fix
- [ ] Add regression test
- [ ] Verify fix doesn't break other features

## Constraints
- Minimal changes only
- Do not refactor unrelated code
- Add test for the specific bug

## Completion
<promise>BUG FIXED</promise>
```

## Refactoring

```markdown
# PROMPT.md

## Objective
Refactor [TARGET] to [NEW_PATTERN/APPROACH]

## Current State
[Description of current implementation]

## Target State
[Description of desired implementation]

## Refactoring Steps
1. [Step 1: e.g., Create new abstraction]
2. [Step 2: e.g., Migrate consumers]
3. [Step 3: e.g., Remove old code]

## Requirements
- [ ] All existing tests still pass
- [ ] No functional changes
- [ ] Improved [metric: readability/performance/etc]
- [ ] New pattern documented

## Constraints
- Incremental changes (commit after each step)
- Keep backwards compatibility during migration
- No feature changes

## Completion
<promise>REFACTOR COMPLETE</promise>
```

## Test Writing

```markdown
# PROMPT.md

## Objective
Add tests for [MODULE/FEATURE]

## Test Coverage Goals
- Unit tests for [functions/classes]
- Integration tests for [workflows]
- Edge case coverage

## Test Cases Required
1. [Happy path test]
2. [Error case test]
3. [Edge case test]
4. [Boundary condition test]

## Framework
- Test framework: [Jest/Pytest/etc]
- Assertion style: [expect/assert]
- Mocking approach: [jest.mock/unittest.mock]

## Completion
<promise>TESTS COMPLETE</promise>
```

## Database Migration

```markdown
# PROMPT.md

## Objective
Create migration for [CHANGE_DESCRIPTION]

## Schema Changes
- Add/modify/remove: [table/column details]

## Requirements
1. Create migration file
2. Write up migration
3. Write down migration (rollback)
4. Update models/types
5. Update affected queries

## Data Migration
[If data needs transformation]

## Verification
- [ ] Migration runs successfully
- [ ] Rollback works
- [ ] Application still works
- [ ] No data loss

## Completion
<promise>MIGRATION COMPLETE</promise>
```

## Documentation

```markdown
# PROMPT.md

## Objective
Document [FEATURE/API/MODULE]

## Documentation Required
1. Overview/purpose
2. Usage examples
3. API reference (if applicable)
4. Configuration options
5. Troubleshooting

## Format
- Location: [docs/ or README]
- Style: [Markdown/JSDoc/etc]

## Examples Required
- Basic usage example
- Advanced usage example
- Error handling example

## Completion
<promise>DOCS COMPLETE</promise>
```
