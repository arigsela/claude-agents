# K3s Homelab Cluster Monitoring Agent

This file provides context for Claude Code when monitoring the K3s homelab cluster.

## Project Overview

**Purpose**: Autonomous monitoring agent for K3s homelab cluster that detects, correlates, and escalates infrastructure issues.

**Monitoring Frequency**: Every 1 hour (configurable)

**Architecture**: Multi-agent orchestration with 4 specialized subagents (ALL using Haiku for cost optimization):
1. **k8s-analyzer**: Cluster health inspector (Haiku 4.5)
2. **escalation-manager**: Severity assessor and decision maker (Haiku 4.5)
3. **slack-notifier**: Alert dispatcher (Haiku 4.5)
4. **github-reviewer**: Deployment correlation analyst (optional, Haiku 4.5)

**Model Configuration**: ALL models hardcoded to Haiku 4.5 for cost optimization (~12x cheaper than Sonnet):
- **Orchestrator**: Haiku 4.5-20251001 (cost optimized, proven effective)
- **k8s-analyzer**: Haiku 4.5-20251001 (fast kubectl analysis)
- **escalation-manager**: Haiku 4.5-20251001 (fast severity decisions)
- **slack-notifier**: Haiku 4.5-20251001 (simple message formatting)
- **github-reviewer**: Haiku 4.5-20251001 (deployment correlation analysis)

⚠️ **IMPORTANT**: All subagent .md files specify `model: claude-haiku-4-5-20251001`
This ensures NO Sonnet usage and keeps costs to ~$0.90-$1.50/year

## Critical Reference Data

**Services Configuration**: `docs/reference/services.txt`
- Contains complete service inventory with criticality tiers (P0/P1/P2/P3)
- Max downtime tolerances for each service
- Known issues and quirks
- GitOps repository mappings
- Health check patterns

**IMPORTANT**: All subagents must read `docs/reference/services.txt` first to understand the cluster context.

## Cluster Information

**Type**: K3s homelab cluster
**Purpose**: Personal infrastructure hosting critical applications
**Deployment Model**: GitOps via ArgoCD
**Repository**: https://github.com/arigsela/kubernetes
**Organization**: arigsela

### GitOps Pattern

- **ArgoCD Applications**: `base-apps/*.yaml` files
- **Manifests**: Corresponding `base-apps/{app-name}/` directories
- **Sync**: Automatic (3-5 minutes after commit to main branch)
- **Example**: `base-apps/mysql.yaml` → `base-apps/mysql/` directory

## Service Criticality Framework

### P0 - Business Critical (0 minutes max downtime)

Customer-facing applications and business-critical automation:
- chores-tracker-backend (FastAPI/Python, JWT auth)
- chores-tracker-frontend (HTMX-based)
- mysql (data layer for chores app)
- n8n (workflow automation, AI integrations)
- postgresql (data layer for n8n)
- nginx-ingress (all external traffic)
- oncall-agent (incident response tool)

**Impact**: Direct customer impact or business operations halt
**Action**: Immediate notification required

### P1 - Infrastructure Dependencies (5-15 min max downtime)

Support P0 services, pods can temporarily run without them:
- vault (secret management)
- external-secrets-operator (secret syncing)
- cert-manager (TLS certificate automation)
- ecr-credentials-sync (AWS ECR authentication)
- crossplane (infrastructure provisioning)

**Impact**: Deployment issues, can't start new pods
**Action**: Notify if affecting P0 services or exceeding tolerance

### P2-P3 - Support Services (hours to days tolerance)

Non-critical infrastructure components:
- crossplane-aws-provider
- loki-aws-infrastructure
- whoami-test

**Impact**: Minimal, support infrastructure only
**Action**: Log only, no immediate notification

## Known Issues and Quirks

### chores-tracker-backend
- ⚠️ **VERY SLOW STARTUP**: 5-6 minutes to ready (initialDelaySeconds: 300-360s)
- This is EXPECTED and NOT a problem - allow full startup time
- Has 2 replicas for HA

