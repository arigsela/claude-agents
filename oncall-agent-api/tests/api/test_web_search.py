"""
Tests for web_search tool (Brave Search API integration)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from api.custom_tools import web_search


@pytest.mark.asyncio
async def test_web_search_success(monkeypatch):
    """Test successful web search with mocked Brave API response."""
    monkeypatch.setenv("BRAVE_API_KEY", "fake-brave-key")

    mock_response_data = {
        "web": {
            "results": [
                {
                    "title": "nginx - Docker Hub",
                    "url": "https://hub.docker.com/_/nginx",
                    "description": "Official build of Nginx.",
                },
                {
                    "title": "nginx changelog",
                    "url": "https://nginx.org/en/CHANGES",
                    "description": "Nginx release notes.",
                },
            ]
        }
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_response_data)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_session_ctx)

    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("api.custom_tools.aiohttp.ClientSession", return_value=mock_client_ctx):
        result = await web_search({"query": "nginx docker hub tags"})

    assert "error" not in result
    assert result["query"] == "nginx docker hub tags"
    assert result["result_count"] == 2
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "nginx - Docker Hub"
    assert result["results"][0]["url"] == "https://hub.docker.com/_/nginx"
    assert result["results"][1]["title"] == "nginx changelog"


@pytest.mark.asyncio
async def test_web_search_no_api_key(monkeypatch):
    """Test graceful error when BRAVE_API_KEY is not set."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    result = await web_search({"query": "test query"})

    assert "error" in result
    assert "BRAVE_API_KEY" in result["error"]
    assert result["query"] == "test query"


@pytest.mark.asyncio
async def test_web_search_empty_query():
    """Test error for empty query string."""
    result = await web_search({"query": ""})

    assert "error" in result
    assert "required" in result["error"]


@pytest.mark.asyncio
async def test_web_search_no_query():
    """Test error for missing query parameter."""
    result = await web_search({})

    assert "error" in result
    assert "required" in result["error"]


@pytest.mark.asyncio
async def test_web_search_api_error(monkeypatch):
    """Test handling of Brave API error responses (429, 500, etc.)."""
    monkeypatch.setenv("BRAVE_API_KEY", "fake-brave-key")

    mock_resp = AsyncMock()
    mock_resp.status = 429
    mock_resp.text = AsyncMock(return_value="Rate limit exceeded")

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_session_ctx)

    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("api.custom_tools.aiohttp.ClientSession", return_value=mock_client_ctx):
        result = await web_search({"query": "test query"})

    assert "error" in result
    assert "429" in result["error"]
    assert result["query"] == "test query"


@pytest.mark.asyncio
async def test_web_search_count_limit(monkeypatch):
    """Test that count is capped at 20."""
    monkeypatch.setenv("BRAVE_API_KEY", "fake-brave-key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"web": {"results": []}})

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_session_ctx)

    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("api.custom_tools.aiohttp.ClientSession", return_value=mock_client_ctx):
        result = await web_search({"query": "test", "count": 50})

    assert "error" not in result
    # Verify the capped count was passed to the API
    call_kwargs = mock_session.get.call_args
    assert call_kwargs[1]["params"]["count"] == 20


@pytest.mark.asyncio
async def test_web_search_empty_results(monkeypatch):
    """Test handling of zero search results."""
    monkeypatch.setenv("BRAVE_API_KEY", "fake-brave-key")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"web": {"results": []}})

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_session_ctx)

    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("api.custom_tools.aiohttp.ClientSession", return_value=mock_client_ctx):
        result = await web_search({"query": "xyznonexistentquery123"})

    assert "error" not in result
    assert result["result_count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_web_search_network_error(monkeypatch):
    """Test handling of aiohttp.ClientError (network failures)."""
    monkeypatch.setenv("BRAVE_API_KEY", "fake-brave-key")

    mock_session = AsyncMock()
    mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))

    mock_client_ctx = AsyncMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("api.custom_tools.aiohttp.ClientSession", return_value=mock_client_ctx):
        result = await web_search({"query": "test query"})

    assert "error" in result
    assert "Network error" in result["error"]
    assert result["query"] == "test query"
