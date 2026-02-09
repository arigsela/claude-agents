# Claude Code Skills

Reusable Claude Code skills for AI-assisted development workflows.

## Installation (Claude Code Plugin System)

Each skill is a standalone Claude Code plugin. Add the marketplace, then install individual skills:

```bash
# Add the marketplace
/plugin marketplace add github:arigsela/claude-agents

# Install individual skills
/plugin install aws-well-architected@claude-agents-marketplace
/plugin install code-review@claude-agents-marketplace
/plugin install feature-builder@claude-agents-marketplace
```

## Available Skills

| Skill | Version | Category | Description |
|-------|---------|----------|-------------|
| [architecture-diagrams](./architecture-diagrams/) | 1.0.0 | documentation | System diagrams with Mermaid/PlantUML/C4 |
| [code-review](./code-review/) | 1.0.0 | development | Parallel agent PR review with confidence scoring |
| [feature-builder](./feature-builder/) | 1.0.0 | development | Ralph Loop automated feature development |
| [prompt-engineering-patterns](./prompt-engineering-patterns/) | 1.0.0 | learning | LLM prompt optimization techniques |
| [aws-well-architected](./aws-well-architected/) | 1.0.0 | architecture | AWS Well-Architected Framework reviews across all six pillars |
| [devops-architect](./devops-architect/) | 1.0.0 | architecture | DevOps best practices using 12-Factor App and maturity scoring |
| [cloud-design-patterns](./cloud-design-patterns/) | 1.0.0 | architecture | AWS cloud design patterns for microservices and distributed systems |
| [platform-engineering-architect](./platform-engineering-architect/) | 1.0.0 | architecture | Platform Engineering IDP design using CNPA, Team Topologies, DORA |
| [git-commit-pr](./git-commit-pr/) | 1.0.0 | development | Automated git workflow: branch, commit, push, and PR creation |
| [creating-implementation-plans](./creating-implementation-plans/) | 1.0.0 | development | Create detailed implementation plans with phased task breakdown |
| [executing-implementation-plans](./executing-implementation-plans/) | 1.0.0 | development | Execute approved plans with phase-based checkpoints and testing |

## Legacy CLI

The Skills CLI provides marketplace functionality for discovering, installing, and managing skills.

### CLI Commands

```bash
# List installed skills
./skill-cli.sh list
./skill-cli.sh list --verbose

# Search skills
./skill-cli.sh search "code review"
./skill-cli.sh search "diagram"

# Show skill details
./skill-cli.sh info code-review

# Install skills
./skill-cli.sh add ./path/to/skill        # From local directory
./skill-cli.sh add ./skill.skill          # From bundle file
./skill-cli.sh add github:user/repo/path  # From GitHub

# Update and remove
./skill-cli.sh update code-review
./skill-cli.sh update --check
./skill-cli.sh remove my-skill

# Validate and package
./skill-cli.sh validate ./my-skill
./skill-cli.sh pack ./my-skill -o ./bundles
```

### SKILL.md Schema

Skills are defined with a YAML frontmatter in `SKILL.md`:

```yaml
---
name: skill-name                  # Required
description: Brief description    # Required
version: "1.0.0"                  # Recommended (defaults to 1.0.0)
author:
  name: "Author Name"
  email: "author@example.com"
tags: [tag1, tag2]                # For searchability
category: development             # development|productivity|testing|learning|automation|documentation
repository: "https://github.com/user/repo"
license: "MIT"
requires:
  tools: [gh, git]                # CLI tools needed
  skills: [other-skill]           # Skill dependencies
---
```

### Skill Structure

```
skill-name/
├── .claude-plugin/
│   └── plugin.json    # Claude Code plugin manifest
├── skills/
│   └── skill-name/
│       ├── SKILL.md       # Full skill definition (YAML frontmatter + instructions)
│       ├── references/    # Extended documentation
│       ├── assets/        # Templates, examples, data files
│       └── scripts/       # Automation utilities
├── SKILL.md           # Stub for legacy skill-cli.sh compatibility
└── README.md          # GitHub/marketplace documentation
```

### Local Catalog

The marketplace tracks installed skills in `skills-catalog.json`:

```json
{
  "version": 1,
  "lastUpdated": "2026-01-19T00:00:00Z",
  "skills": {
    "skill-name": {
      "name": "skill-name",
      "version": "1.0.0",
      "path": "./skill-name",
      "installedAt": "ISO-timestamp",
      "source": { "type": "local|github|bundle", "ref": "..." }
    }
  }
}
```

## Quick Start

```bash
# Install all skills from this repo
for skill in architecture-diagrams code-review feature-builder prompt-engineering-patterns aws-well-architected devops-architect cloud-design-patterns platform-engineering-architect git-commit-pr creating-implementation-plans executing-implementation-plans; do
  ./skill-cli.sh add ./skills/$skill
done

# Or install a specific skill
./skill-cli.sh add ./skills/code-review
```