### mysql
- ⚠️ **Single replica** (no HA) - data loss risk
- Has automated backup CronJob to S3
- Monitor memory usage carefully

### postgresql
- ⚠️ **Single replica** (no HA)
- Data layer for n8n

### vault
- ⚠️ **Requires manual unsealing** after pod restart
- This is EXPECTED behavior, not a bug
- Pods can run with existing secrets until restart

### n8n
- Single replica
- Exposes webhooks for external integrations (NAT gateway traffic)
- Business-critical AI automation workflows

## Health Check Patterns

| Pattern | Services |
|---------|----------|
| `/health` endpoint | chores-tracker-backend, oncall-agent |
| `/healthz` endpoint | n8n |
| TCP probes | mysql:3306, postgresql:5432 |
| Exec commands | vault (vault status), postgresql (pg_isready) |

## Image Registry Patterns

**ECR Account**: 852893458518.dkr.ecr.us-east-2.amazonaws.com
- chores-tracker:5.8.0
- oncall-agent:v0.0.1

**Authentication**: ecr-registry secret (synced by ecr-auth cronjob to kube-system)

**Public Images**: n8n, mysql, postgresql, vault (Docker Hub)

## Monitoring Workflow

### Step 1: Cluster Health Check (k8s-analyzer)
- Check all P0 services first, then P1, then P2-P3
- Use kubectl commands to inspect pods, deployments, nodes, events
- Review recent logs only if issues detected
- Return structured findings organized by severity

### Step 2: Deployment Correlation (github-reviewer)
**Only if issues found in Step 1**
- Query arigsela/kubernetes repository for recent commits
- Focus on manifest paths for affected services
- Check commit timing vs issue timing (5-30 min correlation window)
- Identify deployment-related changes

### Step 3: Severity Assessment (escalation-manager)
- Map affected services to P0/P1/P2/P3 tiers
- Apply max downtime tolerances from services.txt
- Incorporate GitHub correlation confidence
- Determine SEV-1/SEV-2/SEV-3/SEV-4 level
- Decide if notification required

### Step 4: Alert Delivery (slack-notifier)
**Only if escalation-manager says to notify (SEV-1 or SEV-2)**
- Format severity-appropriate Slack message
- Include actionable remediation steps
- Send to configured Slack channel
- Return delivery confirmation

## Escalation Policy

| Severity | Notification | Channel | Timing |
|----------|-------------|---------|---------|
| SEV-1 | ✅ REQUIRED | #critical-alerts | Immediate |
| SEV-2 | ✅ REQUIRED | #infrastructure-alerts | Immediate |
| SEV-3 | ⚠️ BUSINESS HOURS | #infrastructure-alerts | 9 AM - 5 PM only |
| SEV-4 | ❌ LOG ONLY | None | No notification |

## Common Scenarios

### Scenario 1: Healthy Cluster
- k8s-analyzer reports "No critical issues"
- Skip github-reviewer
- escalation-manager determines SEV-4
- No notification sent
- Log monitoring cycle completion

### Scenario 2: P0 Service Down
- k8s-analyzer finds CrashLoopBackOff in chores-tracker-backend
- github-reviewer correlates with recent memory limit change
- escalation-manager classifies as SEV-1 (P0 unavailable, max downtime exceeded)
- slack-notifier sends immediate alert with rollback instructions

### Scenario 3: Expected Behavior
- k8s-analyzer finds vault pod restart
- Recognizes from services.txt that manual unseal is expected
- escalation-manager classifies as SEV-4 (known issue)
- No notification (operational procedure, not incident)

## Operational Notes

### Don't Flag These as Issues
- chores-tracker-backend taking 5-6 minutes to start
- vault requiring manual unseal after restart
- Single replica services (mysql, postgresql, vault, n8n) - architectural choice
- Certificate renewal attempts (only flag if cert actually invalid)

### Always Flag These as Critical
- P0 service with all pods down
- P0 service downtime exceeding max tolerance
- Data layer unavailable (mysql or postgresql)
- Ingress controller down (all external access lost)
- Multiple P0 services failing simultaneously

