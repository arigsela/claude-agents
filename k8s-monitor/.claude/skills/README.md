# Claude Skills Implementation Guide

This directory demonstrates how **Claude Skills** work alongside **Claude Agent SDK subagents** in the k8s-monitor project.

## What We Built

We refactored the `k8s-analyzer` subagent to use a Claude Skill for storing common Kubernetes failure pattern knowledge, demonstrating:
- **Skills for knowledge** (failure patterns, known issues)
- **Subagents for orchestration** (workflow, tool usage)
- **Progressive disclosure** (skill loads only when needed)

## Files Created

```
k8s-monitor/.claude/
├── skills/                              # NEW: Skills directory
│   ├── k8s-failure-patterns.md         # NEW: K8s knowledge skill
│   └── README.md                        # NEW: This documentation
│
└── agents/                              # EXISTING
    ├── k8s-analyzer.md                  # MODIFIED: Now references skill
    ├── github-reviewer.md
    ├── escalation-manager.md
    └── slack-notifier.md
```

## How It Works

### Before (Monolithic Agent)

**k8s-analyzer.md** contained everything (~1,500 tokens):
```markdown
---
name: k8s-analyzer
tools: Bash, Read, Grep
model: haiku
---

# Kubernetes Health Analyzer

## Analysis Checklist
[Commands to run]

## What to Look For
- CrashLoopBackOff: Application crashes repeatedly...
- OOMKilled: Pod exceeded memory limit...
- ImagePullBackOff: Cannot pull container image...
[100+ lines of failure pattern definitions]

## Known Service Issues
- chores-tracker-backend: Slow startup (5-6 min)...
- vault: Manual unsealing required...
- mysql: Single replica (no HA)...
[50+ lines of service-specific knowledge]
```

**Problem**: Every time k8s-analyzer runs, it loads ALL this knowledge, even if just checking healthy pods.

### After (Agent + Skill)

**k8s-analyzer.md** (~900 tokens) - Process focused:
```markdown
---
name: k8s-analyzer
tools: Bash, Read, Grep
model: haiku
---

# Kubernetes Health Analyzer

## Reference Data
Claude will automatically reference the k8s-failure-patterns skill when analyzing pod issues.

## Analysis Checklist
[Commands to run - what to do]

## Output Format
[How to structure results]
```

**k8s-failure-patterns.md** (~1,200 tokens) - Knowledge focused:
```markdown
---
name: k8s-failure-patterns
description: Use when analyzing Kubernetes pod failures, crash events, OOM issues...
---

# Kubernetes Failure Patterns & Known Issues

## Common Pod Status Patterns
- CrashLoopBackOff: [detailed explanation]
- OOMKilled: [detailed explanation]
...

## Service-Specific Known Issues
- chores-tracker-backend: [known quirks]
- vault: [known quirks]
...
```

**Benefit**:
- **Metadata loaded**: ~40 tokens (just the description)
- **Full skill loaded**: Only if Claude encounters a pod failure
- **Token savings**: 40% reduction when no issues found

## Context Usage Comparison

### Scenario 1: Cluster is Healthy (No Issues)

**Before (Monolithic Agent)**:
```
k8s-analyzer loaded: 1,500 tokens
└─ Analysis: kubectl commands show all pods Running
└─ Output: "No critical issues detected"
Total: 1,500 tokens for agent definition
```

**After (Agent + Skill)**:
```
k8s-analyzer loaded: 900 tokens
├─ Skill metadata loaded: 40 tokens (description only)
├─ Analysis: kubectl commands show all pods Running
├─ Skill NOT loaded: No failures to analyze
└─ Output: "No critical issues detected"
Total: 940 tokens (37% savings!)
```

### Scenario 2: Pod with OOMKilled Error

**Before (Monolithic Agent)**:
```
k8s-analyzer loaded: 1,500 tokens
├─ Analysis: kubectl shows pod OOMKilled
├─ References embedded knowledge about OOMKilled
└─ Output: Analysis with context
Total: 1,500 tokens for agent definition
```

**After (Agent + Skill)**:
```
k8s-analyzer loaded: 900 tokens
├─ Skill metadata loaded: 40 tokens
├─ Analysis: kubectl shows pod OOMKilled
├─ Skill FULLY loaded: 1,200 tokens (triggered by OOMKilled pattern)
├─ References skill knowledge about OOMKilled
└─ Output: Analysis with context
Total: 2,140 tokens (43% higher, but more organized)
```

**Trade-off**: Slightly more tokens when skill loads, but:
- Better organized (separation of concerns)
- Reusable (other agents can use same skill)
- Maintainable (update skill once, all agents benefit)

### Scenario 3: Other Agents Can Reuse the Skill

If we later create a `k8s-remediation` agent, it can also reference the same skill:

```
escalation-manager loaded: 1,200 tokens
├─ Skill metadata: 40 tokens (already in context from k8s-analyzer!)
├─ Analysis: Determines SEV-1 severity
└─ Skill knowledge: Already loaded, 0 additional tokens
Total: 1,200 tokens (skill shared across agents)
```

