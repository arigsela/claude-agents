# Chores Tracker Skill

A Claude Desktop skill for analyzing what changed in chores-tracker releases by correlating GitOps deployment history with service repository commits.

## What This Skill Does

This skill answers questions like:
- **"What commits were done for chores-tracker release v5.20.0?"**
- **"What changed between the last two deployments?"**
- **"Show me all JIRA tickets in release v5.20.0"**

It automatically:
1. Finds when the release was deployed (from GitOps repository)
2. Finds when the previous release was deployed
3. Analyzes all commits made between those deployments
4. Provides brief explanations of each commit
5. Extracts and highlights JIRA tickets from commit messages
6. Formats results with smart summaries for large releases

## Quick Start

### Installation

1. Ensure this skill directory is located at: `~/.claude/skills/chores-tracker-jira-prod/`
2. Required files:
   - `SKILL.md` - Skill instructions and metadata
   - `config.json` - Service-specific configuration
   - `README.md` - This documentation

3. Enable in Claude Desktop:
   - Open Claude Desktop
   - Go to Settings > Capabilities > Custom Skills
   - Enable "Chores Tracker"

### First Query

Try this test query:
```
What commits were done for chores-tracker release v5.20.0?
```

Expected result:
- Deployment date range
- Summary (total commits, JIRA tickets, contributors)
- Categorized commit list (Features, Fixes, etc.)
- Brief explanation for each commit
- JIRA tickets extracted from commit messages

## File Structure

```
~/.claude/skills/chores-tracker-jira-prod/
├── SKILL.md              # Main skill file (v2.0.0)
├── config.json           # Service configuration
├── README.md             # This documentation
└── Archive.zip           # Archived v1.0.0 files
```

## Configuration

The `config.json` file contains service-specific settings:

### Key Settings

**Service Identification**:
- `service_name`: Name used in GitOps PR titles (`chores-tracker-backend`)
- `service_repo`: Source code repository (`arigsela/chores-tracker`)
- `gitops_repo`: Deployment repository (`arigsela/kubernetes`)

**Pattern Matching**:
- `pr_title_patterns`: Regex to extract version from GitOps PR titles
  - Example: `"update chores-tracker-backend to (v?[0-9.]+)"`
- `jira_patterns`: Regex to extract JIRA tickets from commits
  - Example: `"\\[([A-Z]+-\\d+)\\]"` matches `[PROJ-1234]`

**Commit Categorization**:
- `commit_message_prefixes`: Patterns to categorize commits
  - `feat:`, `fix:`, `refactor:`, `perf:`, `docs:`, `test:`, `chore:`

### Example config.json

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
  "jira_patterns": [
    "\\[([A-Z]+-\\d+)\\]",
    "\\b([A-Z]+-\\d+)\\b"
  ],
  "pr_title_patterns": [
    "update chores-tracker-backend to (v?[0-9.]+)",
    "chore: update chores-tracker-backend to (v?[0-9.]+)"
  ]
}
```

## How It Works

### Workflow for: "What commits were done for chores-tracker release v5.20.0?"

```
Step 1: Find Deployment PR
    ↓
Query GitOps repo (arigsela/kubernetes) for PR deploying v5.20.0
Extract: Version (v5.20.0), Deployment Date (Date B)
    ↓
Step 2: Find Previous Deployment PR
    ↓
Query GitOps repo for most recent PR merged before Date B
Extract: Previous Version (v5.19.0), Previous Date (Date A)
    ↓
Step 3: Query Service Repo Commits
    ↓
Get all commits from arigsela/chores-tracker between Date A and Date B
    ↓
Step 4: Analyze Each Commit
    ↓
For each commit:
  - Extract JIRA ticket IDs (if present)
  - Categorize by type (feature, fix, refactor, etc.)
  - Generate brief explanation of changes
    ↓
Step 5: Format Results
    ↓
If ≤20 commits: Detailed view with all commit explanations
If >20 commits: Summary view with top highlights + grouped commits
```

### Output Formats

**Detailed View** (≤20 commits):
- Full commit list grouped by category (Features, Fixes, etc.)
- Brief explanation for every commit
- All JIRA tickets with context
- Contributor information
- GitOps PR references

**Summary View** (>20 commits):
- High-level statistics
- Top 5 features and top 5 fixes
- Grouped commit lists (first 10 per category)
- All JIRA tickets
- Note offering detailed view option

## Example Queries

### Version-Based Queries (Primary)
```
What commits were done for chores-tracker release v5.20.0?
What changed in chores-tracker v5.20.0?
Show me the release notes for chores-tracker v5.20.0
```

### Date Range Queries
```
Show me commits deployed for chores-tracker between January 1 and January 31, 2025
What was deployed last week?
```

### Recent Deployment Queries
```
Show me the last 3 deployments of chores-tracker
What are the recent chores-tracker releases?
```

## Requirements

### GitHub MCP Server
- **Required**: This skill uses the GitHub MCP Server for all queries
- **Configuration**: Must be set up in Claude Desktop settings
- **Permissions**: Read access to both repositories
  - Service repo: `arigsela/chores-tracker` (or `artemishealth/chores-tracker` for production)
  - GitOps repo: `arigsela/kubernetes` (or `artemishealth/deployments` for production)

### Rate Limits
- GitHub API: 60 req/hour (unauthenticated), 5000 req/hour (authenticated)
- Recommend authenticating GitHub MCP Server with a token

## Troubleshooting

### Skill Not Showing in Claude Desktop

1. Verify directory location: `~/.claude/skills/chores-tracker-jira-prod/`
2. Check `SKILL.md` has YAML frontmatter (starts with `---`)
3. Validate `config.json` is valid JSON
4. Restart Claude Desktop
5. Enable in Settings > Capabilities > Custom Skills

### No Results Found

**Check**:
1. Version format matches GitOps PR titles (v5.20.0 vs 5.20.0)
2. Deployment PR was merged (not just created)
3. GitHub MCP Server is connected: Test with "List recent commits in arigsela/chores-tracker"
4. PR title patterns in `config.json` match actual PR titles

**Example Verification**:
```
# Test GitHub access
List recent pull requests in arigsela/kubernetes

