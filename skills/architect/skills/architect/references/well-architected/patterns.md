# AWS Well-Architected Implementation Patterns

## Architecture Patterns

### 1. Three-Tier Web Application

```
[CloudFront] → [ALB] → [ECS/EKS (app tier)] → [Aurora (data tier)]
                                ↓
                         [ElastiCache (cache)]
```

**Best practices:**
- CloudFront for static assets + API caching
- ALB with WAF for application-layer protection
- ECS Fargate for container workloads (EKS if K8s required)
- Aurora Multi-AZ for database with read replicas
- ElastiCache for session management and query caching
- Secrets Manager for database credentials

**Pillar highlights:**
- Reliability: Multi-AZ at every tier, auto-scaling, health checks
- Security: WAF, private subnets for app/data, encryption everywhere
- Cost: Fargate Spot for non-critical, Savings Plans for baseline

---

### 2. Event-Driven Architecture

```
[Event Sources] → [EventBridge] → [SQS] → [Lambda / ECS]
                       ↓                        ↓
                   [Archive]              [DynamoDB / S3]
```

**Best practices:**
- EventBridge as central event bus with schema registry
- SQS for decoupling and buffering (with DLQ for failures)
- Lambda for short-lived event handlers
- ECS for long-running processors
- DLQ + alarm for failed message monitoring

**Pillar highlights:**
- Reliability: Loose coupling, retry with backoff, DLQ for poison messages
- Performance: Scales independently per component
- Cost: Pay-per-event, no idle compute with Lambda

---

### 3. Data Lake / Lakehouse

```
[Sources] → [Kinesis/Glue] → [S3 Raw] → [Glue ETL] → [S3 Curated]
                                                            ↓
                                                   [Athena / Redshift]
                                                            ↓
                                                     [QuickSight]
```

**Best practices:**
- S3 as central storage with Lake Formation for governance
- Glue Data Catalog as unified metadata store
- Glue ETL or EMR for transformation
- Athena for ad-hoc SQL queries (pay per query)
- Redshift Serverless for complex analytics
- Lake Formation for fine-grained access control

**Pillar highlights:**
- Cost: S3 tiering, Athena pay-per-query, Redshift Serverless
- Security: Lake Formation column/row-level security, encryption
- Sustainability: Columnar formats (Parquet) reduce data scanned

---

### 4. Serverless API

```
[CloudFront] → [API Gateway] → [Lambda] → [DynamoDB]
                    ↓                          ↓
              [Cognito Auth]            [DynamoDB Streams]
                                              ↓
                                          [Lambda (async)]
```

**Best practices:**
- API Gateway with usage plans and throttling
- Cognito for authentication + JWT authorizer
- Lambda with Powertools (logging, tracing, metrics)
- DynamoDB single-table design for performance
- DynamoDB Streams for change data capture

**Pillar highlights:**
- Operational Excellence: Zero server management, built-in scaling
- Cost: Pay per request, zero cost at zero traffic
- Performance: Provisioned concurrency for cold start-sensitive paths

---

### 5. Multi-Region Active-Active

```
[Route 53 (latency routing)]
     ├── Region A                    ├── Region B
     │   [ALB → ECS]                │   [ALB → ECS]
     │   [Aurora Primary]           │   [Aurora Read Replica]
     │   [DynamoDB Global]          │   [DynamoDB Global]
     │   [ElastiCache]              │   [ElastiCache]
```

**Best practices:**
- Route 53 latency-based routing with health checks
- DynamoDB Global Tables for multi-region data (last-writer-wins)
- Aurora Global Database (RPO < 1s, RTO < 1 min)
- Separate ElastiCache cluster per region
- Stateless application tier for region-agnostic routing
- Conflict resolution strategy for concurrent writes

**Pillar highlights:**
- Reliability: Near-zero RTO/RPO, survives full region failure
- Performance: Users routed to closest region
- Cost: 2x+ infrastructure cost, justify with business requirements

---

### 6. CI/CD Pipeline

```
[CodeCommit/GitHub] → [CodeBuild] → [CodeDeploy / ECS Deploy]
                          ↓                    ↓
                     [ECR (images)]     [CloudFormation / CDK]
                          ↓
                    [Security Scan]
```

**Best practices:**
- Infrastructure as Code: CDK (preferred) or CloudFormation
- Immutable deployments: new AMI/container per release
- Blue/green or canary deployments for zero-downtime
- Security scanning in pipeline: CodeGuru, Snyk, Trivy
- Separate accounts for dev, staging, prod (AWS Organizations)
- Automated rollback on CloudWatch alarm

---

## Security Patterns

### Defense in Depth

```
Layer 1: Edge         → CloudFront + WAF + Shield
Layer 2: Network      → VPC, subnets, SGs, NACLs, Network Firewall
Layer 3: Identity     → IAM, SCP, permission boundaries
Layer 4: Application  → Input validation, parameterized queries
Layer 5: Data         → Encryption at rest + transit, key management
Layer 6: Monitoring   → GuardDuty, Security Hub, CloudTrail
```

### Zero Trust Network

- No implicit trust based on network location
- Every request authenticated and authorized
- VPC endpoints + PrivateLink for service-to-service
- IRSA for pod-level identity in EKS
- mTLS via App Mesh or service mesh
- Just-in-time access with IAM Identity Center + SSO

### Compliance Automation

```
[AWS Config Rules] → [Non-compliant detected]
        ↓
[EventBridge] → [Lambda auto-remediation]
        ↓
[Security Hub] → [Aggregated findings dashboard]
        ↓
[Audit Manager] → [Compliance reports]
```

---

## Cost Optimization Patterns

### Tagging Strategy

