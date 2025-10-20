#!/bin/bash
# Quick test of OnCall Agent API

echo "Testing OnCall Agent API at localhost:8000..."
echo ""

# Test query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: n8n-ROUuxjOoyhPLEfpomwVMKRtWnXyVR" \
  -d '{
    "prompt": "What services are you monitoring in dev-eks?"
  }' | jq .
