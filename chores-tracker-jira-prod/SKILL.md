---
name: chores-tracker
description: Track commits and tickets for chores-tracker releases by analyzing GitOps deployment history and service repository commits
---

# Chores Tracker

## Overview

**Configuration**: This skill uses `config.json` in the same directory. Read this file first before processing any queries.

This skill helps you understand what changed in a chores-tracker release by:
1. Finding when the release was deployed (from GitOps repository)
2. Finding when the previous release was deployed
3. Analyzing all commits made between those two deployment dates
4. Providing brief explanations of each commit's changes
5. Extracting and highlighting any JIRA tickets referenced in commits

## Quick Start

**Most Common Query**: "What commits were done for chores-tracker release v5.20.0?"

**Expected Output**:
- Release deployment date range
- Summary statistics (total commits, features, fixes, JIRA tickets)
- Detailed commit list with explanations (or summary view if >20 commits)
- JIRA tickets extracted from commit messages

**Required Access**: GitHub MCP Server with access to service repo and GitOps repo

## When to Use This Skill

Use this skill when you need to:
- **Understand what changed in a specific release version** (e.g., v5.20.0)
- **Review all commits included in a release**
- **Find JIRA tickets associated with a release**
- **Generate release notes or deployment summaries**
- **Compare changes between deployment cycles**
- **Audit what work was deployed to production**

## How to Query

### Version-Based Query (Primary Use Case)
```
What commits were done for chores-tracker release v5.20.0?
What changed in chores-tracker v5.20.0?
Show me the release notes for chores-tracker v5.20.0
```

### Date Range Query
```
Show me commits deployed for chores-tracker between January 1 and January 31, 2025
```

### Recent Deployments
```
Show me the last 3 deployments of chores-tracker with their commits
```

## Implementation Workflow

### Primary Workflow: Version-Based Query

**Input Example**: "What commits were done for chores-tracker release v5.20.0?"

#### Step 1: Find Deployment PR for Requested Version

1. Read `config.json` to get `gitops_repo` settings
2. Query GitHub MCP Server for merged PRs in GitOps repository:
   - Repository: `{gitops_repo.owner}/{gitops_repo.name}`
   - State: MERGED
   - Base branch: main or master
   - Filter: PR title matches version using `pr_title_patterns` from config

**GitHub MCP Query Pattern**:
```
Use mcp__github__list_pull_requests:
  owner: {gitops_repo.owner}
  repo: {gitops_repo.name}
  state: closed
  sort: updated
  direction: desc

Then filter results where:
  - merged_at is not null
  - title matches pattern from pr_title_patterns
  - extracted version == requested version (v5.20.0)
```

**Extract from PR**:
- Version: v5.20.0
- Deployment Date (Date B): PR merged_at timestamp

#### Step 2: Find Previous Deployment PR

Using the same query approach, find the deployment PR that was merged immediately BEFORE Date B:

**GitHub MCP Query Pattern**:
```
Use mcp__github__list_pull_requests:
  owner: {gitops_repo.owner}
  repo: {gitops_repo.name}
  state: closed
  sort: updated
  direction: desc

Filter results where:
  - merged_at < Date B
  - title matches deployment pattern
  - Take the most recent PR (first result)
```

**Extract from PR**:
- Previous Version: (e.g., v5.19.0)
- Previous Deployment Date (Date A): PR merged_at timestamp

**Result**: Now you have Date A (previous deployment) and Date B (current deployment)

#### Step 3: Query Service Repository for Commits Between Dates

Query the service repository for all commits between Date A and Date B:

**GitHub MCP Query Pattern**:
```
Use mcp__github__list_commits:
  owner: {service_repo.owner}
  repo: {service_repo.name}
  since: Date A (ISO 8601 format)
  until: Date B (ISO 8601 format)

Return for each commit:
  - SHA (short)
  - Commit message (full)
  - Author name
  - Commit date
```

#### Step 4: Analyze Each Commit

For each commit returned:

1. **Extract JIRA Ticket** (if present):
   - Apply regex patterns from `config.json` → `jira_patterns`
   - Default patterns:
     - `\[([A-Z]+-\d+)\]` - Bracket notation: [PROJ-1234]
     - `\b([A-Z]+-\d+)\b` - Standalone: PROJ-1234
   - Store matched tickets

