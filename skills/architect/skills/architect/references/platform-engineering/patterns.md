# Platform Engineering Patterns & Anti-Patterns

## Table of Contents
1. [Golden Path Patterns](#golden-path-patterns)
2. [Self-Service Patterns](#self-service-patterns)
3. [GitOps Patterns](#gitops-patterns)
4. [Platform Team Patterns](#platform-team-patterns)
5. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)

---

## Golden Path Patterns

### Pattern: Opinionated Defaults with Escape Hatches

**Problem:** Developers need guidance but also flexibility for edge cases.

**Solution:**
```
Golden Path (default)     Escape Hatch (opt-out)
├── Standard Helm chart   ├── Custom values.yaml
├── Default resource      ├── Resource override
│   limits                │   annotations
├── Standard CI pipeline  ├── Custom pipeline steps
└── Default observability └── Additional dashboards
```

**Implementation:**
- 80% of use cases work with defaults
- 20% can customize via well-documented mechanisms
- Track escape hatch usage to identify golden path gaps

### Pattern: Template Layering

**Problem:** Different app types need different configurations.

**Solution:**
```
Base Template (all apps)
├── Language Template (Python, Node, Go)
│   ├── Framework Template (FastAPI, Express, Gin)
│   │   └── App-specific overrides
```

**Benefits:**
- Changes to base propagate to all
- Language-specific best practices centralized
- Teams customize only what's unique

### Pattern: Scaffolding with Generators

**Problem:** New projects need consistent structure.

**Solution:**
```bash
# Example: Backstage software template
platform create app \
  --template=python-fastapi \
  --name=my-service \
  --team=payments
```

**Generates:**
- Application code structure
- CI/CD pipeline configuration
- Kubernetes manifests
- Observability dashboards
- Documentation skeleton

---

## Self-Service Patterns

### Pattern: PR-Based Provisioning

**Problem:** Developers need resources but shouldn't have direct cloud access.

**Solution:**
```
Developer           Platform Repo         Automation
    │                    │                    │
    ├─ Create PR ──────► │                    │
    │  (add service)     │                    │
    │                    ├─ Validate ─────────►
    │                    │  (policy check)    │
    │◄─ Auto-approve ────┤                    │
    │   or review        │                    │
    │                    ├─ Merge ───────────►│
    │                    │                    ├─ Provision
    │◄─────────────────────────────────────────┤
    │  (resource ready)                        │
```

**Benefits:**
- Git as audit trail
- Policy enforcement automated
- No direct cloud console access needed

### Pattern: API-First Platform

**Problem:** Multiple interfaces need consistent behavior.

**Solution:**
```
                    Platform API
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    Developer        CLI Tool         Portal UI
      Portal
```

**Implementation:**
- All actions go through API
- UI/CLI are thin clients
- Enables automation and integration

### Pattern: Catalog-Driven Discovery

**Problem:** Developers don't know what's available.

**Solution:**
```
Service Catalog
├── Infrastructure
│   ├── Databases (RDS, DynamoDB)
│   ├── Caching (Redis, Memcached)
│   └── Messaging (SQS, Kafka)
├── Platform Services
│   ├── Authentication
│   ├── Feature Flags
│   └── A/B Testing
└── Developer Tools
    ├── CI/CD Templates
    ├── Observability Dashboards
    └── Development Environments
```

**Each entry includes:**
- Description and use cases
- Self-service provisioning link
- Documentation
- Support contact

---

## GitOps Patterns

### Pattern: App of Apps

**Problem:** Managing many applications in ArgoCD.

**Solution:**
```
Root Application
├── App: team-a-apps
│   ├── service-1
│   ├── service-2
│   └── service-3
├── App: team-b-apps
│   ├── service-4
│   └── service-5
└── App: platform-services
    ├── ingress-controller
    ├── cert-manager
    └── external-secrets
```

**Benefits:**
- Hierarchical organization
- Team-level permissions
- Single source of truth

### Pattern: Environment Promotion

**Problem:** Promoting changes across environments safely.

**Solution:**
```
Git Repository Structure:
├── base/                 # Common manifests
├── overlays/
│   ├── dev/             # Dev-specific
│   ├── staging/         # Staging-specific
│   └── prod/            # Prod-specific
└── applications/
    ├── dev.yaml         # Points to overlays/dev
    ├── staging.yaml     # Points to overlays/staging
    └── prod.yaml        # Points to overlays/prod
```

**Promotion flow:**
1. PR to `overlays/dev` → auto-merge
2. Test in dev
3. PR to `overlays/staging` → auto-merge
4. Test in staging
5. PR to `overlays/prod` → requires approval

### Pattern: Config vs Code Separation

**Problem:** Application code and deployment config have different lifecycles.

**Solution:**
```
app-repo/               deploy-repo/
├── src/                ├── services/
├── tests/              │   └── my-app/
├── Dockerfile          │       ├── base/
└── .github/            │       └── overlays/
    └── workflows/      └── argocd/
        └── build.yaml      └── my-app.yaml

CI builds image → Updates deploy-repo → ArgoCD syncs
```

**Benefits:**
- App teams own app code
- Platform team owns deployment patterns
- Clear separation of concerns

---

## Platform Team Patterns

### Pattern: Embedded Platform Engineers

**Problem:** Platform team disconnected from developer needs.

**Solution:**
- Rotate platform engineers into stream-aligned teams (2-4 weeks)
- Embedded engineer identifies friction points
- Brings learnings back to platform team
- Creates empathy and understanding

### Pattern: Office Hours + Documentation

**Problem:** Scaling platform team support.

**Solution:**
```
Support Model:
├── Self-service (80%)
│   ├── Documentation
│   ├── Runbooks
│   └── FAQs
├── Async support (15%)
│   ├── Slack channel
│   └── Ticket system
└── Synchronous (5%)
    ├── Office hours (scheduled)
    └── Escalation (on-call)
```

**Key:** Invest in documentation to reduce synchronous load.

### Pattern: Platform as Internal Open Source

**Problem:** Platform team can't build everything.

**Solution:**
- Platform team maintains core
- Other teams can contribute
- PR-based contribution model
- Platform team reviews and merges

**Governance:**
- Contribution guidelines
- Review SLAs
- Maintainer responsibilities

---

## Anti-Patterns to Avoid

### Anti-Pattern: Mandate Without Value

**Symptom:** "All teams must use the platform" without demonstrating benefit.

**Problem:** Forces adoption creates resentment; teams find workarounds.

**Solution:** Demonstrate value first; let adoption be organic. If teams aren't adopting, the platform isn't solving real problems.

### Anti-Pattern: Platform as Bottleneck

**Symptom:** Platform team reviews/approves all changes.

**Problem:** Platform team becomes the constraint; defeats self-service goal.

**Solution:** Automate policy enforcement. Platform team should be consulted, not a gate.

### Anti-Pattern: Big Bang Platform

**Symptom:** Multi-year platform project before any delivery.

**Problem:** Requirements change; no feedback; massive risk.

**Solution:** TVP (Thinnest Viable Platform). Deliver incrementally. Get feedback early.

### Anti-Pattern: Technology-First

**Symptom:** "We need Kubernetes/Backstage/ArgoCD" without problem statement.

**Problem:** Solution looking for a problem.

**Solution:** Start with developer pain points. Choose technology that addresses them.

### Anti-Pattern: Ignoring Existing Tools

**Symptom:** Building custom solutions when mature tools exist.

**Problem:** Wasted effort; maintenance burden; worse than OSS alternatives.

**Solution:** Adopt existing tools first. Build custom only for unique requirements.

### Anti-Pattern: Platform Monolith

**Symptom:** Single platform team owns everything.

**Problem:** Bottleneck; cognitive overload; single point of failure.

**Solution:** Federated model. Core platform team + specialized teams (data platform, ML platform, etc.).

### Anti-Pattern: No Feedback Loop

**Symptom:** Platform team ships features without measuring impact.

**Problem:** No way to know if platform is helping.

**Solution:** Measure DORA metrics, developer satisfaction, adoption rates. Use data to prioritize.

### Anti-Pattern: Premature Abstraction

**Symptom:** Building abstractions before understanding the problem space.

**Problem:** Wrong abstractions are worse than none.

**Solution:** Let patterns emerge from 3+ concrete use cases before abstracting.

---

## Implementation Checklist

When implementing any pattern, verify:

- [ ] Solves a real developer pain point (not theoretical)
- [ ] Aligned with TVP principle (minimal viable first)
- [ ] Provides self-service capability
- [ ] Includes appropriate guardrails
- [ ] Has measurable success criteria (DORA, adoption, satisfaction)
- [ ] Documented for discoverability
- [ ] Has clear ownership and support model
