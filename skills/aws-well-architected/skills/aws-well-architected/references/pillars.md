# AWS Well-Architected Framework - Six Pillars Reference

## 1. Operational Excellence

**Focus**: Run and monitor systems to deliver business value, and continually improve supporting processes and procedures.

### Design Principles
- Perform operations as code (IaC)
- Make frequent, small, reversible changes
- Refine operations procedures frequently
- Anticipate failure (game days, chaos engineering)
- Learn from all operational events

### Key Areas

**Organization**
- Evaluate external and internal factors (compliance, governance, threat landscape)
- Define operating model: fully separated, separated with governance, separated with shared services
- Establish organizational culture supporting experimentation and learning

**Prepare**
- Design telemetry: application, workload, user activity, dependency telemetry
- Implement observability: CloudWatch, X-Ray, CloudTrail, OpenTelemetry
- Design for operations: version control, build/test automation, configuration management
- Mitigate deployment risks: blue/green, canary, feature flags, rollback procedures

**Operate**
- Understanding workload health: define KPIs, business and technical metrics
- Understanding operational health: runbook and playbook maturity, on-call processes
- Responding to events: define escalation paths, automate responses where possible
- CloudWatch dashboards, alarms, anomaly detection, composite alarms

**Evolve**
- Learn from experience: post-incident reviews, operational metrics trends
- Make improvements: feedback loops, experimentation, share learnings across teams
- Regular Well-Architected reviews (quarterly recommended)

### Key AWS Services
| Function | Services |
|----------|----------|
| IaC | CloudFormation, CDK, Terraform |
| Observability | CloudWatch, X-Ray, CloudTrail, Managed Grafana, Managed Prometheus |
| Deployment | CodePipeline, CodeDeploy, CodeBuild |
| Automation | Systems Manager, EventBridge, Step Functions, Lambda |
| Configuration | AWS Config, Systems Manager Parameter Store, AppConfig |

---

## 2. Security

**Focus**: Protect information, systems, and assets while delivering business value through risk assessment and mitigation strategies.

### Design Principles
- Implement a strong identity foundation (least privilege)
- Maintain traceability (logging and audit)
- Apply security at all layers (defense in depth)
- Automate security best practices
- Protect data in transit and at rest
- Keep people away from data
- Prepare for security events

### Key Areas

**Identity and Access Management**
- Use AWS Organizations with SCPs for guardrails
- Centralize identity with IAM Identity Center (SSO)
- Enforce MFA everywhere, especially root accounts
- Use IAM roles (not long-lived keys), prefer IRSA for EKS
- Permission boundaries and session policies for delegation
- Regularly review permissions with IAM Access Analyzer

**Detection**
- Enable CloudTrail in all regions, protect log integrity
- GuardDuty for threat detection (enable all protection plans)
- Security Hub for centralized findings and compliance checks
- VPC Flow Logs for network monitoring
- Detective for investigation and root cause analysis
- Macie for sensitive data discovery in S3

**Infrastructure Protection**
- Network segmentation: VPC, subnets, security groups, NACLs
- Use VPC endpoints (gateway and interface) to avoid public internet
- AWS WAF + Shield for DDoS and application-layer protection
- Systems Manager Session Manager instead of SSH bastion hosts
- Network Firewall for stateful inspection and IDS/IPS

**Data Protection**
- Classify data by sensitivity level
- Encrypt at rest: KMS (CMKs), default encryption on all storage services
- Encrypt in transit: TLS 1.2+ everywhere, ACM for certificate management
- S3 Block Public Access (account level), bucket policies, object lock
- Key management: automatic rotation, separate keys per workload/environment
- Secrets Manager for credentials, automatic rotation

**Incident Response**
- Develop incident response plans and playbooks
- Pre-provision forensic tooling (separate account)
- Use AWS Security Incident Response for automated triage
- Tag-based resource identification during incidents
- Regular tabletop exercises and game days

### Key AWS Services
| Function | Services |
|----------|----------|
| Identity | IAM, IAM Identity Center, Organizations, SCP |
| Detection | GuardDuty, Security Hub, CloudTrail, Detective, Macie |
| Network | VPC, WAF, Shield, Network Firewall, Firewall Manager |
| Encryption | KMS, ACM, CloudHSM |
| Secrets | Secrets Manager, Parameter Store |

---

## 3. Reliability

**Focus**: Ensure a workload performs its intended function correctly and consistently when expected, including the ability to operate and test throughout its lifecycle.

### Design Principles
- Automatically recover from failure
- Test recovery procedures
- Scale horizontally to increase aggregate availability
- Stop guessing capacity (use auto-scaling)
- Manage change through automation

### Key Areas

**Foundations**
- Service quotas: monitor with Service Quotas, request increases proactively
- Network topology: sufficient IP space, redundant connectivity (Direct Connect + VPN)
- Account structure: multi-account strategy for blast radius reduction

**Workload Architecture**
- Design for distributed systems: retry with exponential backoff and jitter
- Use bulkhead pattern: isolate failures to prevent cascade
- Implement circuit breakers for dependency failures
- Use queue-based load leveling (SQS) for traffic spikes
- Design for idempotency in all operations

