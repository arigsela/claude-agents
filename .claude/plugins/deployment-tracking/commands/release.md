---
name: release
description: Analyze commits and JIRA tickets for a service release deployment
---

# Release Analysis Command

Quickly analyze what changed in a service release by querying deployment history and commit logs.

## Usage

```bash
/release <service> <version|date-range|latest>
```

## Parameters

### `<service>` (required)
The service name to analyze. Must match a configured skill.

**Available services:**
- `chores-tracker` - Chores Tracker service
- (Add more services by creating skills in `skills/` directory)

**Examples:**
- `chores-tracker`
- `hermes`
- `proteus`

### `<version|date-range|latest>` (required)
What to analyze:

**Version-based:**
- `v5.20.0` - Specific version
- `5.20.0` - Version without 'v' prefix (will be normalized)

**Date range:**
- `last-week` - Past 7 days
- `last-month` - Past 30 days
- `yesterday` - Previous day
- `2025-01-01..2025-01-31` - Custom date range

**Special:**
- `latest` - Most recent deployment
- `recent` - Last 3 deployments

## Examples

### Basic Version Query
```bash
/release chores-tracker v5.20.0
```

Analyzes:
- Commits between v5.19.0 (previous) and v5.20.0 (current)
- JIRA tickets extracted from commits
- Categorized by type (features, fixes, etc.)
- Brief explanation for each commit

**Output:**
```
# Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15 14:30 UTC
**Previous Release**: v5.19.0 (2025-01-08)
**Time Between Releases**: 7 days

## Summary
- Total Commits: 15
- JIRA Tickets: 8
- Contributors: 4

### Features (6 commits)
1. [abc1234] feat: Add JWT authentication - PROJ-1234
   Explanation: Implemented JWT-based auth...

[... detailed commit list ...]
```

### Latest Release
```bash
/release chores-tracker latest
```

Finds the most recent deployment and analyzes it.

### Date Range Query
```bash
/release chores-tracker last-week
```

Shows all deployments in the past 7 days with commit analysis.

### Multiple Recent Deployments
```bash
/release chores-tracker recent
```

Shows the last 3 deployments with summaries.

## How It Works

1. **Parse Command**: Extract service name and query parameters
2. **Invoke Agent**: Call the `release-analyzer` agent
3. **Service Discovery**: Check if service skill exists
4. **Delegate to Skill**: Invoke service-specific skill (e.g., `chores-tracker`)
5. **Format Results**: Present analysis in user-friendly format

## Output Formats

### Detailed View (≤20 commits)
- Full commit list with explanations
- All JIRA tickets with context
- Categorized by type
- Contributor breakdown

### Summary View (>20 commits)
- High-level statistics
- Top 5 features and fixes
- Grouped commits (first 10 per category)
- All JIRA tickets

## Error Handling

### Service Not Found
```
Error: Service 'hermes' is not configured.

Available services:
- chores-tracker

To add hermes, create: .claude/plugins/deployment-tracking/skills/hermes/
```

### Version Not Found
```
Error: Could not find deployment PR for chores-tracker v5.20.0.

Suggestions:
- Check version format (try 5.20.0 without 'v')
- Verify deployment was merged
- Try: /release chores-tracker latest
```

### GitHub Rate Limiting
```
Error: GitHub API rate limit reached.

Current: 0/60 requests remaining
Resets at: 2:30 PM EST

Solutions:
1. Wait 30 minutes
2. Authenticate GitHub MCP Server with token
3. Use narrower date ranges
```

## Advanced Options

### Flags (Future Enhancement)

```bash
# Detailed view regardless of commit count
/release chores-tracker v5.20.0 --detailed

# Summary view even for small releases
/release chores-tracker v5.20.0 --summary

# Filter by author
/release chores-tracker v5.20.0 --author=john.doe

# Export to file
/release chores-tracker v5.20.0 --export=release-notes.md

# Show only tickets
/release chores-tracker v5.20.0 --tickets-only
```

## Adding New Services

To add a new service to track:

1. **Create skill directory:**
   ```bash
   mkdir .claude/plugins/deployment-tracking/skills/hermes
   ```

2. **Copy template files:**
   ```bash
   cp skills/chores-tracker/SKILL.md skills/hermes/
   cp skills/chores-tracker/config.json skills/hermes/
   ```

3. **Update `config.json`:**
   ```json
   {
     "service_name": "hermes-backend",
     "service_repo": {
       "owner": "artemishealth",
       "name": "hermes"
     },
     "gitops_repo": {
       "owner": "artemishealth",
       "name": "deployments"
     },
     "pr_title_patterns": [
       "update hermes-backend to (v?[0-9.]+)"
     ],
     ...
   }
   ```

4. **Update `SKILL.md` frontmatter:**
   ```yaml
   ---
   name: hermes
   description: Track commits and tickets for hermes releases
   ---
   ```

5. **Test the new service:**
   ```bash
   /release hermes latest
   ```

## Integration with Agent

This command invokes the `release-analyzer` agent, which:
1. Discovers available services
2. Validates service exists
3. Parses query parameters
4. Delegates to service-specific skill
5. Formats and presents results

The command provides a **convenient CLI interface** while the agent handles **orchestration logic**.

## Requirements

- **GitHub MCP Server**: Must be configured and authenticated
- **Repository Access**: Read access to service and GitOps repositories
- **Service Skills**: At least one service skill must be configured

## Tips for Best Results

1. **Use specific versions** when possible: `v5.20.0` vs `latest`
2. **Check version format** if query fails: try with/without 'v' prefix
3. **Use date ranges** for historical analysis
4. **Authenticate GitHub MCP** for higher rate limits (5000 req/hour vs 60)
5. **Add services incrementally** - start with one, add more as needed

## Troubleshooting

### Command Not Found
```
Ensure the plugin is installed:
- Plugin location: .claude/plugins/deployment-tracking/
- Command file: commands/release.md
- Restart Claude Code if needed
```

### GitHub MCP Not Available
```
Test GitHub access:
List recent commits in arigsela/chores-tracker

If this fails, configure GitHub MCP Server in Claude Code settings.
```

### Slow Queries
```
Large releases (>50 commits) may take 10-15 seconds.

To speed up:
1. Use narrower date ranges
2. Request summary view
3. Authenticate GitHub MCP for better rate limits
```

## Examples Gallery

### Scenario 1: Check Latest Production Deployment
```bash
/release chores-tracker latest
```
Use when: You want to know what's currently in production

### Scenario 2: Generate Release Notes
```bash
/release chores-tracker v5.20.0 --detailed
```
Use when: Creating release notes for stakeholders

### Scenario 3: Track Ticket Deployment
```bash
/release chores-tracker last-month
```
Then search output for specific JIRA ticket ID
Use when: PM asks "When did PROJ-1234 get deployed?"

### Scenario 4: Compare Releases
```bash
/release chores-tracker v5.20.0
/release chores-tracker v5.19.0
```
Compare the outputs side-by-side
Use when: Investigating regression between versions

### Scenario 5: Weekly Deployment Report
```bash
/release chores-tracker last-week
```
Use when: Preparing weekly team update

## Related Documentation

- **Release Analyzer Agent**: `agents/release-analyzer.md`
- **Chores Tracker Skill**: `skills/chores-tracker/SKILL.md`
- **Adding Services**: See "Adding New Services" section above
- **GitHub MCP Setup**: Claude Code documentation

## Support

If you encounter issues:
1. Check error messages for suggestions
2. Verify GitHub MCP Server is connected
3. Test repository access manually
4. Review service configuration in `config.json`
5. Check that deployment PRs match expected title patterns
