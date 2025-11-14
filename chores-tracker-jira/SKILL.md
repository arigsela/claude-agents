---
name: chores-tracker-jira-tracker
description: Track Jira tickets deployed to production for chores-tracker services by correlating GitHub commits with GitOps deployment PRs
---

# Chores Tracker Jira Ticket Tracker

## Overview

This Skill enables product managers to query and track Jira tickets that were deployed to production for the chores-tracker services. It works by:

1. Querying the GitOps repository (artemishealth/deployments or arigsela/kubernetes for testing) for merged deployment PRs within a date range
2. Extracting the deployed service version from deployment manifest updates
3. Finding the corresponding Git tag in the chores-tracker service repository
4. Querying commits between the previous and current version tags
5. Extracting Jira ticket IDs from commit messages using configured regex patterns
6. Returning a consolidated list of deployed tickets

## When to Use This Skill

Use this Skill when you need to:
- Find all Jira tickets deployed for chores-tracker in a specific date range
- Understand what ticket work made it into a specific service version
- Generate deployment reports with ticket information
- Verify that specific tickets were deployed to production
- Track which tickets were deployed between two dates for release notes

## How to Query

### Basic Date Range Query
```
Show me Jira tickets deployed for chores-tracker between January 1 and January 31, 2025
```

### Specific Version Query
```
What Jira tickets were included in chores-tracker v1.2.4?
```

### Recent Deployments
```
Show me the last 5 deployments of chores-tracker-backend with their Jira tickets
```

## Implementation Details

### Step 1: Query GitOps Repository for Deployment PRs

Query the GitOps repository (configured in `config.json`) for merged pull requests within the requested date range:

- Repository: Uses `gitops_repo` from config
- State: MERGED
- Base branch: main or master
- Date filter: PR merged date between start_date and end_date
- Filter by PR title pattern matching the service name

**GitHub MCP Query Pattern**:
```
Query merged PRs in {gitops_repo} 
where title matches pattern: "chore: update {service_name} to"
and mergedAt is between {start_date} and {end_date}
sorted by mergedAt descending
```

### Step 2: Extract Version from Deployment PR

From each PR identified in Step 1, extract the deployed version by:

1. Parsing the PR title using patterns configured in `config.json` under `pr_title_patterns`
2. Example patterns:
   - `chore: update chores-tracker-backend to v(\d+\.\d+\.\d+)`
   - `update .* to (v?[\d.]+)`

Expected result: Version string like `v1.2.3` or `1.2.3`

### Step 3: Query Service Repository for Commits Between Tags

For each version found:

1. Query the service repository (configured in `config.json` under `service_repo`)
2. Find the Git tag corresponding to the version (e.g., `v1.2.3`)
3. Get the previous tag using git tag sorting by commit date
4. Query all commits between `{previous_tag}..{current_tag}`
5. Sort commits by committed date ascending

**GitHub MCP Query Pattern**:
```
Get commits in {service_repo} 
between tags: {previous_tag}..{current_tag}
Return: commit SHA, message, author, committedDate
```

### Step 4: Extract Jira Tickets from Commit Messages

For each commit message retrieved:

1. Apply regex patterns configured in `config.json` under `jira_patterns`
2. Default patterns to try:
   - `\[([A-Z]+-\d+)\]` - Bracket notation: [PROJ-1234]
   - `\b([A-Z]+-\d+)\b` - Standalone: PROJ-1234
   - `Jira:\s*([A-Z]+-\d+)` - Prefix notation: Jira: PROJ-1234

3. Extract all matching ticket IDs from each commit message
4. Deduplicate tickets globally
5. For each ticket, track:
   - Ticket ID
   - Version it was deployed in
   - Deployment date (from GitOps PR merge date)
   - Commit message for context

### Step 5: Format and Return Results

Return results grouped by deployment version with:

```
# Jira Tickets Deployed for {service_name}
**Date Range**: {start_date} to {end_date}

## Summary
- Total Deployments: X
- Total Unique Tickets: Y
- Deployment Versions: [list]

## Deployments (ordered by date)

### Version {version} (Deployed: {date})
**GitOps PR**: #{pr_number}
**Commits**: X
**Tickets**:
- PROJ-1234
- PROJ-5678

### Version {version} (Deployed: {date})
...

## All Unique Tickets (Sorted by First Deployment)
1. PROJ-1234 - Deployed in v1.2.3 (2025-01-15)
2. PROJ-5678 - Deployed in v1.2.3 (2025-01-15)
...
```

## Configuration

