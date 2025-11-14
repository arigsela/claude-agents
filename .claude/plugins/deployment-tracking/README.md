# Deployment Tracking Plugin

Track releases, commits, and JIRA tickets across deployed services by analyzing GitOps deployment history and correlating with service repository commits.

## What This Plugin Does

This plugin helps you answer:
- **"What changed in the latest release?"**
- **"Which JIRA tickets were deployed last week?"**
- **"Show me commits between v5.20.0 and v5.19.0"**
- **"Generate release notes for the current deployment"**

It automatically:
1. Finds when releases were deployed (from GitOps repository)
2. Identifies commits included in each release
3. Extracts JIRA tickets from commit messages
4. Categorizes commits by type (features, fixes, refactors, etc.)
5. Provides brief explanations for each commit
6. Formats results intelligently (detailed vs summary)

## Quick Start

### Installation

This plugin is already installed in your local `.claude/plugins/` directory.

### Usage

**Option 1: Slash Command (Recommended)**
```bash
/release chores-tracker v5.20.0
/release chores-tracker latest
/release chores-tracker last-week
```

**Option 2: Natural Language**
```
What commits were done for chores-tracker release v5.20.0?
Show me the latest chores-tracker deployment
What changed in chores-tracker last week?
```

**Option 3: Direct Agent Invocation**
```
Use the release-analyzer agent to analyze chores-tracker v5.20.0
```

## Plugin Structure

```
.claude/plugins/deployment-tracking/
├── agents/
│   └── release-analyzer.md          # Orchestrator agent
├── commands/
│   └── release.md                   # /release slash command
├── skills/
│   └── chores-tracker/              # Service-specific skill
│       ├── SKILL.md                 # Analysis logic
│       ├── config.json              # Service configuration
│       └── README.md                # Service documentation
└── README.md                        # This file
```

## Components

### 1. Release Analyzer Agent (`agents/release-analyzer.md`)

**Purpose**: Orchestrates release analysis across services

**Responsibilities**:
- Service discovery (which services are configured?)
- Query parsing (version, date range, latest)
- Error handling (rate limiting, version not found)
- Multi-service coordination (future)
- Result formatting and presentation

**When it's invoked**:
- Via `/release` command
- Via natural language queries about releases
- Automatically when service-related release questions are asked

### 2. Release Command (`commands/release.md`)

**Purpose**: Provides convenient CLI interface

**Syntax**:
```bash
/release <service> <version|date-range|latest>
```

**Examples**:
```bash
/release chores-tracker v5.20.0      # Specific version
/release chores-tracker latest        # Most recent
/release chores-tracker last-week     # Date range
/release chores-tracker recent        # Last 3 deployments
```

### 3. Service Skills (`skills/`)

**Purpose**: Service-specific configuration and analysis logic

Each service has its own skill containing:
- **SKILL.md**: Complete analysis workflow and instructions
- **config.json**: Service-specific configuration
  - Repository locations (service repo, GitOps repo)
  - Pattern matching rules (PR titles, JIRA extraction)
  - Commit categorization prefixes
- **README.md**: Service-specific documentation

**Current Services**:
- `chores-tracker` - Chores Tracker service

**Adding New Services**: See "Adding Services" section below

## How It Works

### Workflow for: `/release chores-tracker v5.20.0`

```
1. Command Parsing
   /release command extracts: service=chores-tracker, version=v5.20.0

2. Agent Orchestration
   release-analyzer agent:
   - Validates service exists (checks skills/chores-tracker/)
   - Reads service configuration (config.json)
   - Invokes service skill

3. Skill Execution (chores-tracker skill)
   Step 1: Find deployment PR for v5.20.0 in GitOps repo
   Step 2: Find previous deployment PR (v5.19.0)
   Step 3: Query commits between deployments
   Step 4: Analyze each commit:
     - Extract JIRA tickets
     - Categorize by type
     - Generate explanation
   Step 5: Format results (detailed or summary)

4. Result Presentation
   Agent formats and returns analysis to user
```

### GitHub Queries

All queries go through **GitHub MCP Server**:
- List merged PRs in GitOps repository
- List commits in service repository with date filtering
- Read PR details (title, merge date, etc.)

**No direct API calls** - everything through MCP for better integration and rate limit management.

## Output Formats

### Detailed View (≤20 commits)

```markdown
# Release Analysis: chores-tracker v5.20.0

**Deployment Date**: 2025-01-15 14:30 UTC
**Previous Release**: v5.19.0 (Deployed: 2025-01-08)
**Time Between Releases**: 7 days

## Summary
- Total Commits: 15
- JIRA Tickets: 8 unique tickets
- Contributors: 4 developers

### Changes by Type
- Features: 6 commits
- Fixes: 5 commits
- Refactoring: 2 commits
- Chores: 2 commits

## Detailed Commit List

### Features (6)
1. **[abc1234]** feat: Add JWT authentication
   - **JIRA**: PROJ-1234
   - **Author**: John Doe
   - **Date**: 2025-01-10
   - **Explanation**: Implemented JWT-based authentication...

[... all commits with explanations ...]

## JIRA Tickets in This Release
1. **PROJ-1234** - JWT Authentication
2. **PROJ-1235** - Password Reset
[... all tickets ...]
```

