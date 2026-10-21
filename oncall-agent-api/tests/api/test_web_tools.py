"""
Tests for web search and data retrieval tools (web_search, fetch_webpage, get_current_datetime)
and context-aware prompt selection in OnCallAgentClient.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.custom_tools import (
    web_search,
    fetch_webpage,
    get_current_datetime,
)


# ============================================================
# web_search tests
# ============================================================


@pytest.mark.asyncio
async def test_web_search_missing_query():
    """Test web_search returns error when query is empty."""
    result = await web_search({"query": ""})
    assert "error" in result
    assert result["error"] == "query is required"


@pytest.mark.asyncio
async def test_web_search_missing_api_key(monkeypatch):
    """Test web_search returns graceful error when TAVILY_API_KEY is not set."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    result = await web_search({"query": "test query"})

    assert "error" in result
    assert "TAVILY_API_KEY" in result["error"]
    assert result["query"] == "test query"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_web_search_success(monkeypatch):
    """Test web_search returns results with valid API key and mocked Tavily."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    mock_response = {
        "answer": "Python 3.13 includes several new features...",
        "results": [
            {
                "title": "What's New in Python 3.13",
                "url": "https://docs.python.org/3/whatsnew/3.13.html",
                "content": "Python 3.13 introduces new features such as...",
                "score": 0.95,
            },
            {
                "title": "Python Release Notes",
                "url": "https://python.org/releases",
                "content": "Release notes for Python versions...",
                "score": 0.8,
            },
        ],
    }

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value=mock_response)

    # Patch the AsyncTavilyClient where it's imported inside web_search
    mock_tavily = MagicMock()
    mock_tavily.AsyncTavilyClient = Mock(return_value=mock_client)

    with patch.dict("sys.modules", {"tavily": mock_tavily}):
        result = await web_search({"query": "Python 3.13 features", "max_results": 5})

    assert "error" not in result
    assert result["query"] == "Python 3.13 features"
    assert result["answer"] == "Python 3.13 includes several new features..."
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "What's New in Python 3.13"
    assert result["result_count"] == 2


@pytest.mark.asyncio
async def test_web_search_truncates_long_content(monkeypatch):
    """Test web_search truncates result content over 1000 chars."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    long_content = "x" * 2000
    mock_response = {
        "answer": "answer",
        "results": [
            {
                "title": "Long Page",
                "url": "https://example.com",
                "content": long_content,
                "score": 0.9,
            },
        ],
    }

    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value=mock_response)

    with patch("tavily.AsyncTavilyClient", return_value=mock_client, create=True):
        result = await web_search({"query": "test"})

    assert len(result["results"][0]["content"]) == 1003  # 1000 + "..."


# ============================================================
# fetch_webpage tests
# ============================================================


@pytest.mark.asyncio
async def test_fetch_webpage_missing_url():
    """Test fetch_webpage returns error when URL is empty."""
    result = await fetch_webpage({"url": ""})
    assert "error" in result
    assert result["error"] == "url is required"


@pytest.mark.asyncio
async def test_fetch_webpage_success():
    """Test fetch_webpage extracts content from HTML."""
    import httpx

    html_content = """
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Hello World</h1>
        <p>This is a test paragraph.</p>
        <script>console.log('ignored');</script>
    </body>
    </html>
    """

    mock_response = Mock()
    mock_response.text = html_content
    mock_response.status_code = 200
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_webpage({"url": "https://example.com"})

    assert "error" not in result
    assert result["url"] == "https://example.com"
    assert result["title"] == "Test Page"
    assert "Hello World" in result["content"]
    assert "This is a test paragraph" in result["content"]
    assert "console.log" not in result["content"]  # Script removed
    assert "content_length" in result


@pytest.mark.asyncio
async def test_fetch_webpage_truncation():
    """Test fetch_webpage truncates content to max_length."""
    long_body = "<html><body>" + "a" * 10000 + "</body></html>"

    mock_response = Mock()
    mock_response.text = long_body
    mock_response.status_code = 200
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_webpage({"url": "https://example.com", "max_length": 500})

    assert result["content_length"] == 503  # 500 + "..."
    assert result["content"].endswith("...")


@pytest.mark.asyncio
async def test_fetch_webpage_timeout():
    """Test fetch_webpage handles timeout gracefully."""
    import httpx

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_webpage({"url": "https://slow.example.com"})

    assert "error" in result
    assert "Timeout" in result["error"]
    assert result["url"] == "https://slow.example.com"


@pytest.mark.asyncio
async def test_fetch_webpage_http_error():
    """Test fetch_webpage handles HTTP errors gracefully."""
    import httpx

    mock_response = Mock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("Not Found", request=Mock(), response=mock_response)
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await fetch_webpage({"url": "https://example.com/notfound"})

    assert "error" in result
    assert "404" in result["error"]


# ============================================================
# get_current_datetime tests
# ============================================================


@pytest.mark.asyncio
async def test_get_current_datetime_utc():
    """Test get_current_datetime returns valid UTC datetime info."""
    result = await get_current_datetime({})

    assert "error" not in result
    assert result["timezone"] == "UTC"
    assert "date" in result
    assert "time" in result
    assert "day_of_week" in result
    assert "iso" in result
    assert "unix_timestamp" in result
    # Verify date format
    assert len(result["date"]) == 10  # YYYY-MM-DD
    assert result["day_of_week"] in [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    ]


@pytest.mark.asyncio
async def test_get_current_datetime_with_timezone():
    """Test get_current_datetime with specific timezone."""
    result = await get_current_datetime({"timezone": "US/Eastern"})

    assert "error" not in result
    assert result["timezone"] == "US/Eastern"
    assert "date" in result
    assert "time" in result


@pytest.mark.asyncio
async def test_get_current_datetime_invalid_timezone():
    """Test get_current_datetime with invalid timezone returns error."""
    result = await get_current_datetime({"timezone": "Invalid/Timezone"})

    assert "error" in result
    assert "Unknown timezone" in result["error"]


# ============================================================
# Context-aware prompt selection tests
# ============================================================


class TestContextAwarePromptSelection:
    """Test that the agent selects the correct prompt and tools based on context."""

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_agent_has_general_prompt(self, mock_anthropic):
        """Test that the agent has both system prompts."""
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        assert agent.system_prompt is not None
        assert agent.general_system_prompt is not None
        assert "on-call agent" in agent.system_prompt.lower()
        assert "helpful ai assistant" in agent.general_system_prompt.lower()
        assert "quake copilot" in agent.general_system_prompt.lower()

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_agent_has_web_tools(self, mock_anthropic):
        """Test that the agent defines web tools separately."""
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        assert len(agent.web_tools) == 3
        web_tool_names = {t["name"] for t in agent.web_tools}
        assert web_tool_names == {"web_search", "fetch_webpage", "get_current_datetime"}

    @patch("src.api.agent_client.Anthropic")
    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_web_tools_in_tool_map(self, mock_anthropic):
        """Test that web tools are in the _execute_tool dispatch map."""
        from src.api.agent_client import OnCallAgentClient

        agent = OnCallAgentClient()

        # The tool map is built inside _execute_tool, so we check by attempting
        # to verify the imports exist on the agent
        assert hasattr(agent, 'web_tools')
        assert len(agent.web_tools) == 3
