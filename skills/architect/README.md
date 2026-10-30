# architect

One Claude Code skill for architecture consulting. It replaces four separate plugins:
`aws-well-architected`, `cloud-design-patterns`, `devops-architect` and
`platform-engineering-architect`. It also adds lenses for system design and agentic
platforms.

```bash
/plugin install architect@claude-agents-marketplace
```

## Lenses

| Lens | Covers | Files |
|---|---|---|
| System design | Designing from requirements: capacity estimates, load balancing, caching, data stores and sharding, consistency, queues, APIs, rate limiting, and worked designs (chat, feed, notifications, checkout, file sync and more) | `references/system-design/` |
| Well-Architected | AWS pillar reviews, trade-offs, remediation roadmaps | `references/well-architected/` |
| Cloud design patterns | Strangler fig, sagas, outbox, pub-sub, circuit breaker, CQRS, BFF, sidecar, queue-based load leveling, priority queue, API routing | `references/cloud-patterns/` |
| DevOps | 12-Factor compliance and the DevOps maturity journey, scored | `references/devops/` |
| Platform engineering | IDP design with CNPA, Microsoft, Team Topologies, DORA; SRE: SLIs, error budget policy, burn-rate alerting, incident response | `references/platform-engineering/` |
| Agentic platform | Agent infrastructure and governance: identity, tools and approvals, sandboxes, evals, model gateway, autonomy levels | `references/agentic-platform.md` |

`SKILL.md` holds the shared consulting workflow and a table for picking the lens. Each
lens's `workflow.md` and deeper files load only when a question needs them, so the
skill's always-loaded description stays one entry instead of four.

For a scored client maturity assessment with Excel and Word deliverables, use the
`infra-maturity-assessment` skill. Its optional AI & Agent Platform tab uses the same
model as the agentic platform lens.

## Migrating from the old plugins

```bash
/plugin uninstall aws-well-architected@claude-agents-marketplace
/plugin uninstall platform-engineering-architect@claude-agents-marketplace
/plugin install architect@claude-agents-marketplace
```

`cloud-design-patterns` and `devops-architect` were never listed as installed plugins
here. If you copied them into `~/.claude/skills/`, delete those copies.
