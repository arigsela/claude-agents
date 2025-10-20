#!/usr/bin/env python3
"""
Simple test to verify Anthropic API connectivity and model availability
"""
import asyncio
import os
from dotenv import load_dotenv
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async def test_api():
    # Load environment
    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("ORCHESTRATOR_MODEL", "claude-sonnet-4-20250514")

    print(f"API Key (first 20 chars): {api_key[:20]}...")
    print(f"Model: {model}")
    print(f"Testing API connectivity...\n")

    try:
        # Create minimal options (API key is read from environment)
        options = ClaudeAgentOptions(
            model=model,
            allowed_tools=[],  # No tools for simple test
            permission_mode="bypassPermissions"
        )

        print("Creating SDK client...")
        async with ClaudeSDKClient(options=options) as client:
            print("Client connected!")
            print("Sending simple query...")

            await client.query("Say 'hello' and nothing else.")

            print("Waiting for response...")
            async for message in client.receive_response():
                print(f"Received message: {message}")

        print("\n✅ API test successful!")

    except Exception as e:
        print(f"\n❌ API test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_api())
