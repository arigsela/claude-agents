"""Tests for the CopilotKit AG-UI endpoint.

Covers:
- _clean_agent_response: XML tool-call stripping
- _extract_latest_user_message: message extraction from AG-UI input
- copilotkit_handler: SSE streaming integration
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

ag_ui = pytest.importorskip("ag_ui", reason="ag_ui not installed")


class TestCleanAgentResponse:
    """Tests for _clean_agent_response XML stripping."""

    def test_strips_function_call_xml(self):
        from orchestrator.copilotkit_endpoint import _clean_agent_response

        text = (
            "Here is the diagnosis.\n"
            "<function_calls><invoke name='tool'>"
            "<parameter>value</parameter>"
            "</invoke></function_calls>\n"
            "Final answer."
        )
        cleaned = _clean_agent_response(text)
        assert "<function_calls>" not in cleaned
        assert "Final answer." in cleaned
        assert "Here is the diagnosis." in cleaned

    def test_handles_no_xml(self):
        from orchestrator.copilotkit_endpoint import _clean_agent_response

        text = "Simple response with no XML."
        assert _clean_agent_response(text) == text

    def test_collapses_excessive_whitespace(self):
        from orchestrator.copilotkit_endpoint import _clean_agent_response

        text = "Line one\n\n\n\n\nLine two"
        cleaned = _clean_agent_response(text)
        assert "\n\n\n" not in cleaned
        assert "Line one" in cleaned
        assert "Line two" in cleaned

    def test_strips_leading_trailing_whitespace(self):
        from orchestrator.copilotkit_endpoint import _clean_agent_response

        text = "  \n  result  \n  "
        assert _clean_agent_response(text) == "result"


class TestExtractLatestUserMessage:
    """Tests for _extract_latest_user_message."""

    def test_extracts_string_content(self):
        from orchestrator.copilotkit_endpoint import _extract_latest_user_message

        msg = Mock()
        msg.role = "user"
        msg.content = "What pods are crashing?"
        input_data = Mock()
        input_data.messages = [msg]

        result = _extract_latest_user_message(input_data)
        assert result == "What pods are crashing?"

    def test_extracts_last_user_message(self):
        from orchestrator.copilotkit_endpoint import _extract_latest_user_message

        msg1 = Mock()
        msg1.role = "user"
        msg1.content = "First question"

        msg2 = Mock()
        msg2.role = "assistant"
        msg2.content = "First answer"

        msg3 = Mock()
        msg3.role = "user"
        msg3.content = "Follow-up question"

        input_data = Mock()
        input_data.messages = [msg1, msg2, msg3]

        result = _extract_latest_user_message(input_data)
        assert result == "Follow-up question"

    def test_extracts_list_content_with_text_parts(self):
        from orchestrator.copilotkit_endpoint import _extract_latest_user_message

        part = Mock()
        part.text = "hello world"

        msg = Mock()
        msg.role = "user"
        msg.content = [part]

        input_data = Mock()
        input_data.messages = [msg]

        result = _extract_latest_user_message(input_data)
        assert result == "hello world"

    def test_returns_default_on_no_messages(self):
        from orchestrator.copilotkit_endpoint import _extract_latest_user_message

        input_data = Mock()
        input_data.messages = []

        result = _extract_latest_user_message(input_data)
        assert result == "Perform a general cluster health check"

    def test_returns_default_on_no_user_messages(self):
        from orchestrator.copilotkit_endpoint import _extract_latest_user_message

        msg = Mock()
        msg.role = "assistant"
        msg.content = "Only assistant messages"

        input_data = Mock()
        input_data.messages = [msg]

        result = _extract_latest_user_message(input_data)
        assert result == "Perform a general cluster health check"


class TestBuildConversationContext:
    """Tests for _build_conversation_context."""

    def test_returns_empty_for_no_session(self):
        from orchestrator.copilotkit_endpoint import _build_conversation_context

        mgr = Mock()
        mgr.get_session.return_value = None

        result = _build_conversation_context(mgr, "thread-1")
        assert result == ""

    def test_returns_empty_for_no_messages(self):
        from orchestrator.copilotkit_endpoint import _build_conversation_context

        session = Mock()
        session.messages = []
        mgr = Mock()
        mgr.get_session.return_value = session

        result = _build_conversation_context(mgr, "thread-1")
        assert result == ""

    def test_builds_context_from_messages(self):
        from orchestrator.copilotkit_endpoint import _build_conversation_context

        session = Mock()
        session.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        mgr = Mock()
        mgr.get_session.return_value = session

        result = _build_conversation_context(mgr, "thread-1")
        assert "CONVERSATION HISTORY" in result
        assert "USER: Hello" in result
        assert "ASSISTANT: Hi there" in result

    def test_truncates_long_assistant_messages(self):
        from orchestrator.copilotkit_endpoint import _build_conversation_context

        session = Mock()
        session.messages = [
            {"role": "assistant", "content": "A" * 1000},
        ]
        mgr = Mock()
        mgr.get_session.return_value = session

        result = _build_conversation_context(mgr, "thread-1")
        assert "[truncated]" in result

    def test_handles_exception_gracefully(self):
        from orchestrator.copilotkit_endpoint import _build_conversation_context

        mgr = Mock()
        mgr.get_session.side_effect = RuntimeError("db error")

        result = _build_conversation_context(mgr, "thread-1")
        assert result == ""