This Skill uses a `config.json` file in the same directory to define service-specific settings:

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
  "jira_patterns": [
    "\\[([A-Z]+-\\d+)\\]",
    "\\b([A-Z]+-\\d+)\\b",
    "Jira:\\s*([A-Z]+-\\d+)"
  ],
  "pr_title_patterns": [
    "update chores-tracker-backend to (v?[0-9.]+)",
    "chore: update chores-tracker-backend to (v?[0-9.]+)"
  ]
}
```

## Edge Cases and Error Handling

**No Deployments in Date Range**
- If no GitOps PRs are found, respond: "No deployments found for {service_name} between {start_date} and {end_date}"

**No Jira Tickets Found**
- If commits have no Jira ticket references, respond: "The {version} deployment included X commits but no Jira ticket references were found in commit messages"

**Version Not Found**
- If a version tag cannot be found in the service repository, note this: "⚠️ Could not locate tag {version} in repository. Version may have been force-pushed or deleted."

**Large Date Ranges**
- If the query spans many deployments (>20), summarize: "Found X deployments in this range. Showing first 20; use more specific date ranges for detailed view."

**Missing Configuration**
- If required config fields are missing, respond: "Skill not properly configured. Please ensure config.json contains: service_name, service_repo, gitops_repo"

## Example Results

### Query: "Show me Jira tickets deployed for chores-tracker between January 1 and January 31, 2025"

```
# Jira Tickets Deployed: chores-tracker-backend
**Date Range**: 2025-01-01 to 2025-01-31

## Summary
- **Total Deployments**: 3
- **Total Unique Tickets**: 10

## Deployments

### v1.2.3 (Deployed: 2025-01-15)
**GitOps PR**: #123
**Tickets**:
- PROJ-1234: Fix login authentication bug
- PROJ-1235: Add password reset functionality  
- PROJ-1240: Update user profile endpoint

### v1.2.4 (Deployed: 2025-01-22)
**GitOps PR**: #128
**Tickets**:
- PROJ-1245: Implement rate limiting
- PROJ-1246: Fix database connection pooling
- PROJ-1248: Add health check endpoint
- PROJ-1250: Update dependencies

### v1.2.5 (Deployed: 2025-01-29)
**GitOps PR**: #135
**Tickets**:
- PROJ-1255: Performance optimization for queries
- PROJ-1260: Add logging improvements

## All Unique Tickets
1. PROJ-1234 - Deployed in v1.2.3
2. PROJ-1235 - Deployed in v1.2.3
3. PROJ-1240 - Deployed in v1.2.3
4. PROJ-1245 - Deployed in v1.2.4
5. PROJ-1246 - Deployed in v1.2.4
6. PROJ-1248 - Deployed in v1.2.4
7. PROJ-1250 - Deployed in v1.2.4
8. PROJ-1255 - Deployed in v1.2.5
9. PROJ-1260 - Deployed in v1.2.5
```

## GitHub MCP Server Requirements

This Skill requires access to the GitHub MCP Server with permissions to:

- Query pull requests in GitOps repository (arigsela/kubernetes)
- Query commits in service repository (arigsela/chores-tracker)
- Query Git tags and releases in service repository
- List and search GitHub repositories and their content

## Limitations and Future Enhancements

**Current Limitations**:
- Queries are limited to repositories accessible via GitHub MCP Server
- Jira ticket extraction depends on consistent commit message formatting
- Large date ranges (>6 months) may result in rate limiting
- Cannot access Jira details (status, assignee, etc.) without Jira MCP Server

**Future Enhancements**:
- Integration with Jira MCP Server for ticket details (status, assignee, epic, sprint)
- Caching of frequently queried version ranges
- Multi-service queries with consolidated reports
- Filtering by Jira project, assignee, or custom fields
- Export to CSV/JSON for reporting and analysis
- Commit author attribution and contribution tracking

## Quick Reference

**Most Common Queries**:
1. "Show me all Jira tickets deployed in [month] [year]"
2. "What tickets are in version [version]?"
3. "Show me the last [number] deployments"
4. "Compare Jira tickets between [version A] and [version B]"

**Tips**:
- Use specific date ranges for faster queries
- Include both backend and frontend in multi-service queries
- Check commit messages in the service repository if tickets aren't found
- Verify PR titles in GitOps repository match expected pattern

## Support and Troubleshooting

**Skill Not Detected**:
- Verify `config.json` exists in the skill directory
- Check that SKILL.md has proper YAML frontmatter (starts with `---`)
- Restart Claude Desktop after adding skill

**GitHub MCP Connection Issues**:
- Verify GitHub MCP Server is configured in Claude Desktop settings
- Test GitHub access: "Can you list recent commits in arigsela/chores-tracker?"
- Check GitHub API rate limits

**No Results Found**:
- Verify date range overlaps with actual deployments
- Check that PR title pattern matches actual GitOps PRs
- Verify Jira ticket format in commit messages matches regex patterns