### Summary View (>20 commits)

```markdown
# Release Analysis: chores-tracker v5.20.0

## Summary
- Total Commits: 47
- JIRA Tickets: 23 unique tickets
- Contributors: 8 developers

## Key Highlights

### Major Features (Top 5)
1. **PROJ-1234** - JWT Authentication system
2. **PROJ-1240** - Reporting dashboard
[... top 5 features ...]

### Critical Fixes (Top 5)
1. **PROJ-1260** - Connection pool memory leak
[... top 5 fixes ...]

## Commits by Category
### Features (18 commits)
- [abc1234] feat: Add JWT authentication - PROJ-1234
[... first 10, then "and 8 more" ...]

---
Note: Summary view due to 47 commits.
Ask for "detailed view" to see all commits.
```

## Adding Services

To track a new service (e.g., hermes):

### Step 1: Create Skill Directory

```bash
mkdir -p .claude/plugins/deployment-tracking/skills/hermes
```

### Step 2: Copy Template Files

```bash
cd .claude/plugins/deployment-tracking/skills
cp chores-tracker/SKILL.md hermes/
cp chores-tracker/config.json hermes/
cp chores-tracker/README.md hermes/
```

### Step 3: Update config.json

Edit `skills/hermes/config.json`:

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
  "deployment_manifest_path": "apps/hermes-backend/deployment.yaml",
  "container_name": "hermes",
  "jira_patterns": [
    "\\[([A-Z]+-\\d+)\\]",
    "\\b([A-Z]+-\\d+)\\b"
  ],
  "pr_title_patterns": [
    "update hermes-backend to (v?[0-9.]+)",
    "chore: update hermes-backend to (v?[0-9.]+)"
  ],
  "commit_message_prefixes": [
    "fix:", "feat:", "refactor:", "perf:",
    "docs:", "test:", "chore:"
  ],
  "github_mcp_enabled": true
}
```

### Step 4: Update SKILL.md

Edit `skills/hermes/SKILL.md` frontmatter:

```yaml
---
name: hermes
description: Track commits and tickets for hermes releases
---

# Hermes

