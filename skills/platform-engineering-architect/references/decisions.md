# Platform Architecture Decision Trees

## Table of Contents
1. [CI/CD Architecture](#cicd-architecture)
2. [Compute Platform](#compute-platform)
3. [Infrastructure as Code](#infrastructure-as-code)
4. [Observability Stack](#observability-stack)
5. [Developer Portal](#developer-portal)
6. [Secrets Management](#secrets-management)
7. [Multi-Cloud Strategy](#multi-cloud-strategy)

---

## CI/CD Architecture

### Push vs Pull (GitOps)

```
Need deployment audit trail?
├── Yes → GitOps (ArgoCD, Flux)
└── No
    ├── Simple apps, fast iteration? → Push-based (GitHub Actions, Jenkins)
    └── Complex environments, compliance? → GitOps
```

**GitOps (Pull-Based)**
| Pros | Cons |
|------|------|
| Git as source of truth | Learning curve |
| Audit trail built-in | Secrets handling complexity |
| Drift detection | Debugging requires GitOps knowledge |
| Declarative state | PR workflow overhead |

**Push-Based**
| Pros | Cons |
|------|------|
| Simple to understand | No drift detection |
| Fast iteration | Audit trail requires extra work |
| Familiar to developers | State not in Git |

**Recommendation by Maturity:**
- Early stage: Push-based for speed
- Growth stage: Hybrid (push CI, pull CD)
- Mature: Full GitOps

### Pipeline Tools

```
Cloud provider lock-in acceptable?
├── Yes
│   ├── AWS → CodePipeline/CodeBuild
│   ├── Azure → Azure Pipelines
│   └── GCP → Cloud Build
└── No
    ├── GitHub-centric? → GitHub Actions
    ├── GitLab-centric? → GitLab CI
    └── Self-hosted required? → Jenkins, Tekton
```

---

## Compute Platform

### Kubernetes vs Alternatives

```
Team has K8s expertise?
├── No
│   ├── Stateless workloads? → Serverless (Lambda, Cloud Run)
│   ├── Simple containers? → Managed containers (ECS, Cloud Run)
│   └── Complex needs? → Managed K8s with platform team abstraction
└── Yes
    ├── Multi-cloud requirement? → Kubernetes
    ├── Advanced scheduling? → Kubernetes
    └── Simple workloads? → Consider serverless for cost
```

### Kubernetes Cluster Strategy

```
Number of environments?
├── 1-2 → Single cluster with namespaces
├── 3-5 → Cluster per environment (dev, staging, prod)
└── 5+ → Consider multi-cluster management (Rancher, OpenShift)

Isolation requirements?
├── Strong (compliance) → Separate clusters
└── Standard → Namespaces with RBAC
```

### Node Provisioning

```
Cloud provider?
├── AWS
│   ├── Predictable workloads → Cluster Autoscaler + node groups
│   └── Variable/bursty → Karpenter
├── GCP → GKE Autopilot or node auto-provisioning
└── Azure → AKS cluster autoscaler
```

**Karpenter vs Cluster Autoscaler (AWS)**
| Aspect | Karpenter | Cluster Autoscaler |
|--------|-----------|-------------------|
| Provisioning speed | Faster (direct EC2) | Slower (ASG) |
| Instance selection | Flexible, cost-optimized | Pre-defined node groups |
| Complexity | Higher | Lower |
| Spot handling | Native | Requires configuration |

---

## Infrastructure as Code

### Tool Selection

```
Multi-cloud requirement?
├── Yes
│   ├── K8s-native preference? → Crossplane
│   └── Traditional IaC? → Terraform
└── No
    ├── AWS-only → Terraform, CDK, or CloudFormation
    ├── Azure-only → Terraform, Bicep, or ARM
    └── GCP-only → Terraform or Deployment Manager
```

### Terraform vs Crossplane

| Aspect | Terraform | Crossplane |
|--------|-----------|------------|
| Paradigm | Imperative runs | Kubernetes reconciliation |
| State | External state file | Kubernetes etcd |
| GitOps integration | Requires wrapper | Native |
| Learning curve | Moderate | Higher (K8s + CRDs) |
| Community | Massive | Growing |

**When to use Crossplane:**
- Already heavily invested in Kubernetes
- Want infrastructure to reconcile like K8s resources
- GitOps-native infrastructure management

**When to use Terraform:**
- Established team expertise
- Non-Kubernetes infrastructure
- Simpler operational model

### Module Strategy

```
Organization size?
├── Small (<50 devs) → Shared module repository
├── Medium (50-200) → Module registry with versioning
└── Large (200+) → Internal provider/module marketplace
```

---

## Observability Stack

### Build vs Buy

```
Budget constraints?
├── Tight → Open source (Prometheus, Grafana, Jaeger)
└── Flexible
    ├── Prefer managed? → Datadog, New Relic, Dynatrace
    └── Prefer control? → Self-hosted with support
```

**Cost Comparison (approximate)**
| Solution | 100 hosts/month | Complexity |
|----------|-----------------|------------|
| Datadog | $5,000-15,000 | Low |
| New Relic | $4,000-12,000 | Low |
| Prometheus+Grafana | $1,000-3,000 (infra) | High |

### OpenTelemetry Strategy

```
Existing instrumentation?
├── None → Start with OTel from day one
├── Vendor-specific → Gradual migration via OTel Collector
└── Mixed → Consolidate through OTel Collector
```

**OTel Collector Pattern:**
```
Apps → OTel Collector → Multiple backends
                     ├── Prometheus (metrics)
                     ├── Jaeger (traces)
                     └── Loki (logs)
```

### Alerting Architecture

```
SLO-based alerting?
├── Yes → Error budget burn rate alerts
└── No → Traditional threshold alerts

Alert routing?
├── Simple → PagerDuty/Opsgenie direct
└── Complex → AlertManager → routing rules → escalation
```

---

## Developer Portal

### Build vs Adopt

```
Customization needs?
├── High → Custom build or heavily extended Backstage
├── Medium → Backstage with plugins
└── Low → Commercial (Port, Cortex, OpsLevel)
```

### Backstage vs Alternatives

| Aspect | Backstage | Port | Cortex |
|--------|-----------|------|--------|
| Cost | Free (OSS) | Commercial | Commercial |
| Setup effort | High | Low | Low |
| Customization | Unlimited | Moderate | Moderate |
| Community | Large | Growing | Growing |
| Support | Community | Vendor | Vendor |

**When to choose Backstage:**
- Engineering capacity to maintain
- Heavy customization needed
- Cost-sensitive
- Want full control

**When to choose commercial:**
- Faster time to value
- Limited platform team capacity
- Prefer vendor support

---

## Secrets Management

### Solution Selection

```
Cloud provider?
├── AWS → AWS Secrets Manager or Parameter Store
├── Azure → Azure Key Vault
├── GCP → Secret Manager
└── Multi-cloud or on-prem → HashiCorp Vault
```

### Kubernetes Integration

```
External secrets needed?
├── Yes → External Secrets Operator
└── No
    ├── Simple needs → Kubernetes Secrets (encrypted at rest)
    └── Rotation needed → Secrets Store CSI Driver
```

**External Secrets Operator Pattern:**
```
Cloud Secret Store → ESO → Kubernetes Secret → Pod
(AWS SM, Vault)     sync    (auto-created)
```

---

## Multi-Cloud Strategy

### When to Go Multi-Cloud

```
Actual requirement?
├── Compliance/regulatory → Yes, proceed carefully
├── Vendor negotiation leverage → Consider, but expensive
├── Disaster recovery → Consider regional diversity first
└── "Best of breed" tools → Usually not worth complexity
```

### Multi-Cloud Approaches

| Approach | Complexity | Use Case |
|----------|------------|----------|
| **Cloud-agnostic abstractions** | High | True portability needed |
| **Primary + DR** | Medium | Compliance, resilience |
| **Workload-specific** | Medium | Best tool for job |
| **Avoid** | Low | Most organizations |

**Abstraction Layers:**
- Kubernetes (compute)
- Terraform (IaC)
- Crossplane (cloud resources)
- OpenTelemetry (observability)

### Migration Strategy

```
Current state?
├── Single cloud, considering multi
│   └── Start with portable patterns (K8s, Terraform)
├── Committed to multi-cloud
│   └── Invest in abstraction layers
└── Already multi-cloud
    └── Consolidate on common tooling
```
