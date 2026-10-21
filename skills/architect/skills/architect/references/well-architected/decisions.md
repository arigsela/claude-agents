# AWS Well-Architected Decision Trees

## 1. Compute Platform Selection

```
What type of workload?
├── Request-driven (APIs, web)
│   ├── Traffic pattern?
│   │   ├── Spiky / unpredictable → Lambda + API Gateway
│   │   ├── Steady / predictable → ECS Fargate or EKS
│   │   └── High sustained throughput → EC2 with ALB
│   └── Execution time?
│       ├── < 15 minutes → Lambda eligible
│       └── > 15 minutes → Container or EC2
├── Batch / data processing
│   ├── Embarrassingly parallel → AWS Batch (Spot)
│   ├── Complex DAG workflows → Step Functions + Lambda/ECS
│   └── Big data processing → EMR / Glue
├── ML training / inference
│   ├── Training → SageMaker Training / EC2 GPU
│   └── Inference
│       ├── Real-time → SageMaker Endpoints / EC2
│       └── Batch → SageMaker Batch Transform
└── Long-running stateful
    ├── Container-friendly → ECS/EKS on EC2
    └── Requires specific OS/kernel → EC2
```

### Container Orchestration Decision

```
Do you need Kubernetes specifically?
├── Yes (team expertise, ecosystem tools, portability)
│   ├── Manage control plane? → EKS
│   │   ├── Manage nodes? → EKS with managed node groups
│   │   └── Serverless nodes? → EKS with Fargate profiles
│   └── No management at all? → EKS on Fargate
└── No (just need container orchestration)
    ├── Want simplicity? → ECS + Fargate
    ├── Need GPU / specific instances? → ECS + EC2
    └── Occasional tasks? → ECS + Fargate Spot
```

---

## 2. Database Selection

```
Data model requirements?
├── Relational (ACID, complex joins)
│   ├── Compatibility needed?
│   │   ├── MySQL / PostgreSQL → Aurora (preferred) or RDS
│   │   ├── SQL Server / Oracle → RDS
│   │   └── Custom engine → EC2 self-managed
│   ├── Scale requirements?
│   │   ├── Read-heavy → Aurora with read replicas (up to 15)
│   │   ├── Write-heavy → Aurora I/O Optimized
│   │   └── Global → Aurora Global Database
│   └── Serverless / variable? → Aurora Serverless v2
├── Key-value / document (flexible schema)
│   ├── Need single-digit ms latency at any scale? → DynamoDB
│   ├── Need microsecond latency? → DynamoDB + DAX
│   ├── MongoDB compatible? → DocumentDB
│   └── Global replication? → DynamoDB Global Tables
├── Cache / session store
│   ├── Redis features (sorted sets, pub/sub)? → ElastiCache for Redis
│   ├── Simple caching? → ElastiCache for Memcached
│   └── DynamoDB accelerator? → DAX
├── Search
│   ├── Full-text search → OpenSearch Service
│   └── Application search → CloudSearch
├── Graph
│   ├── Property graph + RDF → Neptune
│   └── Knowledge graphs → Neptune
├── Time-series
│   ├── IoT / metrics → Timestream
│   └── Financial data → Timestream or DynamoDB
└── Ledger (immutable history)
    └── Verifiable transaction log → QLDB
```

---

## 3. Storage Architecture

```
What are you storing?
├── Objects (files, images, backups, data lake)
│   ├── Access pattern?
│   │   ├── Frequent access → S3 Standard
│   │   ├── Infrequent (>30 days) → S3 IA
│   │   ├── Archive (>90 days) → S3 Glacier Instant/Flexible
│   │   ├── Deep archive (>180 days) → S3 Glacier Deep Archive
│   │   └── Unknown pattern → S3 Intelligent-Tiering
│   └── Special requirements?
│       ├── Compliance / immutability → S3 Object Lock (WORM)
│       ├── Analytics → S3 + Athena / Lake Formation
│       └── Static website → S3 + CloudFront
├── Block storage (databases, OS)
│   ├── Performance needs?
│   │   ├── General purpose → gp3 (always prefer over gp2)
│   │   ├── High IOPS → io2 Block Express
│   │   └── Throughput optimized → st1
│   └── Instance storage needed? → Instance store (ephemeral)
└── File system (shared access)
    ├── Linux / POSIX → EFS
    ├── Windows (SMB) → FSx for Windows
    ├── High-performance (HPC) → FSx for Lustre
    └── NetApp features → FSx for ONTAP
```

---

## 4. Networking Architecture

```
Connectivity requirements?
├── Multi-VPC within region
│   ├── Few VPCs (< 5) → VPC Peering
│   └── Many VPCs → Transit Gateway
├── Multi-region
│   ├── VPC connectivity → Inter-region Transit Gateway Peering
│   ├── Global routing → Global Accelerator
│   └── Content delivery → CloudFront
├── Hybrid (on-premises)
│   ├── Quick setup / backup → Site-to-Site VPN
│   ├── Consistent performance → Direct Connect
│   ├── Both (resilience) → Direct Connect + VPN backup
│   └── Many sites → AWS Cloud WAN
├── Service-to-service (private)
│   ├── AWS service access → VPC Endpoints (Gateway or Interface)
│   ├── Cross-account service → PrivateLink
│   └── Service mesh → App Mesh or EKS + Istio
└── DNS
    ├── Public zones → Route 53
    ├── Private zones → Route 53 Private Hosted Zones
    └── Hybrid DNS → Route 53 Resolver endpoints
```

