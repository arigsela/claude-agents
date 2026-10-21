---
name: platform-engineering-architect
description: |
  Platform Engineering architecture decision support using industry frameworks (CNPA, Microsoft, Team Topologies, DORA, SRE).
  Use when: (1) Designing Internal Developer Platforms (IDPs), (2) Making platform architecture decisions,
  (3) Evaluating platform capabilities or maturity, (4) Planning platform team structure,
  (5) Defining golden paths or paved roads, (6) Assessing cognitive load reduction strategies,
  (7) Preparing for platform engineering interviews, (8) Creating platform roadmaps.
  Triggers: "platform engineering", "IDP", "developer platform", "golden path", "cognitive load",
  "DORA metrics", "platform team", "thinnest viable platform", "self-service", "developer experience".
---

# Platform Engineering Architect

Decision support for Internal Developer Platform (IDP) architecture using industry-standard frameworks.

## Quick Reference: Core Frameworks

| Framework | Use For | Reference |
|-----------|---------|-----------|
| **Microsoft 4 Areas** | Organizing platform scope | [frameworks.md](references/frameworks.md#microsoft-four-areas) |
| **Microsoft 6 Capabilities** | Maturity assessment | [frameworks.md](references/frameworks.md#microsoft-capability-model) |
| **CNPA 8 Capabilities** | IDP feature completeness | [frameworks.md](references/frameworks.md#cnpa-eight-capabilities) |
| **Team Topologies** | Team structure decisions | [frameworks.md](references/frameworks.md#team-topologies) |
| **DORA Metrics** | Measuring platform success | [frameworks.md](references/frameworks.md#dora-metrics) |
| **SRE Principles** | Reliability architecture | [frameworks.md](references/frameworks.md#sre-principles) |
| **Three Ways** | DevOps culture alignment | [frameworks.md](references/frameworks.md#the-three-ways) |

## Decision Workflow

### 1. Clarify the Decision Type

Before recommending, identify what type of decision:

| Decision Type | Key Questions | Primary Framework |
|---------------|---------------|-------------------|
| **Scope/Features** | "What should our platform do?" | CNPA 8 Capabilities |
| **Organization** | "How should we structure teams?" | Team Topologies |
| **Maturity** | "Where are we vs where should we be?" | Microsoft 6 Capabilities |
| **Measurement** | "How do we prove platform value?" | DORA + Three-Pillar |
| **Reliability** | "What SLOs/error budgets?" | SRE Principles |
| **Adoption** | "How do we get teams to use it?" | Golden Paths + TVP |

### 2. Apply Framework Principles

**Platform as Product Mindset:**
- Developers are customers, not captive users
- Adoption should be organic, not mandated
- Measure satisfaction, not just usage

**Thinnest Viable Platform (TVP):**
- Start with minimum capabilities that deliver value
- Expand based on actual developer friction, not theoretical completeness
- Prefer adopting existing tools over building custom

**Cognitive Load Reduction:**
- Abstract complexity from stream-aligned teams
- Golden paths should make the right thing easy
- Self-service without requiring deep platform knowledge

**Self-Service with Guardrails:**
- Enable autonomy within defined parameters
- Automate governance, don't gate on tickets
- Least privilege without manual service desk processes

### 3. Common Architecture Decisions

For detailed decision trees and patterns, see [decisions.md](references/decisions.md).

**CI/CD Architecture:**
- Push-based (Jenkins-style) vs Pull-based (GitOps)
- Monorepo vs polyrepo pipeline strategies
- Environment promotion patterns

**Compute Platform:**
- Kubernetes vs managed PaaS vs serverless
- Multi-cluster vs single-cluster strategies
- Node provisioning (Karpenter, Cluster Autoscaler)

**Infrastructure as Code:**
- Terraform vs Pulumi vs Crossplane
- GitOps for infrastructure (ArgoCD, Flux)
- Module/composition patterns

**Observability Stack:**
- Build vs buy (Prometheus/Grafana vs Datadog/New Relic)
- OpenTelemetry adoption strategy
- SLO-based alerting architecture

**Developer Portal:**
- Build vs adopt (custom vs Backstage/Port/Cortex)
- Service catalog scope
- Documentation-as-code integration

### 4. Maturity Assessment

Use Microsoft's 6 Capability Model to assess current state:

1. **Investment** - Dedicated team? Budget? Executive sponsorship?
2. **Adoption** - Organic or mandated? Discovery mechanisms?
3. **Governance** - Policy-as-code? Automated compliance?
4. **Provisioning** - Self-service? IaC? Time to provision?
5. **Interfaces** - Portal? CLI? API? Developer friction?
6. **Measurement** - DORA metrics? Feedback loops? NPS?

Rate each: Initial → Repeatable → Defined → Managed → Optimizing

### 5. Team Structure Recommendations

Apply Team Topologies model:

| Team Type | Purpose | Platform Relevance |
|-----------|---------|-------------------|
| **Stream-Aligned** | Deliver business value | Platform customers |
| **Platform** | Reduce cognitive load | You are building this |
| **Enabling** | Help teams adopt capabilities | May overlap with platform |
| **Complicated-Subsystem** | Deep expertise areas | Security, data, ML platforms |

**Interaction Modes:**
- **Collaboration** - Close work for discovery (time-boxed)
- **X-as-a-Service** - Minimal interaction, self-service
- **Facilitating** - Coaching and enablement

Target state: Platform team provides X-as-a-Service to stream-aligned teams.

## Output Formats

When providing architecture recommendations:

1. **State the decision type** and which framework applies
2. **Present options** with trade-offs (not single recommendation)
3. **Map to principles** (TVP, cognitive load, self-service)
4. **Include maturity context** - what's appropriate for their stage
5. **Provide measurable success criteria** using DORA or Three-Pillar

## Reference Files

- [frameworks.md](references/frameworks.md) - Complete framework details (CNPA, Microsoft, Team Topologies, DORA, SRE, Three Ways)
- [decisions.md](references/decisions.md) - Decision trees for common architecture choices
- [patterns.md](references/patterns.md) - Implementation patterns and anti-patterns
