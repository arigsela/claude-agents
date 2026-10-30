# Platform Engineering Frameworks Reference

## Table of Contents
1. [Microsoft Four Areas](#microsoft-four-areas)
2. [Microsoft Capability Model](#microsoft-capability-model)
3. [CNPA Eight Capabilities](#cnpa-eight-capabilities)
4. [Team Topologies](#team-topologies)
5. [DORA Metrics](#dora-metrics)
6. [Three-Pillar Framework](#three-pillar-framework)
7. [SRE Principles](#sre-principles)
8. [The Three Ways](#the-three-ways)
9. [Platform Product Lifecycle](#platform-product-lifecycle)

---

## Microsoft Four Areas

Microsoft organizes platform engineering into four problem space areas:

### 1. Engineering Systems
**Definition:** Curated DevOps tools—CI/CD, package management, code environments, AI assistants, scanners.

**Components:**
- CI/CD pipelines (GitHub Actions, Azure Pipelines, GitLab CI)
- Package/artifact management (npm, Maven, container registries)
- Code quality tools (linters, scanners, SAST/DAST)
- Development environments (Codespaces, devcontainers)
- AI assistants (GitHub Copilot)

**Key Insight:** Start self-service here—lowest learning curve for both platform teams and developers.

### 2. Application Platform
**Definition:** Curated IaaS/PaaS services + observability targeting each application stack.

**Components:**
- Compute (Kubernetes, serverless, VMs)
- Data services (databases, caching, messaging)
- Observability (metrics, logs, traces)
- Networking (service mesh, API gateways)
- Security services (secrets, identity)

**Key Insight:** Templates should represent tested configurations so teams can start immediately.

### 3. Application Templates
**Definition:** Organization quickstarts that encapsulate "start right, stay right" guidance.

**Components:**
- Starter code/boilerplate
- CI/CD pipeline configurations
- Infrastructure as Code modules
- Tooling configurations
- Best practices documentation

**Key Insight:** Templates reference centralized assets for composability; allow flexibility for edge cases.

### 4. Developer Self-Service
**Definition:** The glue—APIs, orchestrators, catalogs, UX that reduce toil and enable autonomy.

**Components:**
- Developer portals (Backstage, Port, custom)
- CLIs and automation tools
- Service catalogs
- Provisioning APIs
- Documentation platforms

**Key Insight:** Like a B2B storefront—developers discover and fulfill needs without human interaction.

---

## Microsoft Capability Model

Six capabilities with maturity stages (Initial → Repeatable → Defined → Managed → Optimizing):

### 1. Investment
**Focus:** How are staff and funds allocated to platform capabilities?

| Stage | Characteristics |
|-------|-----------------|
| Initial | Ad-hoc, no dedicated budget |
| Repeatable | Some dedicated resources |
| Defined | Formal team and budget |
| Managed | ROI tracking, justified investment |
| Optimizing | Continuous investment optimization |

### 2. Adoption
**Focus:** Why and how do users discover and use platform capabilities?

| Stage | Characteristics |
|-------|-----------------|
| Initial | Word of mouth only |
| Repeatable | Basic documentation exists |
| Defined | Catalog and discovery mechanisms |
| Managed | Adoption metrics tracked |
| Optimizing | Organic growth, high satisfaction |

### 3. Governance
**Focus:** How do you ensure access, manage costs, data, and IP appropriately?

| Stage | Characteristics |
|-------|-----------------|
| Initial | Manual, inconsistent |
| Repeatable | Some policies documented |
| Defined | Policy-as-code emerging |
| Managed | Automated compliance |
| Optimizing | Preventive governance |

### 4. Provisioning & Management
**Focus:** How are resources provisioned and managed?

| Stage | Characteristics |
|-------|-----------------|
| Initial | Manual, ticket-based |
| Repeatable | Some automation |
| Defined | IaC for most resources |
| Managed | Full self-service |
| Optimizing | Intelligent automation |

### 5. Interfaces
**Focus:** How do users interact with and consume platform capabilities?

| Stage | Characteristics |
|-------|-----------------|
| Initial | CLI/scripts only |
| Repeatable | Basic UI exists |
| Defined | Integrated portal |
| Managed | Unified experience |
| Optimizing | Contextual, personalized |

### 6. Measurements & Feedback
**Focus:** How do you gather feedback and measure success?

| Stage | Characteristics |
|-------|-----------------|
| Initial | No formal measurement |
| Repeatable | Some metrics collected |
| Defined | DORA metrics tracked |
| Managed | Feedback loops established |
| Optimizing | Data-driven decisions |

---

## CNPA Eight Capabilities

CNCF Platform Engineering certification framework for IDP completeness:

| # | Capability | Description | Implementation Examples |
|---|------------|-------------|------------------------|
| 01 | **API-Driven Design** | Every capability accessible programmatically | Kubernetes CRDs, REST APIs, GraphQL |
| 02 | **Declarative Model** | Infrastructure and apps defined as code | GitOps, Terraform, Helm charts |
| 03 | **Automation & Orchestration** | Automated workflows and scaling | CI/CD pipelines, KEDA, Argo Workflows |
| 04 | **Self-Service & Onboarding** | Developers can provision without tickets | Portal, CLI, PR-based provisioning |
| 05 | **Observability & Monitoring** | Built-in visibility across the stack | Metrics, logs, traces, dashboards |
| 06 | **Security & Compliance** | Embedded security, policy enforcement | RBAC, OPA/Kyverno, secrets management |
| 07 | **Extensibility & Plugins** | Platform can be extended without core changes | Custom operators, Crossplane compositions |
| 08 | **Modularity & Layers** | Clear separation of concerns | Infra → Platform Services → Developer Interface |

---

## Team Topologies

### Four Fundamental Team Types

| Team Type | Purpose | Size | Cognitive Load |
|-----------|---------|------|----------------|
| **Stream-Aligned** | Deliver business value end-to-end | 5-9 | Should be minimized |
| **Platform** | Reduce cognitive load for stream-aligned | 5-9 | Absorbs complexity |
| **Enabling** | Help teams adopt new capabilities | 3-6 | Temporary engagement |
| **Complicated-Subsystem** | Deep expertise in specific area | 3-6 | Specialists |

### Three Interaction Modes

| Mode | Duration | When to Use |
|------|----------|-------------|
| **Collaboration** | Time-boxed | Discovery, new capability development |
| **X-as-a-Service** | Ongoing | Mature, well-documented capabilities |
| **Facilitating** | Time-boxed | Coaching, skill transfer |

### Platform Team Evolution

**Early Stage:** Collaboration with stream-aligned teams to understand needs
**Growth Stage:** Facilitating to help teams adopt platform capabilities
**Mature Stage:** X-as-a-Service with minimal direct interaction

### Cognitive Load Types

- **Intrinsic:** Inherent complexity of the problem domain
- **Extraneous:** Unnecessary complexity from poor tooling/processes
- **Germane:** Learning and growth investment

**Platform goal:** Reduce extraneous load so teams can focus on intrinsic and germane.

---

## DORA Metrics

### The Four Key Metrics

| Metric | Definition | Elite | High | Medium | Low |
|--------|------------|-------|------|--------|-----|
| **Deployment Frequency** | How often code deploys to production | On-demand (multiple/day) | Daily-weekly | Weekly-monthly | Monthly+ |
| **Lead Time for Changes** | Commit to production | <1 hour | 1 day-1 week | 1 week-1 month | 1-6 months |
| **Mean Time to Recovery** | Time to restore service | <1 hour | <1 day | 1 day-1 week | 1 week+ |
| **Change Failure Rate** | % of deployments causing incidents | 0-15% | 16-30% | 31-45% | 46%+ |

### Key Insights from Accelerate

- Speed and stability are NOT trade-offs—elite teams excel at both
- These metrics correlate with organizational performance
- Platform engineering directly impacts all four metrics
- Measure at team level, not just organization level

### Platform Impact on DORA

| Platform Capability | DORA Impact |
|---------------------|-------------|
| GitOps/automated deployment | ↑ Deployment Frequency, ↓ Lead Time |
| Canary/progressive delivery | ↓ Change Failure Rate |
| Observability + rollback | ↓ MTTR |
| Self-service provisioning | ↓ Lead Time |

---

## Three-Pillar Framework

For measuring platform success (CNPA):

### Operational Efficiency
- DORA metrics performance
- Infrastructure costs / unit of work
- Incident frequency and severity
- Automation rate (% of tasks automated)
- Toil reduction metrics

### Developer Experience
- Developer NPS (Net Promoter Score)
- Time to first deployment (onboarding)
- Self-service adoption rate
- Developer satisfaction surveys
- Time spent on platform vs product work

### Business Impact
- Time-to-market for features
- Feature velocity (features shipped/quarter)
- Platform ROI calculation
- Revenue per engineering hour
- FinOps metrics (cost per transaction)

---

## SRE Principles

### Service Level Concepts

| Concept | Definition | Example |
|---------|------------|---------|
| **SLI** (Indicator) | Quantitative measure of service | Request latency, error rate |
| **SLO** (Objective) | Target value for SLI | 99.9% requests < 200ms |
| **SLA** (Agreement) | Contract with consequences | 99.9% uptime or credits |

### Error Budgets

**Formula:** Error Budget = 100% - SLO

**Example:** 99.9% SLO = 0.1% error budget = 43.2 minutes/month downtime allowed

**Usage:**
- Budget remaining → ship features faster
- Budget depleted → focus on reliability
- Creates objective trade-off framework

### Choosing SLIs

Measure what users experience, as close to them as possible (load balancer or edge logs
before application metrics). Express each SLI as good events ÷ valid events, and latency
as the share of requests faster than a threshold, never as an average.

| Method | Applies to | Signals |
|--------|------------|---------|
| **Golden signals** | Any user-facing service | Latency, traffic, errors, saturation |
| **RED** | Each request-driven service or endpoint | Rate, Errors, Duration |
| **USE** | Each resource (CPU, memory, disk, connection pool, queue) | Utilization, Saturation, Errors |

Use RED and golden signals for SLOs and paging; use USE for capacity and for diagnosis
once a page fires. Set SLOs per critical user journey (log in, check out), not per
microservice.

Getting the availability SLI right:

- **Count the errors users see that the app never logs:** 502/503/504s generated by the
  load balancer when targets crash, time out or are missing. A full outage looks like
  this.
- **Define valid and good requests explicitly.** Valid requests are the ones the
  service is expected to serve. Leave out client errors that are the caller's fault
  (malformed input, failed authentication or authorization, not found) and rejections
  of clients that exceeded their agreed quota: counted as errors they page on client
  behaviour; counted as successes a flood of them dilutes real failures. Count as bad
  the failures the service causes: 5xx, timeouts, and 429s or 503s from load shedding,
  exhausted capacity or a misconfigured limit.
- **Tag quota rejections distinctly** (a label or a reason header) so the SLI can tell
  them apart from load-shedding 429s, and watch the client-error and quota-rejection
  shares on their own: a jump there can mean a bad deploy or limits rollout that the
  SLI won't show.
- **Request-based budgets drain faster at peak:** at 99.9% a full outage at peak traffic
  spends the month's request budget well before 43 minutes. Say which kind of budget the
  SLO uses.

### Error Budget Policy

Write down, before the budget runs out, what happens when it does, and get product and
engineering to agree:

- **Budget healthy:** normal release pace.
- **Budget mostly spent:** extra review for risky changes; reliability work moves up the
  backlog.
- **Budget exhausted:** freeze feature releases for the service (security and reliability
  fixes still ship) until the budget recovers over the window.
- **Any single incident that consumes more than 20% of the budget** gets a postmortem
  with tracked action items (the example policy in Google's SRE Workbook).

### Burn-Rate Alerting

Burn rate = observed error rate ÷ (1 − SLO). A burn rate of 1 spends exactly the whole
budget over the SLO window; 14.4 spends a 30-day budget in about 2 days.

Multiwindow, multi-burn-rate alerts for a 30-day SLO (Google SRE Workbook). An alert
fires only when both the long and the short window exceed the rate: the long window
proves the burn is significant, and the short window stops the alert as soon as the burn
ends.

| Severity | Burn rate | Long window | Short window | Budget spent when it fires |
|----------|-----------|-------------|--------------|----------------------------|
| Page | 14.4× | 1 hour | 5 minutes | 2% |
| Page | 6× | 6 hours | 30 minutes | 5% |
| Ticket | 1× | 3 days | 6 hours | 10% |

Example: with a 99.9% SLO the budget is a 0.1% error rate, so the first page fires when
the error rate exceeds 1.44% over both the last hour and the last 5 minutes. For
low-traffic services, add synthetic traffic, require a minimum request count, or widen
the windows; otherwise one failed request pages someone.

Burn-rate alerts are blind when traffic stops: zero errors out of zero requests never
fires (DNS failure, expired certificate, a broken listener). Pair them with an external
synthetic probe that pages after a few consecutive failures and an alert on traffic far
below the same hour last week. Generate the recording and alerting rules from an SLO
definition (Sloth, Pyrra, OpenSLO, or the cloud provider's SLO feature) rather than by
hand.

Short, high-stakes events (an on-sale, a launch, a match kickoff) don't fit a 30-day
budget: a 10-minute event is over before a 1-hour window fires. Give the event its own
SLO and page on 1–5 minute windows while it runs.

### Toil Elimination

**Toil characteristics:**
- Manual, repetitive, automatable
- Tactical, no enduring value
- Scales linearly with service growth

**Target:** <50% of SRE time on toil; rest on engineering

### Blameless Postmortems

- Focus on systems, not individuals
- Document timeline, impact, root cause
- Identify preventive measures
- Share learnings organization-wide

### Incident Response

- **Lifecycle:** detect → triage and declare a severity → mitigate → resolve → postmortem.
  Mitigate before diagnosing: roll back, fail over or shed load first, and find the root
  cause after users are safe.
- **Severity levels:** defined in advance by user impact (for example, SEV1 = a critical
  journey down for many users or data at risk; SEV2 = degraded or a subset affected;
  SEV3 = minor, no urgent user impact), each with who is paged and how often status is
  posted.
- **Roles for larger incidents:** an incident commander who coordinates and decides, an
  operations lead who makes changes, and a communications lead who updates stakeholders.
- **Every alert is actionable** and links to a runbook with the first diagnostic steps
  and safe mitigations. Delete or demote alerts nobody acts on.
- **On-call load:** keep it sustainable; Google's SRE book targets at most about two
  incidents per 12-hour shift so each one gets handled and followed up properly.
- **Measure:** time to detect, time to mitigate and time to restore, by severity, and
  repeat incidents with the same cause.

### Resilience Testing

- **Load tests** find each component's knee and confirm headroom to survive a zone loss
  at peak.
- **Chaos experiments** start from a hypothesis ("losing one cache node raises p99 by
  less than 20%"), limit the blast radius, define abort conditions, and run in staging
  before production.
- **Game days** rehearse failover, restore-from-backup and runbooks with the people who
  will be on call.

---

## The Three Ways

From The Phoenix Project / DevOps Handbook:

### First Way: Flow
**Principle:** Optimize left-to-right flow (dev → ops → customer)

**Practices:**
- Make work visible (Kanban)
- Limit WIP
- Reduce batch sizes
- Reduce handoffs
- Identify and elevate constraints
- Eliminate waste

### Second Way: Feedback
**Principle:** Enable fast, constant feedback right-to-left

**Practices:**
- See problems as they occur
- Swarm and solve problems
- Push quality closer to source
- Create shared goals (ops metrics for devs)
- Enable telemetry everywhere

### Third Way: Continuous Learning
**Principle:** Create culture of experimentation and learning

**Practices:**
- Enable organizational learning
- Transform local discoveries into global improvements
- Inject resilience patterns (chaos engineering)
- Institutionalize improvement
- Create time for improvement

---

## Platform Product Lifecycle

From KubeCon/CloudNativeCon (CNPA):

### 1. Identify Shared Challenges
- Talk to customers (developers)
- Evaluate landscape
- Look for existing solutions to adopt and expand
- Identify highest-friction areas

### 2. Design + Build
- Plan and set milestones
- Communicate progress transparently
- Prefer evolving existing to building brand new
- Start with TVP (Thinnest Viable Platform)

### 3. Gather Feedback
- Measure impact with DORA metrics
- Refine based on data
- Drive adoption through demonstrated value
- Regular developer surveys

### 4. Maintain & Operate
- Provide user support
- Ownership of underlying stack
- Business-critical SLOs
- Minimize migration pain for users
