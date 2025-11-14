# Chores Tracker Jira Tickets Tracking

## What is This?

This Claude skill helps you track which Jira tickets were deployed to production for the Chores Tracker Backend service. It correlates your Git commits with deployment PRs to give you a clear picture of what shipped and when.

## How to Use

Just ask Claude natural questions about deployments! Here are examples:

### Find Tickets by Date

```
Show me Jira tickets deployed for chores-tracker in January 2025
```

```
What was deployed to chores-tracker last week?
```

```
List all chores-tracker deployments between November 1 and November 8
```

### Find Tickets by Version

```
What tickets were in chores-tracker v5.20.0?
```

```
Show me the commits in version 5.19.0
```

### Recent Activity

```
What's the latest deployment for chores-tracker?
```

```
Show me chores-tracker deployments from the last 30 days
```

## What You'll Get

Claude will return:
- **Deployment timeline**: When each version was deployed
- **Jira tickets**: All ticket IDs from commit messages
- **Commit details**: What changed in each version
- **Links**: Direct links to PRs and releases
- **Summary stats**: Total deployments, commits, and tickets

## Example Output

```markdown
# Jira Tickets Deployed: Chores Tracker Backend
**Date Range**: 2025-11-01 to 2025-11-08

## Summary
- Total Deployments: 3
- Total Commits: 8
- Unique Jira Tickets: 5

## Deployments

### v5.20.0 (Deployed: 2025-11-07)
GitOps PR: #294
Commits: 3
Jira Tickets:
- PROJ-1234: Fix login authentication bug
- PROJ-1235: Add password reset functionality
```

## Requirements

- **Claude Desktop** with this skill installed
- **GitHub MCP Server** configured and connected
- **Access** to arigsela/kubernetes and arigsela/chores-tracker repositories

## Troubleshooting

### "No Jira tickets found"

This means commits don't have Jira ticket IDs. Ask developers to include ticket references in commit messages:
- Format: `[PROJ-1234]` or `PROJ-1234:`
- Example: `fix: resolve login bug [PROJ-1234]`

### "No deployments found"

- Check your date range - deployments may be outside the period
- Verify the service name is correct
- Confirm deployments were merged to main branch

### Skill not working

1. Restart Claude Desktop
2. Check skill location: `~/.claude/skills/chores-tracker-jira/`
3. Verify GitHub MCP server is connected

## For Developers

To ensure tickets are tracked properly:

1. **Include Jira ticket IDs in commit messages**:
   ```bash
   git commit -m "fix: resolve authentication bug [PROJ-1234]"
   ```

2. **Supported formats**:
   - `[PROJ-1234]` - Bracketed (recommended)
   - `PROJ-1234:` - Colon prefix
   - `Jira: PROJ-1234` - Explicit prefix

3. **Multiple tickets**:
   ```bash
   git commit -m "feat: new feature [PROJ-1234] [PROJ-1235]"
   ```

## Support

Questions? Issues? Contact the DevOps team or check the main project documentation.

## Related Skills

- **chores-tracker-frontend-jira**: Track frontend deployments
- Other service-specific tracking skills (coming soon)

---

**Last Updated**: 2025-11-08
**Skill Version**: 1.0.0
**Maintained By**: DevOps Engineering
