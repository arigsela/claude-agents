# Testing Skills Integration Locally

This guide shows you how to test the skills integration in your oncall agent.

## Prerequisites

1. **Ensure you're in the oncall directory**:
   ```bash
   cd /Users/arisela/git/claude-agents/oncall
   ```

2. **Activate virtual environment**:
   ```bash
   source venv/bin/activate
   ```

3. **Verify .env file exists** with `ANTHROPIC_API_KEY`:
   ```bash
   cat .env | grep ANTHROPIC_API_KEY
   ```

---

## Method 1: Quick Skills Verification Test (No API calls)

This test verifies that skills are loaded correctly WITHOUT making any Anthropic API calls.

```bash
python test_skills.py
```

**What it checks**:
- ✅ Skills files exist and can be loaded
- ✅ k8s-failure-patterns content is in system prompt
- ✅ homelab-runbooks content is in system prompt
- ✅ Skills instructions are added
- ✅ System prompt size (~16K characters)

**Expected output**:
```
============================================================
Testing Skills Integration in OnCall Agent
============================================================

1. Initializing OnCallAgentClient...
   ✅ Client initialized successfully

2. Checking system prompt for skills...
   ✅ k8s-failure-patterns skill found in prompt
   ✅ homelab-runbooks skill found in prompt

3. Verifying specific skill content...
   ✅ Found: k8s-failure-patterns content
   ✅ Found: k8s-failure-patterns content
   ✅ Found: homelab-runbooks content
   ✅ Found: homelab-runbooks content
   ✅ Found: skills instructions

4. System prompt size: 15,857 characters
   (~3964.2K tokens estimated)

============================================================
✅ Skills integration test PASSED
============================================================
```

---

## Method 2: Start API Server and Test with Queries (Real API calls)

### Step 1: Start the API Server

**Option A: Using the helper script** (Recommended):
```bash
./run_api_server.sh
```

**Option B: Using uvicorn directly**:
```bash
# Load environment variables first
export $(cat .env | grep -v '^#' | xargs)

# Start server
python -m uvicorn api.api_server:app --app-dir src --port 8000 --reload
```

**Option C: Using Docker**:
```bash
docker compose up oncall-agent-api
```

### Step 2: Verify Server Started

Check the logs for skills loading:
```bash
# Look for these lines in the startup logs:
✅ Loaded skill: k8s-failure-patterns (5000 chars)
✅ Loaded skill: homelab-runbooks (10000 chars)
```

### Step 3: Check Health Endpoint

```bash
curl http://localhost:8000/health
```

**Expected**:
```json
{
  "status": "healthy",
  "agent": "initialized",
  "version": "1.0.0"
}
```

### Step 4: Test Skills with Queries

Now let's test with queries that should trigger skill knowledge:

#### Test 1: Known Issue (Slow Startup)

**Query**: "chores-tracker pod has been starting for 5 minutes, is this normal?"

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{
    "prompt": "chores-tracker pod has been starting for 5 minutes, is this normal?"
  }' | jq -r '.response'
```

**Expected response should include**:
- ✅ Reference to homelab-runbooks skill
- ✅ "5-6 minute startup is NORMAL"
- ✅ Explanation about Python initialization
- ✅ "Only investigate if >10 minutes"

#### Test 2: CrashLoopBackOff Pattern

**Query**: "mysql pod is in CrashLoopBackOff, help me troubleshoot"

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{
    "prompt": "mysql pod is in CrashLoopBackOff, help me troubleshoot"
  }' | jq -r '.response'
```

**Expected response should include**:
- ✅ Reference to k8s-failure-patterns skill
- ✅ "CrashLoopBackOff" pattern identified
- ✅ Common Causes (from skill)
- ✅ Investigation steps with kubectl commands
- ✅ MySQL-specific troubleshooting (from homelab-runbooks)
- ✅ Note about single replica risk

#### Test 3: Vault Unsealing

**Query**: "vault pod restarted, what do I need to do?"

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{
    "prompt": "vault pod restarted, what do I need to do?"
  }' | jq -r '.response'
```

**Expected response should include**:
- ✅ Reference to homelab-runbooks skill
- ✅ "Manual unseal required"
- ✅ Step-by-step unsealing procedure
- ✅ `kubectl exec -n vault vault-0 -- vault operator unseal`
- ✅ Explanation that this is expected behavior

#### Test 4: ImagePullBackOff ECR

**Query**: "pod has ImagePullBackOff from ECR, how do I fix it?"

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{
    "prompt": "pod has ImagePullBackOff from ECR, how do I fix it?"
  }' | jq -r '.response'
```

**Expected response should include**:
- ✅ Reference to both skills
- ✅ ImagePullBackOff pattern from k8s-failure-patterns
- ✅ ECR authentication troubleshooting from homelab-runbooks
- ✅ Check ecr-auth cronjob
- ✅ Verify vault unsealed
- ✅ Check ecr-registry secret exists

---

## Method 3: Interactive API Testing (Swagger UI)

The easiest way to test with a visual interface:

1. **Start the API server** (see Method 2, Step 1)

2. **Open Swagger UI**:
   ```bash
   open http://localhost:8000/docs
   ```