2. **Generate Brief Explanation**:
   - Analyze the commit message
   - Identify the type of change:
     - Feature (feat:, feature, add, implement)
     - Fix (fix:, bugfix, resolve)
     - Refactor (refactor:, cleanup, reorganize)
     - Performance (perf:, optimize, improve performance)
     - Documentation (docs:, documentation)
     - Test (test:, testing)
     - Chore (chore:, update dependencies, version bump)
   - Provide a 1-sentence explanation of what changed
   - Example: "Added user authentication with JWT tokens" or "Fixed memory leak in database connection pool"

3. **Categorize Commit**:
   - Assign to category: Features, Fixes, Refactoring, Performance, Documentation, Tests, Chores
   - Track count per category for summary

#### Step 5: Format and Return Results

**Formatting Logic**:
- **If ≤20 commits**: Show detailed view with all commits
- **If >20 commits**: Show summary view + grouped commits + option to see full details

##### Format: Detailed View (≤20 commits)

```markdown
# Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15 14:30 UTC
**Previous Release**: v5.19.0 (Deployed: 2025-01-08 10:15 UTC)
**Time Between Releases**: 7 days

## Summary
- **Total Commits**: 15
- **JIRA Tickets**: 8 unique tickets
- **Contributors**: 4 developers

### Changes by Type
- Features: 6 commits
- Fixes: 5 commits
- Refactoring: 2 commits
- Chores: 2 commits

## Detailed Commit List

### Features (6)
1. **[abc1234]** feat: Add user authentication with JWT tokens
   - **JIRA**: PROJ-1234
   - **Author**: John Doe
   - **Date**: 2025-01-10
   - **Explanation**: Implemented JWT-based authentication system for API endpoints

2. **[def5678]** Add password reset functionality
   - **JIRA**: PROJ-1235
   - **Author**: Jane Smith
   - **Date**: 2025-01-11
   - **Explanation**: Created email-based password reset flow with secure token generation

[... continue for all feature commits ...]

### Fixes (5)
1. **[ghi9012]** fix: Memory leak in database connection pool
   - **JIRA**: PROJ-1240
   - **Author**: Bob Johnson
   - **Date**: 2025-01-12
   - **Explanation**: Fixed connection pool not releasing connections properly under high load

[... continue for all fix commits ...]

### Refactoring (2)
[... continue ...]

### Chores (2)
[... continue ...]

## JIRA Tickets in This Release
1. **PROJ-1234** - JWT Authentication (feat: Add user authentication with JWT tokens)
2. **PROJ-1235** - Password Reset (Add password reset functionality)
3. **PROJ-1240** - Connection Pool Fix (fix: Memory leak in database connection pool)
[... continue for all tickets ...]

## GitOps References
- **Deployment PR**: #{pr_number} - {pr_title}
- **Previous Deployment PR**: #{prev_pr_number} - {prev_pr_title}
```

##### Format: Summary View (>20 commits)

```markdown
# Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15 14:30 UTC
**Previous Release**: v5.19.0 (Deployed: 2025-01-08 10:15 UTC)
**Time Between Releases**: 7 days

## Summary
- **Total Commits**: 47
- **JIRA Tickets**: 23 unique tickets
- **Contributors**: 8 developers

### Changes by Type
- Features: 18 commits
- Fixes: 15 commits
- Refactoring: 8 commits
- Performance: 3 commits
- Documentation: 2 commits
- Chores: 1 commit

## Key Highlights

### Major Features (Top 5)
1. **PROJ-1234** - JWT Authentication system
2. **PROJ-1240** - New reporting dashboard
3. **PROJ-1245** - Multi-tenant support
4. **PROJ-1250** - Real-time notifications
5. **PROJ-1255** - Advanced search filters

### Critical Fixes (Top 5)
1. **PROJ-1260** - Database connection pool memory leak
2. **PROJ-1265** - Race condition in payment processing
3. **PROJ-1270** - Session timeout causing data loss
4. **PROJ-1275** - Incorrect timezone handling
5. **PROJ-1280** - API rate limiting bypass vulnerability

### Performance Improvements
- Optimized database queries (3 commits)
- Reduced API response times by 40%
- Improved frontend rendering performance

## All JIRA Tickets (23)
1. PROJ-1234 - JWT Authentication
2. PROJ-1235 - Password Reset
3. PROJ-1240 - Reporting Dashboard
[... continue for all tickets ...]

## Commits by Category

### Features (18 commits)
- [abc1234] feat: Add JWT authentication - PROJ-1234
- [def5678] Add reporting dashboard - PROJ-1240
- [ghi9012] Implement multi-tenant support - PROJ-1245
[... first 10, then "... and 8 more feature commits" ...]

### Fixes (15 commits)
- [jkl3456] fix: Database connection pool leak - PROJ-1260
- [mno7890] fix: Payment processing race condition - PROJ-1265
[... first 10, then "... and 5 more fix commits" ...]

[... continue for other categories ...]

---
**Note**: This is a summary view due to the large number of commits (47).
To see detailed explanations for all commits, ask: "Show me detailed commit explanations for v5.20.0"
```

