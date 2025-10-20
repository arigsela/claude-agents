#!/bin/bash
# Interactive Query Tester for OnCall Agent
# Usage: ./test_query_interactive.sh "your query here"

API_URL="http://localhost:8000"
API_KEY="${API_KEYS:-dev-key}"

if [ -z "$1" ]; then
    echo "Usage: $0 \"your query\""
    echo ""
    echo "Examples:"
    echo "  $0 \"Check chores-tracker pods\""
    echo "  $0 \"What do I do if vault pod restarted?\""
    echo "  $0 \"mysql is down, what's the impact?\""
    exit 1
fi

QUERY="$1"

echo "🔍 Querying OnCall Agent..."
echo "Query: $QUERY"
echo ""

# Check if API is running
if ! curl -s "$API_URL/health" > /dev/null 2>&1; then
    echo "❌ API not running at $API_URL"
    echo "Start it with: ./start_api_local.sh"
    exit 1
fi

# Send query
response=$(curl -s -X POST "$API_URL/query" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d "{\"prompt\": \"$QUERY\"}")

# Pretty print response
echo "📊 Response:"
echo "$response" | jq -r '.responses[0].content // "No response content"'

echo ""
echo "⏱️  Duration: $(echo "$response" | jq -r '.duration_ms // 0 | . / 1000 | tostring + "s"')"

echo ""
