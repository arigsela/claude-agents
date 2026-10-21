# DevOps Maturity Journey -- Deep Dive Reference

Source: [jpswade/DevOps Best Practices](https://gist.github.com/jpswade/4135841363e72ece8086146bd7bb5d91)

This reference provides detailed assessment criteria, key questions, and remediation guidance for each stage of the DevOps maturity journey.

---

## Stage 1: Waterfall to Agile (Foundation)

### Assessment Questions
- Do teams own products end-to-end, or are they temporary project teams?
- Is everything (code, config, docs) in version control?
- Do teams practice blameless post-mortems after incidents?
- Are releases small and frequent, or large and quarterly?
- Does the team structure reflect the desired system architecture (Conway's Law)?
- Are teams small enough (6-10 people) to maintain ownership and agility?

### Key Practices Detail

**Products not projects:** Long-lived teams that own a service or product from inception through production operations. The team doesn't disband after a milestone.

**Culture:** DevOps culture breaks down silos through shared responsibility. Success depends on building autonomous, empowered teams -- not just buying tools.

**Domain Driven Design:** Align service boundaries with business domains using bounded contexts. This creates a common language between business and engineering, enabling meaningful service decomposition.

**Blameless Post-Mortems:** Focus on systemic causes of failure, not individual blame. This builds trust and psychological safety, enabling teams to surface problems early.

**Sacrificial Architecture:** Accept that early system designs will be replaced. Build for today's needs with clean interfaces that allow future replacement.

**Shu-Ha-Ri Learning Model:** Teams learn in stages -- first by following established practices (Shu), then by understanding underlying principles (Ha), and finally by innovating beyond the rules (Ri).

### Red Flags
- Blame-driven incident response
- Releases that require "all hands on deck" war rooms
- Separate teams for dev, QA, and ops with formal handoffs
- Knowledge silos -- only one person understands a system

---

## Stage 2: Agile to Lean (Eliminate Waste)

### Assessment Questions
- Are retrospectives driving measurable change, or are they just rituals?
- Does the team track DORA metrics (deployment frequency, lead time, MTTR, change failure rate)?
- Is technical debt tracked and deliberately addressed?
- Are teams cross-functional, or do they depend on external teams for testing, security, or ops?
- Is there a culture of experimentation and safe failure?

### Key Practices Detail

**Continuous Improvement (Kaizen):** Not just retrospectives -- ongoing, incremental improvement involving every team member. Small daily changes accumulate into transformative results.

**DORA Metrics / KPIs:** The four key metrics that predict software delivery performance:
- Deployment frequency: How often code deploys to production
- Lead time for changes: Time from commit to production
- Mean time to recovery (MTTR): Time to restore service after an incident
- Change failure rate: Percentage of deployments causing a failure

**Test at the appropriate level:** Follow the test pyramid:
- Base: Many fast unit tests
- Middle: Fewer integration tests
- Top: Minimal end-to-end / UI tests
- Anti-pattern: Ice cream cone (mostly manual/E2E tests)

**Technical Debt:** Treat it like financial debt -- track it, understand its interest rate (how much it slows you down), and deliberately allocate capacity to pay it down.

### Red Flags
- No metrics or KPIs for delivery performance
- Retrospectives that generate action items nobody follows up on
- QA bottleneck -- features waiting weeks for testing
- "We'll fix it later" culture with no mechanism to actually fix it later

---

## Stage 3: Lean to Continuous Integration

### Assessment Questions
- Do developers commit to a shared mainline at least daily?
- Does every commit trigger an automated build and test suite?
- Are build failures fixed within 10 minutes?
- Is infrastructure reproducible and disposable (cattle, not pets)?
- Are tests automated, fast, and reliable?

### Key Practices Detail

**Cattle not pets:** Infrastructure is disposable and reproducible. Any server can be destroyed and recreated from code. No hand-configured snowflakes.

**True CI (not CI theater):** Jez Humble's CI certification test:
1. Commit to shared mainline at least daily
2. Every commit triggers automated build + tests
3. Failures are fixed within 10 minutes

If any of these are false, you're not doing CI -- you're doing "CI theater" (usually feature branch builds).

**Quality Built In:** Don't inspect quality in at the end. Build it in from the start through:
- Pair programming / code review
- TDD / BDD
- Static analysis in the pipeline
- Security scanning (shift left)

**Shift Left:** Move testing, security, and quality checks as early as possible in the development lifecycle. Finding issues in development is 10-100x cheaper than finding them in production.

### Red Flags
- Long-lived feature branches (weeks or months)
- "Integration day" or "merge hell" before releases
- Flaky tests that are ignored or disabled
- Manual test gates blocking deployments
- Snowflake servers that can't be reproduced

---

## Stage 4: Continuous Integration to Continuous Delivery

### Assessment Questions
- Can any successful build be deployed to production with one click (or command)?
- Are deployment pipelines fully automated from commit to production-ready?
- Is trunk-based development practiced (short-lived branches or direct trunk commits)?
- Is everything defined as code (infra, config, pipelines, monitoring)?
- Are security checks integrated into the pipeline?
- Is the team optimizing for MTTR over MTBF (recovery speed over failure prevention)?

### Key Practices Detail

**Deployment Pipelines:** The core CD pattern -- automate the path from version control through build, test, and deploy stages. Key principles:
- Incremental releases through decoupled deployment
- Reduced batch size through frequent deployments
- Optimized for resilience -- accept failures as learning opportunities

**Trunk-Based Development:** Work on a shared mainline. If branches are used, they should be short-lived (< 1 day). This enables true CI and reduces merge conflicts.

**Everything as Code:** Not just application code -- infrastructure (Terraform, Pulumi), CI/CD pipelines (Jenkinsfile, GitHub Actions), monitoring (Grafana dashboards as code), alerts, and compliance policies.

**Focus on MTTR:** Shift from "prevent all failures" to "detect and recover fast." Key strategies:
- Feature toggles for instant rollback
- Blue-green deployments
- Comprehensive observability (metrics, logs, traces)
- Automated rollback on health check failure

**Pipelines as Code:** CI/CD pipelines defined in version-controlled files, not configured through a GUI. This enables review, testing, versioning, and reuse of pipeline definitions.

### Red Flags
- Deployments require manual steps or approvals that take days
- Pipeline configuration lives only in the CI tool's GUI
- Security is a separate gate at the end, not integrated into the pipeline
- "Release day" is a stressful event requiring coordination

---

## Stage 5: Continuous Delivery to Continuous Deployment

### Assessment Questions
- Does every successful pipeline run automatically deploy to production?
- Are feature toggles used to decouple deployment from feature release?
- Is all infrastructure provisioned via code?
- Does "done" mean "released to production" for the team?

### Key Practices Detail

**Feature Toggles:** Runtime configuration controlling feature visibility without redeployment. Types:
- Release toggles: Hide incomplete features in production
- Experiment toggles: A/B testing
- Ops toggles: Kill switches for degraded mode
- Permission toggles: Feature access by user segment

Best practice: Feature toggles should be temporary. Remove them once the feature is fully rolled out.

**Infrastructure as Code:** All infrastructure defined in version-controlled code:
- Provisioning: Terraform, Pulumi, CloudFormation, CDK
- Configuration: Ansible, Chef, Puppet, Salt
- Containers: Dockerfile, docker-compose.yml
- Orchestration: Kubernetes manifests, Helm charts

**Done = Released:** A cultural shift where features aren't considered complete until they're running in production and delivering value. The definition of done includes deployment, monitoring, and user validation.

### Red Flags
- Features are "done" when they merge to main, not when they reach production
- No feature toggle strategy -- incomplete features block releases
- Infrastructure provisioned manually or through click-ops
- Inconsistency between what's in code and what's actually deployed (drift)

---

## Stage 6: Continuous Deployment to Continuous Operations

### Assessment Questions
- Are deployments zero-downtime (blue-green, canary, rolling)?
- Do developers carry pagers / participate in on-call rotations?
- Is the system designed for failure (circuit breakers, retries, graceful degradation)?
- Is infrastructure immutable (replaced, never patched)?
- Is performance testing integrated into the pipeline?
- Is there a self-service platform for developers?

### Key Practices Detail

**Blue-Green Deployments:** Two identical production environments. Deploy to the idle one, run smoke tests, then switch traffic. Instant rollback by switching back.

**Developers on Call:** "You build it, you run it." Creates feedback loops where the people who write the code experience its operational behavior. Drives better error handling, logging, and operability.

**Design for Failure:** Microservices must tolerate service failures:
- Circuit breakers prevent cascading failures
- Retries with exponential backoff handle transient errors
- Bulkheads isolate failure to prevent system-wide impact
- Chaos engineering proactively discovers weaknesses

**Immutable Infrastructure:** Never patch or modify running infrastructure. Instead:
1. Build a new image/artifact with the change
2. Deploy the new version alongside the old
3. Switch traffic to the new version
4. Destroy the old version

This eliminates configuration drift and ensures reproducibility.

**Data-Driven Decisions:** Use observability data (metrics, logs, traces) and business analytics to inform product and operational decisions. Move beyond gut feeling to evidence-based engineering.

### Red Flags
- Deployments require downtime or maintenance windows
- Only ops carries the pager; developers are never on call
- No chaos engineering or resilience testing
- Servers are patched in-place, creating snowflakes
- Performance testing happens only before major releases (or never)

---

## Maturity Assessment Template

Use this template for a quick organizational assessment:

```
Organization: _______________
Date: _______________
Assessed by: _______________

Stage 1 - Agile Foundation:     [ ] Not Adopted  [ ] Partial  [ ] Adopted
Stage 2 - Lean Practices:       [ ] Not Adopted  [ ] Partial  [ ] Adopted
Stage 3 - Continuous Integration:[ ] Not Adopted  [ ] Partial  [ ] Adopted
Stage 4 - Continuous Delivery:   [ ] Not Adopted  [ ] Partial  [ ] Adopted
Stage 5 - Continuous Deployment: [ ] Not Adopted  [ ] Partial  [ ] Adopted
Stage 6 - Continuous Operations: [ ] Not Adopted  [ ] Partial  [ ] Adopted

Overall Maturity: Stage ___
Target Maturity:  Stage ___

Top 3 Gaps:
1.
2.
3.

Recommended Next Steps:
1.
2.
3.
```