### Alternative Workflow: Date Range Query

**Input Example**: "Show me commits for chores-tracker between January 1 and January 31, 2025"

Follow the same workflow but:
- **Step 1**: Find ALL deployment PRs merged between start_date and end_date
- **Step 2**: For each deployment, extract version and merge date
- **Step 3**: Query commits between each pair of deployments
- **Step 4-5**: Same analysis and formatting approach

Group results by deployment version within the date range.

## Configuration

This skill requires `config.json` in the same directory:

```json
{
  "service_name": "chores-tracker-backend",
  "service_repo": {
    "owner": "arigsela",
    "name": "chores-tracker"
  },
  "gitops_repo": {
    "owner": "arigsela",
    "name": "kubernetes"
  },
  "deployment_manifest_path": "base-apps/chores-tracker-backend/deployments.yaml",
  "container_name": "chores-tracker",
  "jira_patterns": [
    "\\[([A-Z]+-\\d+)\\]",
    "\\b([A-Z]+-\\d+)\\b",
    "Jira:\\s*([A-Z]+-\\d+)"
  ],
  "pr_title_patterns": [
    "update chores-tracker-backend to (v?[0-9.]+)",
    "chore: update chores-tracker-backend to (v?[0-9.]+)",
    "chores-tracker-backend to (v?[0-9.]+)"
  ],
  "commit_message_prefixes": [
    "fix:", "feat:", "refactor:", "perf:",
    "docs:", "test:", "chore:"
  ],
  "github_mcp_enabled": true
}
```

### Configuration Fields

**Required**:
- `service_name`: Name of the service in GitOps PR titles
- `service_repo`: {owner, name} - Service repository containing code
- `gitops_repo`: {owner, name} - GitOps repository with deployment PRs
- `jira_patterns`: Regex patterns to extract JIRA tickets from commits
- `pr_title_patterns`: Regex patterns to extract version from GitOps PR titles

**Optional**:
- `commit_message_prefixes`: Used to categorize commits by type
- `github_mcp_enabled`: Must be true for this skill to work

## Commit Categorization Logic

Commits are categorized based on their message prefix or content:

| Category | Patterns | Examples |
|----------|----------|----------|
| **Features** | `feat:`, `feature:`, `add:`, `implement:` | "feat: Add JWT auth", "Implement new dashboard" |
| **Fixes** | `fix:`, `bugfix:`, `resolve:`, `patch:` | "fix: Memory leak", "Resolve payment bug" |
| **Refactoring** | `refactor:`, `cleanup:`, `reorganize:` | "refactor: Simplify auth logic" |
| **Performance** | `perf:`, `optimize:`, `improve:` | "perf: Cache database queries" |
| **Documentation** | `docs:`, `documentation:`, `readme:` | "docs: Update API guide" |
| **Tests** | `test:`, `testing:`, `spec:` | "test: Add auth unit tests" |
| **Chores** | `chore:`, `deps:`, `version:`, `merge:` | "chore: Update dependencies" |

Commits that don't match any pattern are categorized as "Other".

## Edge Cases and Error Handling

### Deployment PR Not Found
```
Error: Could not find deployment PR for version v5.20.0 in {gitops_repo}.

Suggestions:
- Verify the version number is correct
- Check that the deployment PR was merged (not just created)
- Ensure PR title matches one of the configured patterns:
  {list pr_title_patterns}
```

### No Previous Deployment Found
```
Warning: This appears to be the first deployment of chores-tracker.

Showing all commits from repository creation to v5.20.0 deployment.
```

### No Commits Between Deployments
```
Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15
**Previous Release**: v5.19.0 (Deployed: 2025-01-15 09:00 UTC)

## Result
No commits were made between v5.19.0 and v5.20.0 (same day deployments).
This was likely a re-deployment or configuration-only change.
```

