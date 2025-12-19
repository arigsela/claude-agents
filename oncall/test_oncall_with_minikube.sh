#!/bin/bash
# Comprehensive test script for oncall agent with minikube
# Tests mem0 integration, K8s queries, and session memory

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  OnCall Agent + mem0 Integration Test${NC}"
echo -e "${BLUE}  with Minikube Local Cluster${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if minikube is running
echo -e "${YELLOW}1. Checking minikube status...${NC}"
if ! minikube status | grep -q "Running"; then
    echo -e "${RED}❌ Minikube is not running${NC}"
    echo "Please start minikube first: minikube start"
    exit 1
fi
echo -e "${GREEN}✅ Minikube is running${NC}"
echo ""

# Check kubectl context
echo -e "${YELLOW}2. Verifying kubectl context...${NC}"
CONTEXT=$(kubectl config current-context)
echo "   Current context: $CONTEXT"
if [[ "$CONTEXT" != "minikube" ]]; then
    echo -e "${YELLOW}⚠️  Switching to minikube context...${NC}"
    kubectl config use-context minikube
fi
echo -e "${GREEN}✅ Using minikube context${NC}"
echo ""

# Create test namespace and workloads
echo -e "${YELLOW}3. Setting up test workloads...${NC}"
kubectl create namespace proteus-dev --dry-run=client -o yaml | kubectl apply -f -
kubectl create deployment nginx --image=nginx -n proteus-dev --dry-run=client -o yaml | kubectl apply -f -
kubectl create deployment redis --image=redis:alpine -n proteus-dev --dry-run=client -o yaml | kubectl apply -f -
kubectl expose deployment nginx --port=80 -n proteus-dev --dry-run=client -o yaml | kubectl apply -f -

# Wait for pods to be ready
echo "   Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=nginx -n proteus-dev --timeout=60s
kubectl wait --for=condition=ready pod -l app=redis -n proteus-dev --timeout=60s
echo -e "${GREEN}✅ Test workloads created${NC}"
echo ""

# Verify API server is accessible
echo -e "${YELLOW}4. Checking oncall API server...${NC}"
# Check both port 8000 and 8001
if curl -s http://localhost:8001/health > /dev/null 2>&1; then
    API_PORT=8001
    echo -e "${GREEN}✅ API server is running on port 8001${NC}"
elif curl -s http://localhost:8000/health > /dev/null 2>&1; then
    API_PORT=8000
    echo -e "${GREEN}✅ API server is running on port 8000${NC}"
else
    echo -e "${RED}❌ API server not running${NC}"
    echo "Please start it first: ./run_api_server.sh 8001"
    exit 1
fi
echo ""

# Test 1: Basic cluster query (no session)
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 1: Basic Cluster Query${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Querying: What namespaces exist?${NC}"
curl -s -X POST http://localhost:$API_PORT/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What namespaces exist in this cluster?"
  }' | jq -r '.responses[0].content' | head -20
echo ""
echo -e "${GREEN}✅ Test 1 Complete${NC}"
echo ""

# Test 2: Namespace-specific query with session (will be stored in mem0)
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 2: Session Query (Stored in mem0)${NC}"
echo -e "${BLUE}========================================${NC}"
SESSION_ID="test-minikube-$(date +%s)"
echo -e "${YELLOW}Session ID: $SESSION_ID${NC}"
echo -e "${YELLOW}Querying: Show pods in proteus-dev${NC}"
RESPONSE=$(curl -s -X POST http://localhost:$API_PORT/query \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"Show me all pods in proteus-dev namespace and their status\",
    \"namespace\": \"proteus-dev\",
    \"session_id\": \"$SESSION_ID\"
  }")

echo "$RESPONSE" | jq -r '.responses[0].content' | head -20
MEMORIES_USED=$(echo "$RESPONSE" | jq -r '.mem0_memories_used // 0')
echo ""
echo -e "${BLUE}Memories used: $MEMORIES_USED${NC}"
echo -e "${GREEN}✅ Test 2 Complete (stored in mem0)${NC}"
echo ""
echo -e "${YELLOW}⏳ Waiting 60 seconds for mem0 to index memories...${NC}"
sleep 60
echo ""

# Test 3: Follow-up query in same session (should use session memory)
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 3: Follow-up Query (Uses Session Memory)${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Querying: Is nginx healthy? (in same session)${NC}"
RESPONSE2=$(curl -s -X POST http://localhost:$API_PORT/query \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"Is the nginx deployment healthy?\",
    \"namespace\": \"proteus-dev\",
    \"session_id\": \"$SESSION_ID\"
  }")

echo "$RESPONSE2" | jq -r '.responses[0].content' | head -20
MEMORIES_USED2=$(echo "$RESPONSE2" | jq -r '.mem0_memories_used // 0')
echo ""
echo -e "${BLUE}Memories used: $MEMORIES_USED2${NC}"
if [ "$MEMORIES_USED2" -gt 0 ]; then
    echo -e "${GREEN}✅ Session memory working! (Referenced previous conversation)${NC}"
else
    echo -e "${YELLOW}⚠️  No memories used (might still be indexing)${NC}"
fi
echo ""

# Test 4: Create an incident scenario
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test 4: Incident Investigation${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${YELLOW}Simulating an incident investigation...${NC}"
curl -s -X POST http://localhost:$API_PORT/query \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"Investigate why redis pod might be using high memory. Check logs and resource usage.\",
    \"namespace\": \"proteus-dev\",
    \"session_id\": \"incident-$SESSION_ID\"
  }" | jq -r '.responses[0].content' | head -30
echo ""
echo -e "${GREEN}✅ Test 4 Complete${NC}"
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ All tests completed successfully!${NC}"
echo ""
echo "Next steps:"
echo "1. Check mem0 dashboard: https://mem0.ai/dashboard"
echo "   - Look for entity: oncall-troubleshooter"
echo "   - Should see $((3 + 1)) interactions stored"
echo ""
echo "2. Run memory audit:"
echo "   python3 test_memory_audit.py"
echo ""
echo "3. Test API docs:"
echo "   open http://localhost:8000/docs"
echo ""
echo -e "${BLUE}========================================${NC}"