**Change Management**
- Monitor behavior: define SLIs (latency, error rate, throughput, availability)
- Auto-scaling: target tracking policies, predictive scaling for known patterns
- Deploy with automation: immutable infrastructure, blue/green, canary
- Use synthetic monitoring (CloudWatch Synthetics) for proactive detection

**Failure Management**
- Automate healing: ASG health checks, Route 53 failover, ECS task restart
- Test resilience: AWS Fault Injection Service (FIS), chaos engineering
- Backup strategy: automated backups, cross-region replication, test restores
- Disaster recovery strategies by RTO/RPO:

| Strategy | RTO | RPO | Cost |
|----------|-----|-----|------|
| Backup & Restore | Hours | Hours | $ |
| Pilot Light | 10s of min | Minutes | $$ |
| Warm Standby | Minutes | Seconds | $$$ |
| Multi-site Active-Active | Near zero | Near zero | $$$$ |

**Availability Targets**

| Target | Downtime/year | Typical Architecture |
|--------|--------------|---------------------|
| 99% | 3.65 days | Single AZ |
| 99.9% | 8.76 hours | Multi-AZ |
| 99.95% | 4.38 hours | Multi-AZ with auto-healing |
| 99.99% | 52.6 minutes | Multi-Region |
| 99.999% | 5.26 minutes | Multi-Region Active-Active |

### Key AWS Services
| Function | Services |
|----------|----------|
| Scaling | Auto Scaling, ECS/EKS scaling, DynamoDB on-demand |
| Networking | Route 53, Global Accelerator, Direct Connect, Transit Gateway |
| DR | Elastic Disaster Recovery, S3 Cross-Region Replication, Aurora Global |
| Testing | Fault Injection Service (FIS), CloudWatch Synthetics |
| Backup | AWS Backup, RDS snapshots, EBS snapshots |

---

## 4. Performance Efficiency

**Focus**: Use computing resources efficiently to meet system requirements, and maintain that efficiency as demand changes and technologies evolve.

### Design Principles
- Democratize advanced technologies (use managed services)
- Go global in minutes (multi-region, edge)
- Use serverless architectures where appropriate
- Experiment more often
- Consider mechanical sympathy (understand how services work)

### Key Areas

**Compute Selection**

| Workload Type | Recommended Compute | When to Use |
|--------------|-------------------|-------------|
| Request-driven, variable | Lambda | < 15 min, < 10 GB memory, spiky traffic |
| Containerized, steady | ECS Fargate | Predictable containers, no cluster management |
| Containerized, complex | EKS | Service mesh, custom scheduling, team familiarity |
| High performance / GPU | EC2 (custom) | ML training, HPC, specific instance needs |
| Batch processing | AWS Batch | Large-scale parallel compute jobs |

**Storage Selection**

| Storage Type | Service | Use Case |
|-------------|---------|----------|
| Object | S3 (+ tiers) | Static assets, backups, data lake |
| Block | EBS (gp3/io2) | Database volumes, boot volumes |
| File | EFS / FSx | Shared file systems, legacy apps |
| Cache | ElastiCache / DAX | Session store, query cache, real-time |

**Database Selection**

| Pattern | Service | Best For |
|---------|---------|----------|
| Relational | Aurora / RDS | Transactions, complex queries, joins |
| Key-value | DynamoDB | Single-digit ms latency, any scale |
| Document | DocumentDB | MongoDB-compatible, flexible schema |
| In-memory | ElastiCache | Sub-ms latency, caching, leaderboards |
| Graph | Neptune | Relationships, knowledge graphs |
| Time-series | Timestream | IoT, metrics, events |
| Ledger | QLDB | Immutable, verifiable history |
| Wide-column | Keyspaces | Cassandra-compatible workloads |

**Network Optimization**
- CloudFront for static and dynamic content caching
- Global Accelerator for TCP/UDP performance (anycast IPs)
- VPC endpoints to keep traffic on AWS backbone
- Enhanced Networking (ENA) for EC2
- Placement groups for low-latency inter-instance communication

**Review and Optimize**
- Benchmark and load test before production (use distributed load testing)
- Use performance monitoring: CloudWatch, X-Ray, RUM
- Profile application code, identify bottlenecks
- Re-evaluate service choices as new options become available (Graviton, new instance families)

### Key AWS Services
| Function | Services |
|----------|----------|
| Compute | Lambda, ECS, EKS, EC2, Batch |
| Caching | CloudFront, ElastiCache, DAX, API Gateway cache |
| Database | Aurora, DynamoDB, ElastiCache, Neptune |
| Network | Global Accelerator, CloudFront, PrivateLink |
| Monitoring | CloudWatch, X-Ray, RUM, Compute Optimizer |

---

## 5. Cost Optimization

**Focus**: Avoid unnecessary costs, understand where money is being spent, select the most appropriate and right number of resource types, analyze spending over time, and scale to meet business needs without overspending.

