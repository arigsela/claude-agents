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
version: "1.2.1"
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
5. **Get an independent challenge.** Do this for every deliverable that is a design,
   review or recommendation someone else will act on (not for a quick answer in
   conversation), when the `codex` skill is in your list of available skills. Whenever
   you don't run it, say why in one line of your reply, for example "Codex review not
   run: the codex skill isn't installed."

   The draft goes to OpenAI: strip secrets and credentials, and if it holds a client's
   confidential material (hostnames, security gaps, customer data), ask the user before
   sending it.

   Consult mode needs a git repository. If the working directory isn't inside one
   (`git rev-parse --show-toplevel` fails), create one in your scratchpad or temp
   directory (`git init -q <dir>`), save the draft there as `draft.md`, and run every
   consult-mode command from it, starting each with `cd <dir> &&`. The draft file keeps
   Codex's file listing from failing, which would make the codex skill report
   `VERDICT: unavailable` for an answer it did give. Codex needs nothing else from the
   real folder, since the draft is also pasted into the prompt. Delete that directory
   afterwards.

   Invoke the `codex` skill in consult mode as a new conversation (`/codex <prompt>`, or
   the Skill tool with the prompt as its argument; if it offers to continue an earlier
   conversation, start fresh), with a prompt made of these parts, in order:
   1. "Attack this architecture draft. Report only problems, most severe first, each
      with a severity (Critical, High, Medium or Low), the section it refers to, and
      why it is wrong."
   2. What to look for: estimates or arithmetic that are wrong or missing; failure modes
      with no answer; consistency choices that could lose data or money; trade-offs
      presented as free; a simpler or cheaper design that meets the same targets; steps
      in the wrong order.
   3. The client's request and the labelled assumptions.
   4. The full draft, pasted in. Codex can't read files outside the repository, and the
      draft is not a plan file, so consult mode's plan-file lookup doesn't apply.

   Check each finding against the draft and the facts. Fix the ones that hold, and keep
   a one-line reason for each one you reject: Codex is a second opinion, not an
   authority. Rate what you fix on this skill's severity scale; Codex's labels are input
   only. Then add an **Independent review** line under the deliverable's summary: that
   Codex reviewed the draft, how many of its findings changed the draft, and any
   disagreement left for the reader to decide. Consult mode leaves
   `.context/codex-session-id` and `.gstack/tmp/` in the repository it runs from; keep
   them out of commits.
6. **Deliver** in this order:
   - a summary with the top three findings;
   - findings by severity, each with a recommendation;
   - a roadmap: quick wins (under a week), short-term work (1–4 weeks) and strategic
     work (1–3 months).

Each lens's `workflow.md` has its own output template. When lenses combine, use the
template of the lens that leads (system design for a design or a stress-test of a
proposal; Well-Architected for an AWS posture review), keep the order above, and fold the
other lenses' findings in, each tagged with its pillar or lens.

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
- Diagrams go to `architecture-diagrams` or `drawio-skill` when a diagram is the
  deliverable; an ASCII sketch inside a design needs no hand-off.
- An independent adversarial review of a draft goes to the `codex` skill in consult mode
  (§2 step 5).

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