### Context is Key
- Read services.txt before making any decisions
- Consider known issues before escalating
- Correlate timing between K8s events and GitHub commits
- Understand dependencies (mysql supports chores-tracker-backend)

## Environment Configuration

Configured via .env file:

### Required Configuration
- ANTHROPIC_API_KEY: Claude API access
- GITHUB_TOKEN: GitHub repository access
- SLACK_BOT_TOKEN: Slack notification delivery
- SLACK_CHANNEL: Target channel for alerts
- KUBECONFIG: Path to K3s kubeconfig
- K3S_CONTEXT: Kubernetes context name
- MONITORING_INTERVAL_HOURS: Cycle frequency (default: 1)

### Model Configuration (ALL HARDCODED TO HAIKU)

⚠️ **CRITICAL**: All models are now hardcoded to Haiku 4.5 for maximum cost optimization.

DO NOT change these - they are hardcoded in the Python code AND specified in agent .md files:

```bash
# ALL AGENTS USE HAIKU (hardcoded, cannot be overridden)
ORCHESTRATOR_MODEL=claude-haiku-4-5-20251001
K8S_ANALYZER_MODEL=claude-haiku-4-5-20251001
ESCALATION_MANAGER_MODEL=claude-haiku-4-5-20251001
SLACK_NOTIFIER_MODEL=claude-haiku-4-5-20251001
GITHUB_REVIEWER_MODEL=claude-haiku-4-5-20251001
```

**Cost Optimization Achieved**:
- Haiku: ~$0.25 per million tokens
- Sonnet: ~$3.00 per million tokens (12x more expensive)
- Our implementation: **ALL HAIKU** (maximum savings)

**Estimated Monthly Costs** (30-50 cycles/month, ~10K tokens/cycle):
- Our implementation (All Haiku): ~$0.075-$0.125/month (**~$0.90-$1.50/year**)
- If it were Sonnet: ~$0.75-$1.25/month (~$9-15/year)
- **Annual Savings: ~$8-14** ✅

## File Structure

```
k8s-monitor/
├── .claude/
│   ├── CLAUDE.md (this file)
│   └── agents/
│       ├── k8s-analyzer.md
│       ├── github-reviewer.md
│       ├── escalation-manager.md
│       └── slack-notifier.md
├── src/
│   ├── main.py (orchestrator)
│   └── config/
│       └── settings.py
├── docs/
│   └── reference/
│       └── services.txt (CRITICAL REFERENCE)
└── mcp-servers/
    ├── github/ (GitHub MCP server)
    └── slack/ (Slack MCP server)
```

## Success Criteria

### Monitoring Effectiveness
- ✅ Detects P0 service failures within 1 monitoring cycle
- ✅ Correctly classifies severity using services.txt
- ✅ Correlates issues with deployments when applicable
- ✅ Sends actionable alerts with remediation steps

### Reliability
- ✅ Runs successfully on hourly schedule
- ✅ Handles kubectl failures gracefully
- ✅ Doesn't alert on expected behaviors (vault unseal, slow startups)
- ✅ Preserves incident data if Slack unavailable

### Operational Excellence
- ✅ No false positives (alarm fatigue prevention)
- ✅ Clear rollback instructions in alerts
- ✅ GitHub commit correlation when relevant
- ✅ Business impact assessment for critical issues

## Important Reminders

1. **Always read services.txt first** - It contains the authoritative service criticality mapping
2. **Respect max downtime tolerances** - P0 services have 0 minutes, enforce strictly
3. **Known issues are not incidents** - Check services.txt before escalating
4. **Timing correlation matters** - 5-30 min after deployment suggests causation
5. **Be actionable** - Include specific kubectl commands, commit SHAs, rollback steps
6. **Context over noise** - Concise findings, not raw kubectl dumps
7. **Business impact** - Translate technical issues to user impact

## Version Information

**Agent Version**: 1.0.0-MVP
**Created**: 2025-10-19
**Cluster**: K3s Homelab
**Deployment**: Containerized, scheduled execution