### Design Principles
- Implement cloud financial management
- Adopt a consumption model
- Measure overall efficiency
- Stop spending money on undifferentiated heavy lifting
- Analyze and attribute expenditure

### Key Areas

**Cloud Financial Management**
- Assign cost ownership with tags (enforce with tag policies)
- Establish budgets and forecasts (AWS Budgets, Cost Anomaly Detection)
- Use AWS Cost Explorer for trend analysis
- Create chargeback/showback models per team or workload
- CUR (Cost and Usage Reports) for granular analysis

**Expenditure and Usage Awareness**
- Tag everything: mandatory tags for environment, team, workload, cost-center
- Use AWS Organizations for consolidated billing
- Enable Cost Anomaly Detection for proactive alerts
- Track unit economics: cost per transaction, per user, per API call

**Cost-Effective Resources**

| Strategy | Savings | Commitment | Best For |
|----------|---------|-----------|----------|
| On-Demand | 0% | None | Unpredictable, short-term |
| Savings Plans (Compute) | Up to 66% | 1 or 3 year | Steady compute baseline |
| Reserved Instances | Up to 72% | 1 or 3 year | Specific instance types |
| Spot Instances | Up to 90% | None (interruptible) | Fault-tolerant, flexible |
| Graviton (ARM) | ~20% better price-performance | None | Most Linux workloads |

**Right-Sizing**
- AWS Compute Optimizer for EC2, Lambda, EBS, ECS recommendations
- Review instance utilization: target 70-80% CPU average
- Downsize over-provisioned RDS instances
- Use gp3 instead of gp2 for EBS (20% cheaper, better performance)
- Lambda: optimize memory allocation (use Lambda Power Tuning)

**Waste Elimination Checklist**
- [ ] Unattached EBS volumes
- [ ] Idle load balancers
- [ ] Old EBS snapshots
- [ ] Unused Elastic IPs
- [ ] Orphaned resources after stack deletions
- [ ] Over-provisioned NAT Gateways (consider Gateway endpoints for S3/DynamoDB)
- [ ] Idle RDS instances (dev/staging off-hours)
- [ ] Excessive CloudWatch log retention

**Data Transfer Cost Optimization**
- Use VPC endpoints (gateway for S3/DynamoDB is free)
- Keep traffic within AZ where possible (AZ-aware routing)
- CloudFront for egress reduction (cheaper than direct transfer)
- S3 Intelligent-Tiering for unpredictable access patterns
- Compress data before transfer

### Key AWS Services
| Function | Services |
|----------|----------|
| Visibility | Cost Explorer, Budgets, CUR, Cost Anomaly Detection |
| Optimization | Compute Optimizer, Trusted Advisor, S3 Intelligent-Tiering |
| Purchasing | Savings Plans, Reserved Instances, Spot |
| Governance | Organizations, Tag Policies, Service Control Policies |

---

## 6. Sustainability

**Focus**: Minimize the environmental impact of running cloud workloads by understanding impact, establishing sustainability goals, and maximizing utilization.

### Design Principles
- Understand your impact
- Establish sustainability goals
- Maximize utilization
- Anticipate and adopt new, more efficient offerings
- Use managed services
- Reduce the downstream impact of your workloads

### Key Areas

**Region Selection**
- Choose regions powered by renewable energy where possible
- AWS publishes carbon-free energy percentages per region
- Balance sustainability with latency and data residency requirements

**Compute Efficiency**
- Use Graviton processors: better performance per watt
- Right-size all instances (avoid over-provisioning)
- Use Spot instances to maximize utilization of existing capacity
- Serverless (Lambda, Fargate) shares resources efficiently
- Auto-scale aggressively to match demand, scale down during low periods

**Storage Efficiency**
- Implement data lifecycle policies (S3 Lifecycle, Glacier)
- Delete unnecessary data and snapshots
- Use compression and deduplication
- Choose the right storage tier (Infrequent Access, Glacier, Deep Archive)
- Use S3 Intelligent-Tiering to automate tier placement

**Data Efficiency**
- Reduce data movement: process data where it resides
- Use efficient data formats (Parquet, ORC over CSV/JSON)
- Implement caching to reduce redundant computation
- Compress API responses
- Use pagination and filtering in queries (avoid full table scans)

**Code Efficiency**
- Optimize algorithms and data structures
- Profile code to find resource-intensive operations
- Use compiled languages where appropriate (Rust, Go over Python for hot paths)
- Optimize container images: minimal base images, multi-stage builds

**Measurement**
- AWS Customer Carbon Footprint Tool for Scope 1, 2, 3 emissions
- Track metrics: cost per transaction, resource utilization, data storage growth
- Set sustainability KPIs alongside performance and cost KPIs

### Key AWS Services
| Function | Services |
|----------|----------|
| Measurement | Customer Carbon Footprint Tool, CloudWatch |
| Compute | Graviton instances, Lambda, Fargate, Spot |
| Storage | S3 Lifecycle, Intelligent-Tiering, Glacier |
| Optimization | Compute Optimizer, Trusted Advisor |