# Check if deployment PR exists
Show me merged PRs in arigsela/kubernetes with "chores-tracker" in the title
```

### Missing JIRA Tickets

1. Verify commit messages include JIRA ticket IDs
2. Check JIRA patterns in `config.json` match your ticket format
3. Test manually: Look at a few commit messages in GitHub

**Common JIRA formats**:
- `[PROJ-1234]` - Bracket notation (recommended)
- `PROJ-1234` - Standalone
- `Jira: PROJ-1234` - Prefix notation

### Incorrect Commit Categorization

**Fix**:
1. Update `commit_message_prefixes` in `config.json`
2. Encourage team to use conventional commit format:
   - `feat:` for features
   - `fix:` for bug fixes
   - `refactor:` for refactoring
   - `perf:` for performance improvements
   - `docs:` for documentation
   - `test:` for tests
   - `chore:` for maintenance tasks

### GitHub API Rate Limit

**Error**: "GitHub API rate limit reached"

**Solutions**:
1. Authenticate GitHub MCP Server with a personal access token
2. Wait for rate limit reset (shown in error message)
3. Use narrower date ranges to reduce API calls

## Creating Skills for Other Services

To create a similar skill for other services (e.g., `hermes`, `proteus`):

1. **Copy this skill**:
   ```bash
   cp -r ~/.claude/skills/chores-tracker-jira-prod ~/.claude/skills/hermes-jira-prod
   ```

2. **Update `config.json`**:
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
     ...
   }
   ```

3. **Update `SKILL.md` frontmatter**:
   ```yaml
   ---
   name: hermes
   description: Track commits and tickets for hermes releases
   version: 2.0.0
   dependencies: GitHub MCP Server
   ---
   ```

4. **Restart Claude Desktop** and enable the new skill

## Production Configuration

For production deployment tracking with Artemis Health repositories:

**Update `config.json`**:
```json
{
  "service_name": "chores-tracker-backend",
  "service_repo": {
    "owner": "artemishealth",
    "name": "chores-tracker"
  },
  "gitops_repo": {
    "owner": "artemishealth",
    "name": "deployments"
  },
  "deployment_manifest_path": "apps/chores-tracker-backend/deployment.yaml",
  ...
}
```

**Verify Access**:
- Ensure GitHub MCP Server has access to `artemishealth/*` repositories
- Test: "List recent commits in artemishealth/chores-tracker"

## What's New in v2.0.0

### Major Changes

1. **Version-Based Workflow** (Primary use case)
   - Query by release version: "What changed in v5.20.0?"
   - Automatically finds deployment date range
   - Compares to previous deployment

2. **Commit Explanations**
   - Brief 1-sentence explanation for every commit
   - Categorization: Features, Fixes, Refactoring, Performance, etc.
   - Contributor tracking

3. **Smart Formatting**
   - Detailed view for small releases (≤20 commits)
   - Summary view for large releases (>20 commits)
   - Top highlights extraction

4. **Deployment PR Correlation**
   - Uses actual deployment merge dates
   - Links to GitOps PRs
   - Shows time between releases

5. **Enhanced Error Handling**
   - Clear error messages
   - Troubleshooting suggestions
   - Version format flexibility

### Migration from v1.0.0

**v1.0.0 focused on**: JIRA ticket extraction from date ranges
**v2.0.0 focuses on**: Complete release analysis by version

**Old query style**:
```
Show me Jira tickets deployed between January 1 and January 31
```

**New query style** (recommended):
```
What commits were done for chores-tracker release v5.20.0?
```

Both styles still work, but version-based queries provide richer analysis.

## Support and Feedback

### Getting Help

1. Check this README troubleshooting section
2. Review `SKILL.md` for detailed workflow documentation
3. Test GitHub MCP Server connection independently
4. Verify repository access and permissions

### Common Issues

| Issue | Solution |
|-------|----------|
| Skill not appearing | Restart Claude Desktop, check file location |
| No results | Verify version format, check PR titles match patterns |
| Missing tickets | Review commit messages, verify JIRA patterns |
| Rate limiting | Authenticate GitHub MCP Server with token |
| Wrong categorization | Update commit message prefixes in config |

## Version History

- **v2.0.0** (2025-11-08): Major rewrite
  - Version-based query workflow
  - Commit explanations and categorization
  - Smart formatting (detailed vs summary)
  - Deployment PR correlation
  - Enhanced error handling

- **v1.0.0** (2025-11-08): Initial release
  - Basic JIRA ticket extraction
  - Date range queries
  - GitOps PR correlation

## Technical Notes

### Architecture

This skill is **read-only** and **stateless**:
- No credentials stored in skill files
- No repository modifications
- All queries through GitHub MCP Server
- No caching or persistence

### Performance

**Typical Query Performance**:
- Version query: 3-5 GitHub API calls
- Date range query: 5-10 GitHub API calls (depends on deployment frequency)
- Large releases (>50 commits): May take 10-15 seconds

**Optimization Tips**:
- Use specific versions instead of date ranges
- Narrow date ranges for faster results
- Authenticate GitHub MCP Server for higher rate limits

## License and Attribution

Part of the `claude-agents` repository - Learning Lab for Anthropic AI Integration Patterns.

This skill demonstrates:
- Custom Claude Skills best practices
- GitHub MCP Server integration
- Progressive disclosure design
- Intelligent output formatting
