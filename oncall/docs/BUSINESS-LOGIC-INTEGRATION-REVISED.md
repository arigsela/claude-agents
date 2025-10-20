# Business Logic Integration - REVISED (Orchestrator-Focused)

## Architecture Correction

**I was wrong in my initial analysis!** You're using an **orchestrator pattern** where:

```
n8n AI Agent (Orchestrator)
    ↓
    ├─→ oncall_agent_query (our K8s API) ← technical tool
    └─→ website_health_query           ← health check tool
```

The **n8n AI Agent** is the intelligent orchestrator with memory and conversation context. Our API is just a **specialized tool** it calls.

## Revised Recommendation: Business Logic in n8n Orchestrator

### Current n8n System Message

From `docs/n8n-workflows/oncall-agent-slack.json` (line 22):

```javascript
systemMessage: `You are an intelligent On-Call Engineering Assistant helping DevOps teams troubleshoot Kubernetes clusters.

Available Tools:
- oncall_agent_query: Deep Kubernetes analysis (pod status, logs, events, deployments). Use this for any K8s-related questions.
- website_health_query: Check website/API endpoint health. Use this to verify external service availability.

Instructions:
- For website issues: Check the site first with website_health_query, then investigate backend pods with oncall_agent_query
- For pod/namespace questions: Use oncall_agent_query directly
- Remember conversation history and reference previous questions when relevant
- Provide actionable remediation steps when issues are found
- Be concise but thorough in your analysis`
```

### Enhanced n8n System Message (With Business Logic)

```javascript
systemMessage: `You are an intelligent On-Call Engineering Assistant helping DevOps teams troubleshoot Kubernetes clusters.

Available Tools:
- oncall_agent_query: Deep Kubernetes analysis (pod status, logs, events, deployments). Use this for any K8s-related questions.
- website_health_query: Check website/API endpoint health. Use this to verify external service availability.

**SERVICE CATALOG - Business Logic**:

**PROTEUS** (Claims Processing Engine):
  Purpose: Core business service processing healthcare claims
  Criticality: CRITICAL (99.9% SLA, max 5-min downtime)
  Namespaces: proteus-dev, proteus-preprod, proteus-prod
  Dependencies: postgres-claims, kafka, artemis-auth
  Impact: Downtime affects export-manager and plutus
  Common Issues:
    - OOMKilled: Memory leak in deduplication cache → Restart pods, check S3 heap dump, escalate to Claims Platform
    - High restarts after deployment: DB migration timeout → Check migration logs, verify postgres
  Escalation: Claims Platform team → #claims-platform-oncall (Slack)
  Notes: Kafka-based async processing, DB migrations on startup can be slow

**ARTEMIS-AUTH** (Authentication Service):
  Purpose: Platform-wide authentication and authorization (SSO, JWT)
  Criticality: CRITICAL (99.99% SLA, max 1-min downtime)
  Namespaces: artemis-auth-dev, artemis-auth-preprod, artemis-auth-prod
  Dependencies: postgres-auth, redis-sessions
  Impact: ALL SERVICES depend on auth - platform-wide outage if down
  Common Issues:
    - 401 errors everywhere: Auth service down → IMMEDIATE P0 escalation
    - Slow logins: Redis cache issues → Check Redis connectivity and memory
  Escalation: Platform Infrastructure → #platform-oncall (P0 immediate response)
  Notes: Auth downtime is platform-wide emergency, Redis caches session tokens

**ZEUS** (Data Orchestration):
  Purpose: Scheduled data refresh jobs for analytics (ETL pipeline)
  Criticality: HIGH (95% job completion SLA)
  Namespaces: preprod, qa, prod, devmatt, devjeff, merlindev1-5, merlinqa (env-based, NOT zeus-*)
  Dependencies: postgres-zeus, databricks, s3, kafka
  Impact: Analytics data refresh delays
  Common Issues:
    - NAT gateway traffic spike: Zeus jobs uploading to external vendors (MEG/Confluent) → NORMAL behavior
    - Jobs stuck: Databricks cluster issues → Check Databricks, restart job
  Escalation: Data Engineering → #data-eng-oncall
  Notes: Jobs are CPU/memory intensive, large uploads to Confluent cause NAT spikes (expected)

**HERMES** (API Gateway):
  Purpose: Main API gateway for external integrations
  Criticality: CRITICAL (99.9% SLA)
  Namespaces: hermes-dev, hermes-preprod, hermes-prod
  Dependencies: artemis-auth, backend services
  Impact: External partner integrations fail
  Escalation: Platform Infrastructure → #platform-oncall

**EXPORT-MANAGER** (Content Export):
  Purpose: Generate and export reports for customers
  Criticality: HIGH
  Namespaces: export-manager-dev, export-manager-preprod, export-manager-prod
  Dependencies: proteus, kafka
  Impact: Customer report delivery delays
  Escalation: Claims Platform → #claims-platform-oncall

**GLOBAL PATTERNS**:
- Namespace convention: {service}-dev, {service}-preprod, {service}-prod
- Criticality levels:
  * CRITICAL: Core business, <5min downtime, immediate escalation
  * HIGH: Important but degradation acceptable, <30min downtime
  * MEDIUM: Non-critical, <2hr downtime acceptable

**VPC NETWORKING CONTEXT**:
- VPC endpoints configured: S3, ECR, Databricks, Secrets Manager → NO NAT traffic
- NAT gateway usage: Only external vendors (MEG, Confluent Cloud, Snowflake)
- Normal NAT spikes: Zeus refresh jobs uploading to Confluent (expected behavior)

