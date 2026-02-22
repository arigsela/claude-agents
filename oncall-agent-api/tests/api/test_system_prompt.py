"""
Tests for system_prompt pass-through feature.

Verifies that:
1. QueryRequest model accepts/validates system_prompt field
2. agent.query() prepends custom prompt to built-in prompts
3. Backward compatibility when system_prompt is not provided
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ============================================================
# QueryRequest model tests
# ============================================================


class TestQueryRequestSystemPrompt:
    """Test QueryRequest model validation for system_prompt field."""

    def test_accepts_system_prompt(self):
        """Test model accepts a valid system_prompt."""
        from src.api.models import QueryRequest

        req = QueryRequest(
            prompt="What pods are running?",
            system_prompt="Always respond in bullet points.",
        )
        assert req.system_prompt == "Always respond in bullet points."

    def test_system_prompt_optional(self):
        """Test model works without system_prompt (backward compat)."""
        from src.api.models import QueryRequest

        req = QueryRequest(prompt="What pods are running?")
        assert req.system_prompt is None

    def test_system_prompt_none_explicit(self):
        """Test model accepts explicit None for system_prompt."""
        from src.api.models import QueryRequest

        req = QueryRequest(prompt="What pods are running?", system_prompt=None)
        assert req.system_prompt is None

    def test_system_prompt_max_length(self):
        """Test model rejects system_prompt exceeding 10,000 chars."""
        from src.api.models import QueryRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            QueryRequest(prompt="test", system_prompt="x" * 10001)

    def test_system_prompt_at_max_length(self):
        """Test model accepts system_prompt at exactly 10,000 chars."""
        from src.api.models import QueryRequest

        req = QueryRequest(prompt="test", system_prompt="x" * 10000)
        assert len(req.system_prompt) == 10000


# ============================================================
# agent.query() system prompt prepend tests
# ============================================================


class TestAgentQuerySystemPrompt:
    """Test that agent.query() prepends custom system_prompt correctly."""

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_custom_prompt_prepended_devops_mode(self, mock_anthropic_cls):
        """Test custom prompt is prepended to DevOps prompt."""
        import asyncio
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        # Mock the Anthropic client response
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.text = "Response text"
        mock_text_block.type = "text"
        mock_response.content = [mock_text_block]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        agent.client.messages.create = MagicMock(return_value=mock_response)

        custom_prompt = "Focus on memory issues only."
        asyncio.get_event_loop().run_until_complete(
            agent.query("check pods", system_prompt=custom_prompt)
        )

        # Verify the system prompt passed to Anthropic starts with custom prompt
        call_args = agent.client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", call_args[1].get("system", ""))
        assert system_arg.startswith(custom_prompt)
        assert "on-call agent" in system_arg.lower()

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_custom_prompt_prepended_general_mode(self, mock_anthropic_cls):
        """Test custom prompt is prepended to general prompt (quake-copilot)."""
        import asyncio
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.text = "Response"
        mock_text_block.type = "text"
        mock_response.content = [mock_text_block]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        agent.client.messages.create = MagicMock(return_value=mock_response)

        custom_prompt = "Respond in Spanish."
        asyncio.get_event_loop().run_until_complete(
            agent.query(
                "what time is it",
                context={"source": "quake-copilot"},
                system_prompt=custom_prompt,
            )
        )

        call_args = agent.client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", call_args[1].get("system", ""))
        assert system_arg.startswith(custom_prompt)
        assert "helpful ai assistant" in system_arg.lower()

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_no_custom_prompt_uses_builtin(self, mock_anthropic_cls):
        """Test that without custom prompt, built-in prompt is used alone."""
        import asyncio
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.text = "Response"
        mock_text_block.type = "text"
        mock_response.content = [mock_text_block]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        agent.client.messages.create = MagicMock(return_value=mock_response)

        asyncio.get_event_loop().run_until_complete(agent.query("check pods"))

        call_args = agent.client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", call_args[1].get("system", ""))
        # Should be the raw DevOps prompt without any prepended text
        assert system_arg == agent.system_prompt

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_none_system_prompt_uses_builtin(self, mock_anthropic_cls):
        """Test that explicit None system_prompt uses built-in prompt."""
        import asyncio
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.text = "Response"
        mock_text_block.type = "text"
        mock_response.content = [mock_text_block]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        agent.client.messages.create = MagicMock(return_value=mock_response)

        asyncio.get_event_loop().run_until_complete(
            agent.query("check pods", system_prompt=None)
        )

        call_args = agent.client.messages.create.call_args
        system_arg = call_args.kwargs.get("system", call_args[1].get("system", ""))
        assert system_arg == agent.system_prompt