### Version Format Mismatch
If the version format doesn't match expected patterns (v5.20.0 vs 5.20.0):
- Try both formats when querying
- Normalize version strings by adding/removing 'v' prefix as needed

### GitHub API Rate Limiting
```
Error: GitHub API rate limit reached.

Current usage: X/Y requests remaining
Resets at: {timestamp}

Suggestion: Wait for rate limit reset or authenticate GitHub MCP Server with a token for higher limits (5000 req/hour).
```

### Large Commit Count (>100)
For very large releases with >100 commits:
- Show summary view by default
- Provide top 10 for each category
- Offer to show full details if requested
- Consider suggesting narrower date ranges

## Example Queries and Expected Results

### Example 1: Version-Based Query

**Query**: "What commits were done for chores-tracker release v5.20.0?"

**Expected Output** (assuming 12 commits):
```markdown
# Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15 14:30 UTC
**Previous Release**: v5.19.0 (Deployed: 2025-01-08 10:15 UTC)
**Time Between Releases**: 7 days

## Summary
- **Total Commits**: 12
- **JIRA Tickets**: 6 unique tickets
- **Contributors**: 3 developers

### Changes by Type
- Features: 5 commits
- Fixes: 4 commits
- Refactoring: 2 commits
- Chores: 1 commit

[... detailed commit list as shown in Format section ...]
```

### Example 2: Date Range Query

**Query**: "Show me commits for chores-tracker between January 1 and January 15, 2025"

**Expected Output** (assuming 3 deployments):
```markdown
# Deployment History: chores-tracker
**Date Range**: 2025-01-01 to 2025-01-15

## Summary
- **Total Deployments**: 3
- **Total Commits**: 28
- **Total JIRA Tickets**: 15

## Deployments

### v5.20.0 (Deployed: 2025-01-15)
- Commits: 12
- JIRA Tickets: 6
- [View detailed breakdown]

### v5.19.0 (Deployed: 2025-01-10)
- Commits: 10
- JIRA Tickets: 5
- [View detailed breakdown]

### v5.18.0 (Deployed: 2025-01-03)
- Commits: 6
- JIRA Tickets: 4
- [View detailed breakdown]

[... can expand each deployment with full commit details ...]
```

## GitHub MCP Server Requirements

This skill requires:
- **GitHub MCP Server** configured and enabled
- **Permissions**:
  - Read access to GitOps repository (arigsela/kubernetes or artemishealth/deployments)
  - Read access to service repository (arigsela/chores-tracker or artemishealth/chores-tracker)
  - Ability to list pull requests
  - Ability to list commits with date filtering
  - Ability to read PR details (title, merge date, etc.)

## Tips for Best Results

1. **Use specific version numbers**: "v5.20.0" is better than "latest release"
2. **Check version format**: Some repos use `v5.20.0`, others use `5.20.0`
3. **Narrow date ranges**: Shorter ranges = faster queries and more detailed results
4. **Request specific details**: Ask for "detailed view" if you want all commit explanations
5. **Verify repository access**: Test with "List recent commits in arigsela/chores-tracker" first

## Troubleshooting

### Skill Not Working

**Before processing queries, validate**:
1. `config.json` exists and is valid JSON
2. Required fields are present: `service_name`, `service_repo`, `gitops_repo`
3. GitHub MCP Server is connected: Test with a basic GitHub query
4. Repository access: Verify you can read both service and GitOps repos

### No Results Returned

**Check**:
1. Version number format matches GitOps PR titles
2. PR title patterns in config.json match actual PR naming convention
3. Deployment PR was actually merged (not just opened)
4. Date range overlaps with actual deployments

### Missing JIRA Tickets

**Verify**:
1. Commit messages include JIRA ticket IDs
2. JIRA patterns in config.json match your ticket format
3. Check a few commit messages manually to confirm format

### Incorrect Commit Categorization

**Adjust**:
1. Update `commit_message_prefixes` in config.json
2. Ensure commits use conventional commit format (feat:, fix:, etc.)

## Version History

- **v2.0.0** (2025-11-08): Major rewrite
  - Changed primary workflow to version-based queries
  - Added commit explanation generation
  - Added smart formatting (detailed vs summary views)
  - Changed date comparison to use deployment PR merge dates
  - Added commit categorization logic
  - Improved error handling and edge cases

- **v1.0.0** (2025-11-08): Initial release
  - Basic JIRA ticket extraction from commits
  - GitOps PR correlation
  - Date range filtering