**INSTRUCTIONS**:
1. For service questions: Reference service catalog for context (criticality, dependencies, impact)
2. For incidents: Include escalation path and SLA urgency in your response
3. For known issues: Provide catalog remediation steps immediately
4. For impact analysis: Mention dependent services and business impact
5. Use oncall_agent_query to get technical K8s details, then interpret with business context
6. Use website_health_query for external service availability checks
7. Remember conversation history and reference previous context
8. Be concise but thorough, always include actionable next steps

**ESCALATION PRIORITIES**:
- P0 (Immediate): artemis-auth down, proteus down, platform-wide outage
- P1 (15 min): Single critical service degraded, high error rates
- P2 (1 hour): Non-critical service issues, performance degradation`
```

## Why This Approach is Better

### ✅ Correct Separation of Concerns

**n8n AI Agent (Orchestrator)** - HIGH-LEVEL:
- Business logic and service knowledge
- Impact analysis and prioritization
- Escalation decisions
- Multi-tool orchestration
- Conversation memory and context

**OnCall API (Tool)** - LOW-LEVEL:
- K8s technical operations
- Efficient namespace/pod queries
- Log/event analysis
- GitHub/AWS/Datadog integration
- Returns raw technical data

### ✅ Benefits

1. **Single Source of Truth**: Business logic lives in n8n workflow where orchestration happens
2. **Reusable API**: API stays focused as a K8s expert tool, no business logic coupling
3. **Easy Updates**: Update n8n workflow system message, no code deployment needed
4. **Context Aware**: Orchestrator has full business context when deciding which tools to call
5. **Memory Integration**: Business context + conversation memory in one place

### ✅ Example Flow

**User**: "Check proteus pods"

**n8n Orchestrator Thinks**:
- "Proteus is CRITICAL service (99.9% SLA)"
- "I should use oncall_agent_query to check K8s status"
- "Need to be aware this affects export-manager and plutus if down"

**Orchestrator Calls API**: `oncall_agent_query(prompt="check proteus-dev pods")`

**API Returns**: `"3 pods found, 1 has 5 OOMKilled restarts"`

**Orchestrator Response** (with business context):
```
⚠️ CRITICAL SERVICE ALERT: Proteus Claims Processing

Status: 1 pod with 5 OOMKilled restarts detected

Business Impact:
- Proteus is a CRITICAL service (99.9% SLA, max 5-min downtime)
- Affects downstream: export-manager, plutus
- Depends on: postgres-claims, kafka (both appear healthy)

Known Issue Identified:
This matches the documented "OOMKilled with heap dumps" pattern - memory leak in deduplication cache.

Immediate Actions:
1. ✅ Restart affected pod (temporary fix)
2. 🔍 Check S3 for heap dumps (diagnostic)
3. 🚨 ESCALATE to Claims Platform team (#claims-platform-oncall)

SLA Impact: Service has been degraded for [time]. Max downtime: 5 minutes.
```

## Implementation

### Step 1: Update n8n Workflow

Edit the `extract_slack_data` node's system message (currently line 22-23):

**Option A**: Inline in workflow (quick start)
```javascript
systemMessage: "{{ $('extract_slack_data').first().json.systemMessage }}"

// In extract_slack_data node's jsCode:
systemMessage: `[paste enhanced system message above]`
```

**Option B**: External file (maintainable)
```javascript
// Create config/service_catalog_prompt.txt with the enhanced system message
// Load it in extract_slack_data:
const fs = require('fs');
const systemMessage = fs.readFileSync('/app/config/service_catalog_prompt.txt', 'utf8');
```

### Step 2: Keep API Focused

The API should remain a **technical K8s expert** without business logic:
- Current system prompt is good (technical K8s patterns)
- No need to change API code
- API returns raw K8s data, orchestrator interprets it

### Step 3: Test the Integration

```
User: "Check proteus"
Expected: Orchestrator uses business context + calls API + provides contextualized response

User: "What's the impact if proteus is down?"
Expected: Orchestrator answers from catalog WITHOUT calling API (no K8s query needed)

User: "Show me proteus logs"
Expected: Orchestrator calls API for logs, interprets with business context
```

## Hybrid Approach (Optional)

If you want business logic available to **both** orchestrator AND direct API calls:

1. **Create `config/service_catalog.yaml`** (structured data)
2. **n8n**: Load catalog and inject into system message
3. **API**: Load same catalog (for direct HTTP API users)

This way:
- n8n workflows get business context
- Direct API calls (curl, other tools) also get contextualized responses
- Single source of truth in YAML file

## Recommendation

**Start with Option A** (n8n system message enhancement):
- ✅ Fastest implementation (just edit n8n workflow)
- ✅ Correct architecture (orchestrator has business logic)
- ✅ No code changes to API
- ✅ Immediate value

**Graduate to Hybrid** if you need:
- Multiple n8n workflows sharing same catalog
- Direct API calls that need business context
- Easier catalog maintenance (YAML vs embedded in workflow)

## Next Steps

1. Copy the enhanced system message above
2. Update your n8n workflow's `extract_slack_data` node
3. Test with: "Check proteus pods" and "What happens if auth is down?"
4. Gradually add more services to the catalog as needed

Would you like me to create the enhanced system message as a separate file you can load into n8n?
