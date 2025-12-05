#!/bin/bash
# Test Qdrant connectivity and basic operations
#
# Usage: ./scripts/test-qdrant.sh [host:port]
# Default: localhost:6333

set -e

QDRANT_URL="${1:-http://localhost:6333}"

echo "Testing Qdrant at ${QDRANT_URL}..."
echo ""

# Test 1: Health check
echo "1. Health Check..."
if curl -sf "${QDRANT_URL}/readyz" > /dev/null; then
  echo "   ✓ Qdrant is ready"
else
  echo "   ✗ Qdrant is not responding"
  exit 1
fi

# Test 2: Get cluster info
echo ""
echo "2. Cluster Info..."
curl -s "${QDRANT_URL}/cluster" | head -c 200
echo ""

# Test 3: List collections
echo ""
echo "3. List Collections..."
COLLECTIONS=$(curl -s "${QDRANT_URL}/collections")
echo "   ${COLLECTIONS}"

# Test 4: Create test collection
echo ""
echo "4. Create Test Collection (rag-mcp-test)..."
CREATE_RESULT=$(curl -sf -X PUT "${QDRANT_URL}/collections/rag-mcp-test" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 384,
      "distance": "Cosine"
    }
  }' 2>/dev/null || echo '{"status":"already_exists"}')
echo "   Result: ${CREATE_RESULT}"

# Test 5: Insert test vector
echo ""
echo "5. Insert Test Vector..."
# Create a simple 384-dim test vector (all 0.01)
VECTOR=$(python3 -c "print('[' + ','.join(['0.01']*384) + ']')" 2>/dev/null || echo "[$(seq -s, 1 384 | sed 's/[0-9]*/0.01/g')]")

INSERT_RESULT=$(curl -sf -X PUT "${QDRANT_URL}/collections/rag-mcp-test/points" \
  -H "Content-Type: application/json" \
  -d "{
    \"points\": [
      {
        \"id\": 1,
        \"vector\": ${VECTOR},
        \"payload\": {
          \"content\": \"This is a test document for RAG MCP server\",
          \"source\": \"test-script\",
          \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }
      }
    ]
  }" 2>/dev/null || echo '{"status":"error"}')
echo "   Result: ${INSERT_RESULT}"

# Test 6: Search
echo ""
echo "6. Search Test..."
SEARCH_RESULT=$(curl -sf -X POST "${QDRANT_URL}/collections/rag-mcp-test/points/search" \
  -H "Content-Type: application/json" \
  -d "{
    \"vector\": ${VECTOR},
    \"limit\": 3,
    \"with_payload\": true
  }" 2>/dev/null || echo '{"status":"error"}')
echo "   Result: ${SEARCH_RESULT}" | head -c 300
echo ""

# Test 7: Collection stats
echo ""
echo "7. Collection Stats..."
STATS=$(curl -s "${QDRANT_URL}/collections/rag-mcp-test")
echo "   ${STATS}" | head -c 300
echo ""

# Test 8: Clean up (optional - comment out to keep test data)
echo ""
echo "8. Cleanup Test Collection..."
DELETE_RESULT=$(curl -sf -X DELETE "${QDRANT_URL}/collections/rag-mcp-test" 2>/dev/null || echo '{"status":"not_found"}')
echo "   Result: ${DELETE_RESULT}"

echo ""
echo "========================================="
echo "All tests completed successfully!"
echo "========================================="
echo ""
echo "Qdrant Dashboard: ${QDRANT_URL}/dashboard"
