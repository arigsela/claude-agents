#!/usr/bin/env python3
"""
Test script for Microsoft Teams Webhook (Outgoing Webhook or Power Automate).

Usage:
    python scripts/test_teams_webhook.py [message]

Examples:
    # Using HMAC (native Outgoing Webhook)
    python scripts/test_teams_webhook.py "check cluster health"

    # Using API Key (Power Automate)
    python scripts/test_teams_webhook.py --api-key "check cluster health"

    # Specify custom API key
    python scripts/test_teams_webhook.py --api-key --key "my-api-key" "hello"
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests module not installed. Run: pip install requests")
    sys.exit(1)


def compute_hmac_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for Teams webhook."""
    secret_bytes = base64.b64decode(secret)
    signature = base64.b64encode(
        hmac.new(secret_bytes, body, hashlib.sha256).digest()
    ).decode()
    return f"HMAC {signature}"


def create_teams_payload(message: str, user_name: str = "Test User") -> dict:
    """Create a mock Teams activity payload."""
    return {
        "type": "message",
        "id": f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "timestamp": datetime.now().isoformat() + "Z",
        "text": f"<at>OnCall</at> {message}",
        "from": {
            "id": "test-user-id",
            "name": user_name,
            "aadObjectId": "test-aad-object-id"
        },
        "conversation": {
            "id": "19:test-conversation@thread.tacv2",
            "conversationType": "channel",
            "tenantId": "test-tenant-id",
            "name": "Test Channel"
        },
        "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/test/"
    }


def main():
    parser = argparse.ArgumentParser(
        description="Test Microsoft Teams Webhook (Outgoing Webhook or Power Automate)"
    )
    parser.add_argument(
        "message",
        nargs="?",
        default="check cluster health",
        help="Message to send to the agent (default: 'check cluster health')"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/teams/webhook",
        help="Webhook URL (default: http://localhost:8000/teams/webhook)"
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="HMAC secret (default: from TEAMS_WEBHOOK_SECRET env var)"
    )
    parser.add_argument(
        "--api-key",
        action="store_true",
        help="Use API key authentication instead of HMAC (for Power Automate)"
    )
    parser.add_argument(
        "--key",
        default=None,
        help="API key value (default: from TEAMS_API_KEY env var)"
    )
    parser.add_argument(
        "--user",
        default="Test User",
        help="User name for the mock request (default: 'Test User')"
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Check health endpoint instead of sending webhook"
    )

    args = parser.parse_args()

    if args.health:
        # Just check health endpoint
        health_url = args.url.replace("/webhook", "/health")
        print(f"Checking health at: {health_url}")
        try:
            response = requests.get(health_url)
            print(f"Status: {response.status_code}")
            print(json.dumps(response.json(), indent=2))
        except Exception as e:
            print(f"Error: {e}")
        return

    # Determine authentication method
    if args.api_key:
        # API Key authentication (Power Automate)
        api_key = args.key or os.getenv("TEAMS_API_KEY")
        if not api_key:
            print("Error: TEAMS_API_KEY not set")
            print("Set it with: export TEAMS_API_KEY=your-api-key")
            print("Or use: --key your-api-key")
            sys.exit(1)
        auth_method = "API Key"
        auth_header = f"Bearer {api_key}"
    else:
        # HMAC authentication (native Outgoing Webhook)
        secret = args.secret or os.getenv("TEAMS_WEBHOOK_SECRET")
        if not secret:
            print("Error: TEAMS_WEBHOOK_SECRET not set")
            print("Set it with: export TEAMS_WEBHOOK_SECRET=$(echo -n 'test-secret' | base64)")
            print("Or use --api-key flag for API key authentication")
            sys.exit(1)
        auth_method = "HMAC"

    # Create payload
    payload = create_teams_payload(args.message, args.user)
    body = json.dumps(payload).encode()

    # Compute HMAC signature if using HMAC auth
    if not args.api_key:
        auth_header = compute_hmac_signature(body, secret)

    print("=" * 60)
    print("Teams Webhook Test")
    print("=" * 60)
    print(f"URL: {args.url}")
    print(f"Auth Method: {auth_method}")
    print(f"Message: {args.message}")
    print(f"User: {args.user}")
    print(f"Authorization: {auth_header[:40]}...")
    print()

    # Send request
    try:
        print("Sending request...")
        response = requests.post(
            args.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": auth_header
            },
            timeout=30
        )

        print(f"Status Code: {response.status_code}")
        print()

        if response.status_code == 200:
            result = response.json()
            print("Response (Adaptive Card):")
            print("-" * 40)

            # Extract text from Adaptive Card
            if "attachments" in result and result["attachments"]:
                card = result["attachments"][0].get("content", {})
                body_blocks = card.get("body", [])
                for block in body_blocks:
                    if block.get("type") == "TextBlock":
                        print(block.get("text", ""))
                        print()
            else:
                print(json.dumps(result, indent=2))
        else:
            print("Error Response:")
            print(json.dumps(response.json(), indent=2))

    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to server")
        print("Make sure the API server is running:")
        print("  uvicorn src.api.api_server:app --reload")
    except requests.exceptions.Timeout:
        print("Error: Request timed out (>30 seconds)")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
