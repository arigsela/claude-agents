#!/bin/bash
# Wait for Anthropic rate limit to reset, then test

echo "⏰ Waiting 60 seconds for Anthropic rate limit to reset..."
echo "   (Rate limit: 50,000 tokens/minute per organization)"
echo ""

# Countdown
for i in {60..1}; do
    printf "\r   Time remaining: %2d seconds" $i
    sleep 1
done

echo ""
echo ""
echo "✅ Rate limit should be reset now!"
echo ""
echo "🧪 Testing with a simple query..."
echo ""

# Test with a simple query
./test_query_interactive.sh "Check chores-tracker pods"
