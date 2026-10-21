# CrewAI Tools Catalog -- Quick Reference

Quick-reference for all built-in CrewAI tools and MCP configuration parameters.

## Installation

```bash
pip install 'crewai[tools]'
```

All tools are imported from `crewai_tools`:

```python
from crewai_tools import SerperDevTool, DirectoryReadTool, FileReadTool
```

---

## Built-In Tools

### Search Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `SerperDevTool` | `from crewai_tools import SerperDevTool` | None (uses `SERPER_API_KEY` env var) | Google search -- web, news, images |
| `EXASearchTool` | `from crewai_tools import EXASearchTool` | None | Exhaustive multi-source search |
| `FirecrawlSearchTool` | `from crewai_tools import FirecrawlSearchTool` | None | Web search via Firecrawl |

### RAG (Retrieval-Augmented Generation) Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `RagTool` | `from crewai_tools import RagTool` | `config` | General-purpose RAG, any data source |
| `DirectorySearchTool` | `from crewai_tools import DirectorySearchTool` | `directory`, `config` | Semantic search within directories |
| `CodeDocsSearchTool` | `from crewai_tools import CodeDocsSearchTool` | `config` | Code documentation search |
| `CSVSearchTool` | `from crewai_tools import CSVSearchTool` | `csv` (file path) | Structured CSV data search |
| `DOCXSearchTool` | `from crewai_tools import DOCXSearchTool` | `docx` (file path) | Word document search |
| `GithubSearchTool` | `from crewai_tools import GithubSearchTool` | `github_repo`, `content_types` | GitHub repository search |
| `JSONSearchTool` | `from crewai_tools import JSONSearchTool` | `json_path` | JSON file search |
| `MDXSearchTool` | `from crewai_tools import MDXSearchTool` | `mdx` (file path) | Markdown/MDX search |
| `PDFSearchTool` | `from crewai_tools import PDFSearchTool` | `pdf` (file path) | PDF document search |
| `PGSearchTool` | `from crewai_tools import PGSearchTool` | `db_uri` | PostgreSQL database search |
| `TXTSearchTool` | `from crewai_tools import TXTSearchTool` | `txt` (file path) | Plain text file search |
| `WebsiteSearchTool` | `from crewai_tools import WebsiteSearchTool` | `website` (URL) | Website content search |
| `XMLSearchTool` | `from crewai_tools import XMLSearchTool` | `xml` (file path) | XML file search |
| `YoutubeChannelSearchTool` | `from crewai_tools import YoutubeChannelSearchTool` | `youtube_channel_handle` | YouTube channel search |
| `YoutubeVideoSearchTool` | `from crewai_tools import YoutubeVideoSearchTool` | `youtube_video_url` | YouTube video transcript search |

### File I/O Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `DirectoryReadTool` | `from crewai_tools import DirectoryReadTool` | `directory` | Read directory structures and contents |
| `FileReadTool` | `from crewai_tools import FileReadTool` | None | Read files in various formats |

### Scraping Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `ScrapeWebsiteTool` | `from crewai_tools import ScrapeWebsiteTool` | `website_url` | Full website scraping via HTTP |
| `ScrapeElementFromWebsiteTool` | `from crewai_tools import ScrapeElementFromWebsiteTool` | `website_url`, `css_element` | Targeted element extraction |
| `SeleniumScrapingTool` | `from crewai_tools import SeleniumScrapingTool` | `website_url`, `css_element`, `wait_time`, `cookie`, `return_html` | Browser-automated scraping (requires Chrome) |
| `FirecrawlCrawlWebsiteTool` | `from crewai_tools import FirecrawlCrawlWebsiteTool` | `url` | Multi-page crawling via Firecrawl |
| `FirecrawlScrapeWebsiteTool` | `from crewai_tools import FirecrawlScrapeWebsiteTool` | `url` | Single-page scraping via Firecrawl |
| `BrowserbaseLoadTool` | `from crewai_tools import BrowserbaseLoadTool` | None | Browser interaction and extraction |