## Progressive Disclosure in Action

Here's the exact flow when the k8s-analyzer subagent runs:

### Step 1: Orchestrator Invokes Subagent
```python
# main monitoring daemon
response = await client.query(
    "Use Task tool to invoke k8s-analyzer to check cluster health"
)
```

### Step 2: k8s-analyzer Context Initialized
```
Loading agent definition: k8s-analyzer.md (900 tokens)
Loading skill metadata: k8s-failure-patterns.md (40 tokens)
├─ name: k8s-failure-patterns
└─ description: "Use when analyzing Kubernetes pod failures..."

Total initial context: 940 tokens
```

### Step 3: Claude Executes kubectl Commands
```bash
kubectl get pods --all-namespaces
# Output shows: chores-tracker-backend pod has status OOMKilled
```

### Step 4: Claude Detects Relevance
```
Claude's reasoning:
"I see an OOMKilled pod. The k8s-failure-patterns skill description says
'Use when analyzing OOM issues'. I should load this skill now."

Action: Load full k8s-failure-patterns.md (+1,200 tokens)
```

### Step 5: Claude Uses Skill Knowledge
```
Now Claude has access to:
- What OOMKilled means
- Common causes (memory limit too low, memory leak, etc.)
- Investigation steps (check limits, check Git history)
- Service-specific context (if it's chores-tracker-backend)
```

### Step 6: Structured Output
```markdown
## K8s Health Analysis Report

### Critical Issues (P0)
- **Service**: chores-tracker-backend
  - **Issue**: OOMKilled (memory limit exceeded)
  - **Investigation**: [uses skill knowledge]
  - **Known Context**: This service has slow startup but no known memory issues
```

## When Skills Load vs When They Don't

### Skills Load When:
✅ Claude sees a pod status that matches skill description (OOMKilled, CrashLoopBackOff)
✅ Claude needs to explain a failure pattern
✅ Claude references service-specific known issues
✅ User explicitly asks about failure patterns

### Skills DON'T Load When:
❌ All pods are healthy (Running state)
❌ Just listing pods without issues
❌ Checking deployments that are all at desired replicas
❌ No failures to analyze

## How to Test This Implementation

### Test 1: Verify Skill File Exists
```bash
ls -la k8s-monitor/.claude/skills/
# Should show:
# - k8s-failure-patterns.md
# - README.md
```

### Test 2: Check Agent References Skill
```bash
grep -n "k8s-failure-patterns" k8s-monitor/.claude/agents/k8s-analyzer.md
# Should show references to the skill in the agent definition
```

### Test 3: Simulate Healthy Cluster (Skill Won't Load)
```python
# In your monitoring daemon
response = await client.query("""
Use Task tool to invoke k8s-analyzer.

Simulate this kubectl output:
NAMESPACE                NAME                    READY   STATUS    RESTARTS
chores-tracker-backend   backend-abc123          1/1     Running   0
chores-tracker-frontend  frontend-xyz789         1/1     Running   0
mysql                    mysql-0                 1/1     Running   0

Analyze and report.
""")

# Expected: Skill metadata loaded (40 tokens) but NOT full skill
# Output should be: "No critical issues detected"
```

### Test 4: Simulate OOMKilled Pod (Skill WILL Load)
```python
response = await client.query("""
Use Task tool to invoke k8s-analyzer.

Simulate this kubectl output:
NAMESPACE                NAME                    READY   STATUS        RESTARTS
chores-tracker-backend   backend-abc123          0/1     OOMKilled     5

Analyze and report.
""")

# Expected: Full skill loads (1,200 tokens)
# Output should reference OOMKilled causes from skill:
# - Memory limit too low
# - Memory leak
# - Check recent Git changes
```

## Benefits of This Approach

### 1. Token Efficiency (Progressive Disclosure)
- **Healthy clusters**: Save 37% tokens (skill metadata vs full definition)
- **Failed pods**: Load knowledge on-demand when needed
- **Amortized cost**: Multiple agents share same skill

### 2. Maintainability (DRY Principle)
```
Before: Update failure patterns in k8s-analyzer.md
After: Update k8s-failure-patterns.md ONCE
      → k8s-analyzer automatically gets updates
      → Future agents (k8s-remediation, k8s-forecaster) also get updates
```

### 3. Reusability
Other agents can reference the same skill:
- `escalation-manager`: Reference failure patterns for severity scoring
- `github-reviewer`: Reference known service issues when correlating deployments
- Future `k8s-remediation`: Use same knowledge for automated fixes

### 4. Separation of Concerns
- **Agent**: WHAT to do (commands to run, workflow)
- **Skill**: WHAT to know (failure patterns, service quirks)
- Clear boundaries, easier to debug

### 5. Extensibility
Easy to add more skills without bloating agent definitions:
```
.claude/skills/
├── k8s-failure-patterns.md      # Pod failure knowledge
├── k8s-network-debugging.md     # NEW: Network troubleshooting
├── k8s-storage-issues.md        # NEW: PVC/PV problems
└── aws-eks-specifics.md         # NEW: AWS-specific context
```