[... rest of SKILL.md stays the same ...]
```

Update any chores-tracker-specific references in the body to hermes.

### Step 5: Test the New Service

```bash
/release hermes latest
```

The agent will automatically discover the new service!

## Configuration

### Service Configuration (config.json)

Each service skill requires a `config.json`:

```json
{
  "service_name": "service-name",           // Name in GitOps PR titles
  "service_repo": {
    "owner": "org-name",                    // GitHub org/user
    "name": "repo-name"                     // Repository name
  },
  "gitops_repo": {
    "owner": "org-name",
    "name": "deployments"                   // GitOps repository
  },
  "deployment_manifest_path": "path/to/deployment.yaml",
  "container_name": "container-name",
  "jira_patterns": [                        // Regex for JIRA tickets
    "\\[([A-Z]+-\\d+)\\]",                 // [PROJ-1234]
    "\\b([A-Z]+-\\d+)\\b"                  // PROJ-1234
  ],
  "pr_title_patterns": [                    // Extract version from PR title
    "update service-name to (v?[0-9.]+)"
  ],
  "commit_message_prefixes": [              // Categorization
    "fix:", "feat:", "refactor:", "perf:",
    "docs:", "test:", "chore:"
  ],
  "github_mcp_enabled": true
}
```

### Pattern Matching

**PR Title Patterns**:
- Must include a capture group `(...)` for version
- Supports both `v5.20.0` and `5.20.0` formats
- Examples:
  - `"update chores-tracker to (v?[0-9.]+)"`
  - `"chore: bump version to (v?[0-9.]+)"`

**JIRA Patterns**:
- Standard regex for extracting ticket IDs
- Common formats:
  - `\\[([A-Z]+-\\d+)\\]` - Bracket notation
  - `\\b([A-Z]+-\\d+)\\b` - Standalone
  - `Jira:\\s*([A-Z]+-\\d+)` - Prefix notation

**Commit Prefixes**:
- Used to categorize commits
- Follows Conventional Commits standard
- Categories: features, fixes, refactoring, performance, docs, tests, chores

## Requirements

### GitHub MCP Server

**Required**: This plugin depends on GitHub MCP Server for all queries.

**Setup**:
1. Configure GitHub MCP Server in Claude Code settings
2. Authenticate with GitHub token (recommended for 5000 req/hour vs 60)
3. Ensure access to repositories:
   - Service repositories (e.g., artemishealth/chores-tracker)
   - GitOps repositories (e.g., artemishealth/deployments)

**Test GitHub Access**:
```
List recent commits in artemishealth/chores-tracker
```

### Repository Access

**Read access required** to:
- Service repositories (code repos)
- GitOps repositories (deployment manifests)

**Verify access**:
```bash
/release chores-tracker latest
```

If this fails with permission errors, check GitHub token scopes.

## Troubleshooting

### Plugin Not Loading

**Check**:
1. Plugin directory exists: `.claude/plugins/deployment-tracking/`
2. All files present:
   - `agents/release-analyzer.md`
   - `commands/release.md`
   - `skills/chores-tracker/SKILL.md`
3. Restart Claude Code

### Command Not Found

```bash
Error: /release command not found
```

**Fix**:
1. Verify `commands/release.md` exists
2. Check file has proper frontmatter
3. Restart Claude Code
4. Try: `Use the release-analyzer agent...` (direct agent invocation)

### Service Not Found

```bash
Error: Service 'hermes' is not configured.
```

**Fix**:
1. Check `skills/hermes/` directory exists
2. Verify `SKILL.md` and `config.json` present
3. See "Adding Services" section

### GitHub Rate Limiting

```bash
Error: GitHub API rate limit reached (0/60 remaining)
```

**Fix**:
1. **Authenticate GitHub MCP Server** with token (increases to 5000/hour)
2. Wait for rate limit reset (shown in error)
3. Use narrower date ranges to reduce queries

### Version Not Found

```bash
Error: Could not find deployment PR for v5.20.0
```

**Check**:
1. Version format matches PR titles (v5.20.0 vs 5.20.0)
2. PR title patterns in `config.json` match actual titles
3. Deployment PR was merged (not just opened)
4. Try: `/release chores-tracker latest` to see recent deployments

### Missing JIRA Tickets

**Verify**:
1. Commit messages include JIRA ticket IDs
2. JIRA patterns in `config.json` match ticket format
3. Check a few commits manually in GitHub

## Performance

**Typical Query Performance**:
- Version query: 3-5 GitHub API calls, 2-5 seconds
- Date range query: 5-10 API calls, 5-10 seconds
- Large releases (>50 commits): 10-15 seconds

**Optimization**:
- Use specific versions instead of date ranges
- Authenticate GitHub MCP for higher rate limits
- Request summary view for large releases

## Examples

### Daily Standup
```bash
/release chores-tracker latest
```
Quick check of what's in production

### Release Notes
```bash
/release chores-tracker v5.20.0
```
Generate detailed release notes

### Ticket Tracking
```bash
/release chores-tracker last-month
```
Find when specific tickets were deployed

### Deployment Report
```bash
/release chores-tracker last-week
```
Weekly deployment summary for team

### Version Comparison
```bash
/release chores-tracker v5.20.0
/release chores-tracker v5.19.0
```
Compare outputs to see differences

## Future Enhancements

- **Multi-service queries**: `/release --all last-week`
- **Slack/Teams integration**: Post release notes automatically
- **JIRA integration**: Query ticket status and details
- **Export formats**: Markdown, JSON, CSV for reporting
- **Deployment trends**: Track velocity and patterns
- **Custom filters**: By author, file path, commit type
- **Rollback analysis**: Compare current vs previous

## Architecture

### Progressive Disclosure

This plugin follows the progressive disclosure pattern:

1. **Command** - Simple CLI interface (`/release`)
2. **Agent** - Orchestration and service discovery
3. **Skills** - Service-specific logic and configuration

**Minimal Context Usage**:
- Install only what you need
- Each service is a separate skill
- Agent loads only when needed
- Skills load only when invoked

### Composability

**Plugin components work together**:
- Command invokes Agent
- Agent discovers and invokes Skills
- Skills use GitHub MCP Server
- Clean separation of concerns

**Can be used independently**:
- Direct agent invocation: "Use release-analyzer..."
- Direct skill invocation: "Use chores-tracker skill..."
- Command invocation: `/release chores-tracker...`

## Contributing

### Adding New Features

**New Service**: Follow "Adding Services" section
**New Command**: Add to `commands/` directory
**New Agent**: Add to `agents/` directory
**Enhance Skill**: Edit service-specific `SKILL.md`

### Testing

**Test new service**:
```bash
/release new-service latest
```

**Test command**:
```bash
/release chores-tracker v5.20.0
```

**Test agent directly**:
```
Use the release-analyzer agent to analyze chores-tracker v5.20.0
```

## License

Part of the `claude-agents` repository - Learning Lab for Anthropic AI Integration Patterns.

## Support

**Documentation**:
- Agent: `agents/release-analyzer.md`
- Command: `commands/release.md`
- Skill: `skills/chores-tracker/SKILL.md`

**Common Issues**:
- GitHub MCP not configured
- Rate limiting
- Version format mismatch
- Repository access denied

See "Troubleshooting" section above for solutions.
