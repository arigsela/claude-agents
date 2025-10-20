#!/bin/bash
# Local Testing Script for Service Catalog Integration
# Tests the new K3s homelab service catalog functionality

set -e

API_URL="http://localhost:8000"
API_KEY="${API_KEYS:-dev-key}"  # Use dev-key or your actual API key

echo "🧪 Testing OnCall Agent Service Catalog Integration"
echo "=================================================="
echo ""

# Function to test a query
test_query() {
    local test_name="$1"
    local query="$2"
    local expected_keywords="$3"

    echo "📝 Test: $test_name"
    echo "Query: \"$query\""
    echo ""

    response=$(curl -s -X POST "$API_URL/query" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: $API_KEY" \
        -d "{\"prompt\": \"$query\"}" | jq -r '.responses[0].content // "No response"')

    echo "Response:"
    echo "$response"
    echo ""

    # Check for expected keywords
    if [ -n "$expected_keywords" ]; then
        echo "Checking for keywords: $expected_keywords"
        for keyword in $expected_keywords; do
            if echo "$response" | grep -qi "$keyword"; then
                echo "  ✅ Found: $keyword"
            else
                echo "  ❌ Missing: $keyword"
            fi
        done
    fi

    echo ""
    echo "---"
    echo ""
}

# Ensure API is running
echo "Checking if API is running at $API_URL..."
if ! curl -s "$API_URL/health" > /dev/null 2>&1; then
    echo "❌ API not running. Please start it first:"
    echo "   ./start_api_local.sh"
    echo "   OR"
    echo "   docker compose up oncall-agent-api"
    exit 1
fi
echo "✅ API is running"
echo ""

# Test 1: Known Issue - chores-tracker slow startup (should say it's NORMAL)
test_query \
    "Known Issue: chores-tracker slow startup" \
    "Check chores-tracker-backend pods. One pod has been starting for 5 minutes, is this normal?" \
    "NORMAL 5-6 minutes Python"

# Test 2: Vault unsealing procedure (should provide exact command)
test_query \
    "Vault Unsealing Procedure" \
    "The vault pod restarted, what do I need to do?" \
    "unseal kubectl exec vault-0"

# Test 3: Service dependency awareness (mysql down affects chores-tracker)
test_query \
    "Service Dependency Impact" \
    "What happens if mysql goes down?" \
    "chores-tracker P0 customer data"

# Test 4: Priority classification (nginx-ingress should be P0)
test_query \
    "Priority Classification" \
    "nginx-ingress controller is down, how urgent is this?" \
    "P0 platform-wide outage IMMEDIATE"

# Test 5: GitOps correlation awareness
test_query \
    "GitOps Correlation" \
    "chores-tracker pods are restarting 10 times, how do I check if it's related to a recent deployment?" \
    "ArgoCD GitHub kubernetes repo"

# Test 6: Single replica risk awareness (postgresql)
test_query \
    "Single Replica Risk" \
    "What are the risks if postgresql pod fails?" \
    "single replica conversation history n8n"

# Test 7: ECR authentication troubleshooting
test_query \
    "ECR ImagePullBackOff" \
    "A pod has ImagePullBackOff error with an ECR image, what should I check?" \
    "ecr-auth cronjob vault unsealed"

# Test 8: n8n importance (should know it runs the Slack bot)
test_query \
    "n8n Service Importance" \
    "What happens if n8n goes down?" \
    "Slack bot oncall-agent postgresql"

# Test 9: Namespace discovery pattern (should use list_namespaces first)
test_query \
    "Namespace Discovery" \
    "Check the health of chores-tracker services" \
    "chores-tracker-backend chores-tracker-frontend"

# Test 10: Infrastructure service priority (cert-manager should be P2)
test_query \
    "Infrastructure Priority" \
    "cert-manager is failing to renew certificates, how urgent is this?" \
    "P2 90 days Route 53 pfSense"

echo "✅ All tests completed!"
echo ""
echo "Review the responses above to verify:"
echo "  1. Known issues are identified correctly (slow startup, vault unsealing)"
echo "  2. Priorities are assigned correctly (P0/P1/P2)"
echo "  3. Dependencies are mentioned (mysql → chores-tracker)"
echo "  4. GitOps context is included (ArgoCD, GitHub repo)"
echo "  5. Specific commands are provided (kubectl exec vault...)"
echo ""