```
Required Tags:
  - Environment: dev | staging | prod
  - Team: engineering | data | platform
  - CostCenter: CC-1234
  - Workload: api | web | pipeline
  - Owner: team-email

Enforcement:
  - Tag Policies via AWS Organizations
  - SCP to deny untagged resource creation
  - AWS Config rule for compliance checking
```

### Scheduling Pattern (Dev/Staging)

```
[EventBridge Scheduler] → [Lambda]
     ↓                       ↓
  Cron: stop at 7PM    Stop: RDS, EC2, ECS (desired=0)
  Cron: start at 7AM   Start: RDS, EC2, ECS (desired=N)

Savings: 50-65% on non-prod compute
```

### Spot Instance Pattern

```
[ASG with mixed instances policy]
  ├── On-Demand: 20% (baseline)
  ├── Spot: 80% (diversified across 4+ instance types)
  └── Capacity Rebalancing: enabled

Best for: Stateless workloads, batch processing, CI/CD runners
Not for: Databases, stateful single-instance workloads
```

---

## Reliability Patterns

### Circuit Breaker

```
[Service A] → [Circuit Breaker] → [Service B]
                    ↓
             [State: Closed]     → Normal flow
             [State: Open]       → Return cached/default response
             [State: Half-Open]  → Test with limited traffic
```

Implementation: Use Step Functions, Lambda Powertools, or application-level libraries.

### Bulkhead Isolation

```
[Workload]
  ├── Critical path (isolated resources)
  │   ├── Dedicated ALB
  │   ├── Separate ECS service / ASG
  │   └── Reserved DB connections
  └── Best-effort path (shared resources)
      ├── Shared ALB
      └── Shared compute pool
```

### Retry with Backoff and Jitter

```
Base delay: 100ms
Retry 1: random(0, 200ms)
Retry 2: random(0, 400ms)
Retry 3: random(0, 800ms)
Max retries: 3
Max delay cap: 5s

Key: Add jitter to prevent thundering herd
```

---

## Anti-Patterns to Avoid

### 1. Lift and Shift Without Optimization
**Problem**: Moving on-prem architecture to AWS unchanged.
**Fix**: Re-architect for cloud-native services. Start with managed services for databases, caching, messaging.

### 2. Single AZ Deployment
**Problem**: All resources in one AZ.
**Fix**: Multi-AZ for every tier. Use ALB/NLB for distribution. Aurora Multi-AZ, ElastiCache Multi-AZ.

### 3. Over-Permissive IAM
**Problem**: `Action: *`, `Resource: *` policies.
**Fix**: Least privilege. Use IAM Access Analyzer, policy generation from CloudTrail, SCPs as guardrails.

### 4. No Encryption Strategy
**Problem**: Inconsistent or missing encryption.
**Fix**: Default encryption on all storage services. KMS CMKs with rotation. TLS everywhere. Account-level EBS default encryption.

### 5. Manual Infrastructure
**Problem**: ClickOps - creating resources through the console.
**Fix**: 100% IaC with CDK or Terraform. No manual changes to production. Use Service Catalog for self-service.

### 6. Monolithic Database
**Problem**: Single large RDS instance for all services.
**Fix**: Purpose-built databases per service. Use DynamoDB for key-value, Aurora for relational, ElastiCache for caching.

### 7. Ignoring Data Transfer Costs
**Problem**: Unexpected cross-AZ and internet egress charges.
**Fix**: VPC endpoints, CloudFront for egress, AZ-aware routing, compress before transfer.

### 8. No Cost Governance
**Problem**: Uncontrolled cloud spending, no visibility.
**Fix**: Mandatory tagging, AWS Budgets with alerts, regular cost reviews, Savings Plans for baseline.

### 9. Treating Cloud Like a Data Center
**Problem**: Fixed-size infrastructure, no auto-scaling.
**Fix**: Auto-scaling at every tier, serverless where appropriate, right-size continuously.

### 10. Security as Afterthought
**Problem**: Security review only at the end.
**Fix**: Security in CI/CD pipeline, automated compliance checks, shift-left security testing, threat modeling at design time.

---

## Review Checklist

Before declaring an architecture Well-Architected, verify:

### Operational Excellence
- [ ] All infrastructure defined as code
- [ ] CI/CD pipeline with automated testing
- [ ] Observability (metrics, logs, traces) for all components
- [ ] Runbooks for common failure scenarios
- [ ] Deployment strategy supports rollback

### Security
- [ ] Least privilege IAM policies
- [ ] Encryption at rest and in transit for all data
- [ ] Network segmentation (private subnets for data/app tiers)
- [ ] Detection enabled (GuardDuty, Security Hub, CloudTrail)
- [ ] Incident response plan documented and tested

### Reliability
- [ ] Multi-AZ deployment for all critical components
- [ ] Auto-scaling configured with appropriate metrics
- [ ] Backup strategy with tested restore procedures
- [ ] Disaster recovery plan with defined RTO/RPO
- [ ] Health checks and automated healing

### Performance Efficiency
- [ ] Right-sized compute, storage, and database
- [ ] Caching strategy (CloudFront, ElastiCache, API cache)
- [ ] Performance testing and benchmarking completed
- [ ] Monitoring for latency, throughput, error rates

### Cost Optimization
- [ ] Resource tagging strategy enforced
- [ ] Savings Plans / RIs for baseline compute
- [ ] Waste elimination review completed
- [ ] Budget alerts configured
- [ ] Cost per unit metric defined and tracked

### Sustainability
- [ ] Utilization targets defined (>70% for steady-state)
- [ ] Data lifecycle policies implemented
- [ ] Efficient data formats used (Parquet over CSV)
- [ ] Right-sized resources (no over-provisioning)
- [ ] Graviton instances evaluated