3. **Test the `/query` endpoint**:
   - Click on "POST /query"
   - Click "Try it out"
   - Enter JSON request body:
     ```json
     {
       "prompt": "chores-tracker pod has been starting for 5 minutes"
     }
     ```
   - Click "Execute"
   - View response

4. **Look for skill citations** in the response:
   - "According to the homelab-runbooks..."
   - "Based on k8s-failure-patterns..."
   - Specific kubectl commands
   - Known issue references

---

## Method 4: Session-Based Testing (Multi-turn)

Test that skills work across multiple queries in a session:

### Create a session:
```bash
SESSION_ID=$(curl -X POST http://localhost:8000/session \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{
    "user_id": "test-user"
  }' | jq -r '.session_id')

echo "Session ID: $SESSION_ID"
```

### Query 1: Ask about an issue
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d "{
    \"prompt\": \"mysql pod is crashing\",
    \"session_id\": \"$SESSION_ID\"
  }" | jq -r '.response'
```

### Query 2: Follow-up (tests context retention)
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d "{
    \"prompt\": \"what are the common causes?\",
    \"session_id\": \"$SESSION_ID\"
  }" | jq -r '.response'
```

**Expected**: Should reference CrashLoopBackOff common causes from skills

---

## What to Look For in Responses

### ✅ Good Signs (Skills Working)

1. **Skill Citations**:
   - "According to the homelab-runbooks..."
   - "Based on k8s-failure-patterns..."
   - "From the skill knowledge..."

2. **Detailed kubectl Commands**:
   - `kubectl logs -n namespace pod --tail=100`
   - `kubectl describe pod -n namespace pod`
   - `kubectl get events -n namespace --sort-by='.lastTimestamp'`

3. **Common Causes Listed**:
   - Numbered list of causes from the skill
   - Specific to the failure type

4. **Investigation Steps**:
   - Step-by-step troubleshooting
   - Matches content from skills

5. **Known Issues Referenced**:
   - "5-6 min startup is NORMAL"
   - "Manual unseal required"
   - "Single replica risk"

### ❌ Bad Signs (Skills Not Working)

1. **Generic Responses**:
   - "Check the logs"
   - "Restart the pod"
   - No specific kubectl commands

2. **No Skill References**:
   - Doesn't cite which skill is being used
   - No mention of "common causes" or "investigation steps"

3. **Missing Known Issues**:
   - Treats slow startup as a problem
   - Doesn't mention vault unseal procedure
   - Misses ECR authentication steps

---

## Troubleshooting Test Failures

### Skills Not Loading

**Symptom**: Test shows "Skill file not found"

**Fix**:
```bash
# Verify skills exist
ls -la .claude/skills/
# Should show:
# k8s-failure-patterns.md
# homelab-runbooks.md

# If missing, they're in the wrong location
# Skills should be in oncall/.claude/skills/, not root .claude/skills/
```

### API Server Won't Start

**Symptom**: Server fails with "ANTHROPIC_API_KEY not set"

**Fix**:
```bash
# Check .env file exists
cat .env | grep ANTHROPIC_API_KEY

# If not set, add it:
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env

# Or export temporarily:
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### Skills Loaded But Not Used

**Symptom**: Skills in prompt but responses don't reference them

**Possible causes**:
1. Model is Haiku (needs explicit instructions - already added ✅)
2. Skills content is being ignored
3. Query doesn't trigger skill patterns

**Debug**:
```bash
# Check if explicit instructions are in prompt
python -c "from src.api.agent_client import OnCallAgentClient; \
           c = OnCallAgentClient(); \
           print('INSTRUCTIONS FOUND' if 'IMPORTANT: Using Skills' in c.system_prompt else 'MISSING')"
```

### API Authentication Errors

**Symptom**: 401 Unauthorized

**Fix**:
```bash
# For testing, disable API key auth by setting empty API_KEYS:
echo "API_KEYS=" >> .env

# Or use a test key:
-H "X-API-Key: test-key"
```

---

## Quick Test Checklist

Before declaring "skills are working", verify:

- [ ] ✅ Test script passes (`python test_skills.py`)
- [ ] ✅ API server starts and shows skill loading logs
- [ ] ✅ Health endpoint responds
- [ ] ✅ Query about "chores-tracker slow startup" mentions 5-6 min is normal
- [ ] ✅ Query about "CrashLoopBackOff" includes Common Causes
- [ ] ✅ Query about "vault restart" includes unseal procedure
- [ ] ✅ Query about "ImagePullBackOff" mentions ECR auth troubleshooting
- [ ] ✅ Responses cite which skill is being used
- [ ] ✅ kubectl commands are detailed and specific

---

## Performance Check

Monitor token usage to ensure skills aren't too expensive:

```bash
# Make a query and check token usage
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key" \
  -d '{"prompt": "test query"}' | jq '.usage'
```

**Expected token usage**:
- Input tokens: ~4,000-5,000 (includes skills in system prompt)
- Output tokens: ~500-1,500 (varies by response)
- Cost per query: ~$0.001-$0.002 (with Haiku 4.5)

**This is acceptable!** Skills add value without significant cost increase.

---

## Summary

**Fastest test**: `python test_skills.py` (30 seconds)

**Most thorough test**: Start API + test all 4 query scenarios (5 minutes)

**Easiest test**: Swagger UI at http://localhost:8000/docs (visual, interactive)

All three methods should confirm skills are loaded and being used correctly! 🎉