All auto-discovered by Claude when relevant!

## Limitations & Trade-offs

### When Skills Are NOT Ideal

❌ **Critical tool restrictions**: Skills can't enforce per-agent tool boundaries
- k8s-analyzer should only have Bash/Read/Grep
- Skills don't provide this security boundary
- **Solution**: Keep using subagents for different tool access levels

❌ **Guaranteed execution order**: Skills auto-invoke, no pipeline control
- Your pipeline: k8s-analyzer → github-reviewer → escalation-manager → slack-notifier
- Skills can't guarantee this sequence
- **Solution**: Keep using Task tool for orchestration

❌ **Context isolation**: Skills share context within same conversation
- If skill loads early, it stays in context (no cleanup)
- Could contribute to context bloat in long conversations
- **Solution**: Use subagents for isolated contexts + skills for knowledge

### Current Approach: Hybrid (Best of Both Worlds)

✅ **Subagents**: Orchestration, tool boundaries, workflow control
✅ **Skills**: Shared knowledge, progressive disclosure, reusability

## Next Steps

### Recommended Additional Skills

1. **service-priorities.md** - Service criticality tiers
   - Used by: escalation-manager, k8s-analyzer
   - Content: P0/P1/P2/P3 definitions, max downtime values

2. **incident-response-sops.md** - Standard operating procedures
   - Used by: escalation-manager, slack-notifier
   - Content: Escalation paths, notification rules, runbooks

3. **slack-message-templates.md** - Formatting standards
   - Used by: slack-notifier
   - Content: SEV-1/2/3 templates, emoji guide, markdown patterns

### How to Add a New Skill

1. **Create the skill file**:
```bash
cat > k8s-monitor/.claude/skills/service-priorities.md << 'EOF'
---
name: service-priorities
description: Use when assessing incident severity or service criticality
---

# Service Criticality Tiers

## P0 - Business Critical
- chores-tracker-backend
- mysql
...
EOF
```

2. **Reference it in agents** (optional, Claude auto-discovers):
```markdown
# In escalation-manager.md
Claude will automatically reference the service-priorities skill when
assessing incident severity.
```

3. **Test it**:
```python
# Invoke escalation-manager with a P0 service issue
# Verify skill loads when determining severity
```

## Comparison to Current Architecture

### Your Current Multi-Agent Architecture (UNCHANGED)

```
Orchestrator (monitor_daemon.py)
├─ Invokes: k8s-analyzer (NEW: now uses skill)
│  └─ Returns: Health report
├─ Invokes: github-reviewer
│  └─ Returns: Deployment correlation
├─ Invokes: escalation-manager
│  └─ Returns: Severity decision
└─ Invokes: slack-notifier
   └─ Returns: Notification confirmation
```

**This orchestration flow is PRESERVED.** Skills just make k8s-analyzer lighter.

### What Changed

| Component | Before | After |
|-----------|--------|-------|
| **k8s-analyzer.md** | 1,500 tokens (monolithic) | 900 tokens (references skill) |
| **Failure knowledge** | Embedded in agent | Extracted to skill |
| **Context efficiency** | Always loads all | Progressive disclosure |
| **Reusability** | None (agent-specific) | Other agents can use skill |
| **Orchestration** | Task tool (unchanged) | Task tool (unchanged) |
| **Tool restrictions** | Per-agent (unchanged) | Per-agent (unchanged) |
| **Workflow control** | Explicit (unchanged) | Explicit (unchanged) |

## Cost Analysis

### Token Usage Per Monitoring Cycle

**Scenario: 80% of cycles have healthy cluster, 20% have issues**

#### Before (Monolithic Agents)
```
80 healthy cycles × 1,500 tokens = 120,000 tokens
20 issue cycles × 1,500 tokens   =  30,000 tokens
Total:                             150,000 tokens
```

#### After (Agents + Skills)
```
80 healthy cycles × 940 tokens   = 75,200 tokens (skill metadata only)
20 issue cycles × 2,140 tokens   = 42,800 tokens (skill fully loaded)
Total:                            118,000 tokens (21% savings!)
```

**Savings**: ~32,000 tokens per 100 cycles

**Cost Impact** (assuming Claude Haiku at $0.25/1M input tokens):
- Before: $0.0375 per 100 cycles
- After: $0.0295 per 100 cycles
- Savings: $0.008 per 100 cycles (~21%)

For a deployment running every 15 minutes (96 cycles/day):
- Daily savings: ~$0.008
- Monthly savings: ~$0.24
- Annual savings: ~$2.88

**Not huge savings, but demonstrates the principle!** For larger deployments with more agents and more skills, savings multiply.

## Conclusion

This implementation demonstrates:
- ✅ **Skills work alongside subagents** (not a replacement)
- ✅ **Progressive disclosure saves tokens** (when cluster is healthy)
- ✅ **Knowledge reusability** (multiple agents can share skills)
- ✅ **Maintainability** (update skill once, all agents benefit)
- ✅ **Separation of concerns** (process vs knowledge)

**Your orchestration architecture remains unchanged.** Skills just make individual agents more efficient and maintainable.
