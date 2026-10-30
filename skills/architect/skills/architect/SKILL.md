---
name: architect
description: >
  Architecture consulting with six lenses: system design from requirements (capacity
  estimates, caching, sharding, consistency, queues, rate limiting, worked designs such
  as chat, feeds, notifications and checkout); AWS Well-Architected reviews; cloud design
  patterns (microservices, sagas, CQRS, strangler fig, event-driven); DevOps and 12-Factor
  maturity; platform engineering (IDPs, golden paths, Team Topologies, DORA, SLOs and
  burn-rate alerting); and agentic or AI platforms (agent identity, tools and approvals,
  sandboxes, evals, model gateway, autonomy levels). Use when designing a system ("design
  a system for…", "how would this scale", back-of-envelope estimates), reviewing an
  architecture, advising a client, comparing options and trade-offs, or checking
  practices against one of these frameworks. For a scored client maturity assessment with
  Excel/Word deliverables, use infra-maturity-assessment instead.
version: "1.1.0"
author:
  name: "Arisela"
tags: [architecture, consulting, system-design, capacity-planning, aws, well-architected, design-patterns, devops, 12-factor, platform-engineering, idp, sre, ai-agents, agentic-platform]
category: learning
requires:
  tools: []
  skills: []
---

# Architect

One consulting skill with six lenses. Pick the lens (or lenses) the question needs, read
that lens's `workflow.md`, and load its deeper files only when the answer needs them.

## 1. Pick the lens

| The question is about | Lens | Read first |
|---|---|---|
| Designing a system from requirements, or stress-testing one: capacity, components, data stores, caching, consistency, queues, rate limits, what breaks at scale | System design | `references/system-design/workflow.md` (then `estimation.md`, `building-blocks.md`, `reference-designs.md`) |
| An AWS workload's posture: pillar review, cost, reliability, security, trade-offs between pillars | Well-Architected | `references/well-architected/workflow.md` (then `pillars.md`, `decisions.md`, `patterns.md`) |
| Splitting or connecting services: messaging, distributed transactions, resilience, monolith migration, API routing | Cloud design patterns | `references/cloud-patterns/workflow.md` (then `patterns.md`, `decisions.md`) |
| How a team builds and ships: CI/CD, 12-Factor compliance, DevOps maturity, operational practices | DevOps | `references/devops/workflow.md` (then `12-factor-deep-dive.md`, `devops-maturity-deep-dive.md`) |
| An internal developer platform: golden paths, self-service, platform team shape, DORA, developer experience; SLOs, error budgets, burn-rate alerting, incident response | Platform engineering | `references/platform-engineering/workflow.md` (then `frameworks.md`, `decisions.md`, `patterns.md`) |
| AI agents doing delivery or ops work: agent infrastructure, governance, model access, how much autonomy to allow | Agentic platform | `references/agentic-platform.md` |

Lenses combine. A new design usually starts in system design, then goes to
Well-Architected to pick AWS services and to cloud patterns for service-to-service
mechanics. For SLOs, error budgets, alerting or incident response, go straight to
`references/platform-engineering/frameworks.md` (SRE Principles) rather than that lens's
IDP workflow. An agentic platform review usually also needs the platform engineering
lens (agents run on the IDP) and the security pillar of Well-Architected. A monolith
migration usually needs cloud patterns plus DevOps. Say which lenses you used.

## 2. Shared consulting workflow (every lens)

1. **Classify the request:** review or audit, new design, a single decision, trade-off
   analysis, or a roadmap.
2. **Gather context.** Ask; don't assume:
   - workload type and scale;
   - team structure and ownership;
   - cloud and stack;
   - compliance requirements;
   - current state, recent incidents and pain points;
   - non-functional targets: load and growth, read:write ratio, latency (as a
     percentile), availability, and which data must be strongly consistent;
   - budget and timeline.

   When the client can't answer, state an assumption, label it as one in the
   deliverable, and carry it through.
3. **Apply the lens's framework.** Assess verified state, not claims. If evidence is
   missing, say so and assess conservatively.
4. **Show trade-offs.** Give options with their costs, not one answer, and say which you
   recommend and why.
5. **Deliver** in this order:
   - a summary with the top three findings;
   - findings by severity, each with a recommendation;
   - a roadmap: quick wins (under a week), short-term work (1–4 weeks) and strategic
     work (1–3 months).

Each lens's `workflow.md` has its own output template; use it.

| Severity | Definition | Action |
|---|---|---|
| Critical | Active data-loss risk, breach potential, compliance violation, or autonomy without the controls it needs | Fix immediately |
| High | Single point of failure, missing encryption, no backup, a critical path that fails at expected peak load, agents with unscoped credentials | Within 1–2 weeks |
| Medium | Sub-optimal configuration, missing monitoring, manual processes | Next sprint |
| Low | Nice-to-have improvements | Backlog |

## 3. Rules that hold across lenses

- **Fit the size.**
  - Patterns, platforms and agents all cost something to run.
  - A small team with a simple app gets a monolith and a pipeline, not microservices.
  - Under about 50 developers, a team gets tool-level guardrails, not an agent platform.
- **Foundations first.**
  - Version control and CI come before continuous deployment.
  - IaC comes before policy-as-code.
  - A working IDP comes before an agent platform.
  - Evals and an audit record come before more agent autonomy.
- **Numbers before components:** estimate load, data size and growth before choosing
  components, and name the bottleneck each addition fixes.
- **Incremental over big-bang:** strangle, pilot one path, measure, then widen.
- **Tools follow practices:** don't recommend buying a product before the process change
  it supports is understood.
- **Name the people side:** team structure, ownership and separation of duties decide
  whether an architecture survives.

## 4. Hand-offs

- A scored client assessment (L1–L4 workbook, Word report, horizon roadmap) goes to the
  `infra-maturity-assessment` skill, which has an AI & Agent Platform tab.
- Diagrams go to `architecture-diagrams` or `drawio-skill`.

## Reference map

```
references/
├── system-design/         workflow.md · estimation.md · building-blocks.md · reference-designs.md
├── well-architected/      workflow.md · pillars.md · decisions.md · patterns.md
├── cloud-patterns/        workflow.md · patterns.md · decisions.md
├── devops/                workflow.md · 12-factor-deep-dive.md · devops-maturity-deep-dive.md
├── platform-engineering/  workflow.md · frameworks.md · decisions.md · patterns.md
└── agentic-platform.md    layers, path types, autonomy levels, build order, control catalog
```