### Code & Execution Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `CodeInterpreterTool` | `from crewai_tools import CodeInterpreterTool` | None | Execute Python code |

### Generation Tools

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `DALL-E Tool` | `from crewai_tools import DallETool` | None | Image generation via DALL-E |
| `Vision Tool` | `from crewai_tools import VisionTool` | None | Image analysis |

### Integration Bridges

| Tool | Import | Key Parameters | Notes |
|:-----|:-------|:---------------|:------|
| `ApifyActorsTool` | `from crewai_tools import ApifyActorsTool` | `actor_id` | Apify Actors for web scraping/automation |
| `ComposioTool` | `from crewai_tools import ComposioTool` | Varies | Bridge to Composio ecosystem |
| `LlamaIndexTool` | `from crewai_tools import LlamaIndexTool` | Varies | Bridge to LlamaIndex ecosystem |

---

## RAG Tool Configuration

All RAG tools accept a `config` parameter for custom embeddings and vector stores:

```python
tool = DirectorySearchTool(
    directory="./docs",
    config={
        "embedding_model": {
            "provider": "openai",        # or "huggingface", "cohere"
            "config": {
                "model": "text-embedding-3-small",
                # "api_key": "sk-..."   # Optional, defaults to env var
            },
        },
        "vectordb": {
            "provider": "chromadb",      # or "qdrant"
            "config": {
                # ChromaDB settings
                # "settings": Settings(persist_directory="...", is_persistent=True)

                # Qdrant settings
                # "vectors_config": VectorParams(size=384, distance=Distance.COSINE)
            },
        },
    }
)
```

---

## MCP Configuration Parameters

### MCPServerStdio

| Parameter | Type | Required | Default | Description |
|:----------|:-----|:---------|:--------|:------------|
| `command` | `str` | Yes | -- | Command to execute (`"python"`, `"node"`, `"npx"`, `"uvx"`) |
| `args` | `list[str]` | No | `[]` | Command arguments |
| `env` | `dict[str, str]` | No | `{}` | Environment variables for the process |
| `tool_filter` | `Callable` | No | `None` | Static or dynamic tool filter |
| `cache_tools_list` | `bool` | No | `False` | Cache discovered tools for faster access |

### MCPServerHTTP

| Parameter | Type | Required | Default | Description |
|:----------|:-----|:---------|:--------|:------------|
| `url` | `str` | Yes | -- | Server URL (HTTPS recommended) |
| `headers` | `dict[str, str]` | No | `{}` | HTTP headers (e.g., Authorization) |
| `streamable` | `bool` | No | `True` | Use streamable HTTP transport |
| `tool_filter` | `Callable` | No | `None` | Static or dynamic tool filter |
| `cache_tools_list` | `bool` | No | `False` | Cache discovered tools for faster access |

### MCPServerSSE

| Parameter | Type | Required | Default | Description |
|:----------|:-----|:---------|:--------|:------------|
| `url` | `str` | Yes | -- | SSE endpoint URL |
| `headers` | `dict[str, str]` | No | `{}` | HTTP headers (e.g., Authorization) |
| `tool_filter` | `Callable` | No | `None` | Static or dynamic tool filter |
| `cache_tools_list` | `bool` | No | `False` | Cache discovered tools for faster access |

### MCPServerAdapter

| Parameter | Type | Required | Default | Description |
|:----------|:-----|:---------|:--------|:------------|
| `server_params` | `StdioServerParameters` or `dict` | Yes | -- | Server configuration |
| `*tool_names` | `str` | No | -- | Positional args to filter specific tools |
| `connect_timeout` | `int` | No | `30` | Connection timeout in seconds |

### Tool Filter Functions

```python
from crewai.mcp.filters import create_static_tool_filter, create_dynamic_tool_filter

# Static: allow list
filter = create_static_tool_filter(allowed_tool_names=["read_file", "write_file"])

# Static: block list
filter = create_static_tool_filter(blocked_tool_names=["delete_file"])

# Dynamic: context-aware
def my_filter(context: ToolFilterContext, tool: dict) -> bool:
    return True  # or False to exclude
```
