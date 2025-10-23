#!/usr/bin/env python
"""
Test script to verify skills integration in oncall agent_client.py
"""
import os
import sys

# Set ANTHROPIC_API_KEY from environment or use dummy for testing load functionality
if "ANTHROPIC_API_KEY" not in os.environ:
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test123"  # Dummy key for testing

sys.path.insert(0, "src")

from api.agent_client import OnCallAgentClient

def test_skills_loading():
    """Test that skills are loaded correctly."""
    print("=" * 60)
    print("Testing Skills Integration in OnCall Agent")
    print("=" * 60)

    try:
        # Initialize agent (this should load skills)
        print("\n1. Initializing OnCallAgentClient...")
        client = OnCallAgentClient()
        print("   ✅ Client initialized successfully")

        # Check system prompt
        print("\n2. Checking system prompt for skills...")
        system_prompt = client.system_prompt

        # Check for k8s-failure-patterns skill
        if "k8s-failure-patterns" in system_prompt.lower():
            print("   ✅ k8s-failure-patterns skill found in prompt")
        else:
            print("   ❌ k8s-failure-patterns skill NOT found")

        # Check for homelab-runbooks skill
        if "homelab-runbooks" in system_prompt.lower():
            print("   ✅ homelab-runbooks skill found in prompt")
        else:
            print("   ❌ homelab-runbooks skill NOT found")

        # Check for specific content from skills
        checks = [
            ("CrashLoopBackOff", "k8s-failure-patterns content"),
            ("ImagePullBackOff", "k8s-failure-patterns content"),
            ("Vault Unsealing", "homelab-runbooks content"),
            ("ECR Authentication", "homelab-runbooks content"),
            ("IMPORTANT: Using Skills Knowledge", "skills instructions"),
        ]

        print("\n3. Verifying specific skill content...")
        for search_term, description in checks:
            if search_term in system_prompt:
                print(f"   ✅ Found: {description}")
            else:
                print(f"   ❌ Missing: {description}")

        # Print prompt size
        print(f"\n4. System prompt size: {len(system_prompt):,} characters")
        print(f"   (~{len(system_prompt) / 4:.1f}K tokens estimated)")

        # Print first 500 chars of skills section if found
        if "SKILL: k8s-failure-patterns" in system_prompt:
            print("\n5. Skills section preview:")
            skill_start = system_prompt.find("SKILL: k8s-failure-patterns")
            print(f"   {system_prompt[skill_start:skill_start+200]}...")

        print("\n" + "=" * 60)
        print("✅ Skills integration test PASSED")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_skills_loading()