### Load Balancer Selection

```
Traffic type?
├── HTTP/HTTPS (Layer 7)
│   ├── Path/host-based routing → ALB
│   ├── gRPC support → ALB
│   └── WebSocket → ALB
├── TCP/UDP (Layer 4)
│   ├── Ultra-low latency → NLB
│   ├── Static IP required → NLB
│   └── PrivateLink → NLB
└── Legacy EC2-Classic → CLB (migrate to ALB/NLB)
```

---

## 5. Security Architecture

```
Identity & access approach?
├── Human access
│   ├── Workforce (employees) → IAM Identity Center (SSO)
│   ├── Customers → Cognito User Pools
│   └── Partners → Cognito or Identity Center with external IdP
├── Machine / service access
│   ├── AWS service-to-service → IAM Roles
│   ├── EC2 workloads → Instance profiles
│   ├── EKS pods → IRSA (IAM Roles for Service Accounts)
│   ├── Lambda → Execution role
│   └── Cross-account → Assume role with external ID
└── Secrets management
    ├── Credentials with rotation → Secrets Manager
    ├── Configuration values → Parameter Store (free tier)
    └── Hardware-backed keys → CloudHSM
```

### Encryption Strategy

```
Data state?
├── At rest
│   ├── S3 → SSE-S3 (default) or SSE-KMS for compliance
│   ├── EBS → KMS encryption (enable by default via account setting)
│   ├── RDS/Aurora → KMS encryption at creation
│   ├── DynamoDB → AWS owned key (default) or CMK
│   └── Key management → KMS CMKs, automatic rotation enabled
└── In transit
    ├── External → TLS 1.2+ (ACM certificates)
    ├── Internal → TLS between services
    ├── VPC traffic → VPC encryption (Nitro instances)
    └── Database → Enforce SSL connections
```

---

## 6. Disaster Recovery Strategy

```
What is your RTO/RPO requirement?
├── RTO: hours, RPO: hours
│   └── Backup & Restore
│       - AWS Backup for automated backups
│       - S3 Cross-Region Replication for critical data
│       - CloudFormation/CDK for infrastructure rebuild
│       - Cost: $ (storage only)
├── RTO: 10s of minutes, RPO: minutes
│   └── Pilot Light
│       - Core infrastructure running (DB replicas, minimal compute)
│       - Scale up on failover
│       - Route 53 health checks for detection
│       - Cost: $$
├── RTO: minutes, RPO: seconds
│   └── Warm Standby
│       - Scaled-down but fully functional copy
│       - Scale up to production on failover
│       - Aurora Global Database for cross-region
│       - Cost: $$$
└── RTO: near zero, RPO: near zero
    └── Multi-Site Active-Active
        - Full production in multiple regions
        - Route 53 latency or weighted routing
        - DynamoDB Global Tables
        - Conflict resolution strategy required
        - Cost: $$$$
```

---

## 7. Cost Optimization Strategy

```
What is your spending concern?
├── Overall reduction
│   ├── Check Compute Optimizer for right-sizing
│   ├── Review Trusted Advisor cost recommendations
│   ├── Enable S3 Intelligent-Tiering
│   └── Implement tagging → Cost Explorer analysis
├── Compute costs
│   ├── Predictable baseline → Savings Plans (Compute)
│   ├── Specific instances → Reserved Instances
│   ├── Fault-tolerant workloads → Spot Instances
│   ├── ARM-compatible → Graviton (20% cheaper)
│   └── Variable demand → Lambda / Fargate Spot
├── Data transfer costs
│   ├── S3/DynamoDB access → Gateway VPC Endpoints (free)
│   ├── Internet egress → CloudFront (cheaper than direct)
│   ├── Cross-AZ traffic → AZ-aware routing
│   └── Large data movement → Direct Connect (predictable)
├── Storage costs
│   ├── Unpredictable access → S3 Intelligent-Tiering
│   ├── Old data → Lifecycle to Glacier
│   ├── EBS → Switch gp2 to gp3
│   └── Snapshots → Review and delete unused
└── Database costs
    ├── Variable workloads → Aurora Serverless v2
    ├── Dev/staging → Stop instances off-hours
    ├── Read-heavy → Read replicas + caching
    └── Massive scale → DynamoDB on-demand → provisioned when stable
```

---

## 8. Observability Architecture

```
What do you need to observe?
├── Infrastructure metrics
│   ├── AWS resources → CloudWatch Metrics
│   ├── Custom metrics → CloudWatch (embedded metric format)
│   └── Prometheus-compatible → Amazon Managed Prometheus
├── Application traces
│   ├── AWS-native → X-Ray
│   ├── OpenTelemetry → X-Ray (OTEL collector)
│   └── Vendor (Datadog, etc.) → Agent-based
├── Logs
│   ├── Application logs → CloudWatch Logs
│   ├── Centralized analysis → CloudWatch Logs Insights
│   ├── Long-term archive → S3 (via subscription filter)
│   └── Real-time processing → Kinesis Data Streams
├── Dashboards
│   ├── AWS-native → CloudWatch Dashboards
│   ├── Advanced visualization → Amazon Managed Grafana
│   └── Business metrics → CloudWatch + custom dashboards
└── Alerting
    ├── Metric-based → CloudWatch Alarms
    ├── Anomaly-based → CloudWatch Anomaly Detection
    ├── Composite → CloudWatch Composite Alarms
    └── Routing → SNS → Lambda / PagerDuty / Slack
```
