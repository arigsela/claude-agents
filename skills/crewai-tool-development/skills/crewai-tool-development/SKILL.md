---
name: crewai-tool-development
description: >
  Extend CrewAI agent capabilities with custom tools (BaseTool, @tool decorator),
  async tools, MCP server integration, and the built-in tools catalog.
  Covers tool creation patterns, caching, error handling, transport configuration,
  and security best practices for production agent systems.
triggers:
  - "crewai tool"
  - "custom tool"
  - "mcp crewai"
  - "crewai mcp"
  - "tool development"
  - "BaseTool"
  - "tool decorator"
  - "crewai tools"
  - "agent tools"
  - "mcp integration"
  - "mcp server"
  - "async tool"
  - "crewai_tools"
  - "tool caching"
  - "tool filtering"
  - "MCPServerAdapter"
  - "MCPServerStdio"
  - "MCPServerHTTP"
  - "MCPServerSSE"
  - "crewai amp"
version: "1.0.0"
author:
  name: "Arisela"
tags: [crewai, tools, mcp, custom-tools, async, integrations, model-context-protocol, BaseTool]
category: learning
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
---

# CrewAI Tool Development Expert

Build, configure, and integrate tools that extend what CrewAI agents can do. This skill covers the full spectrum from writing a simple function-based tool to orchestrating multiple MCP servers with filtered access and custom transports.

## When to Use This Skill

- Building custom tools for CrewAI agents (BaseTool or @tool decorator)
- Integrating external services via Model Context Protocol (MCP)
- Implementing async tools for non-blocking I/O operations
- Selecting the right built-in tool from the CrewAI tools catalog
- Configuring tool caching, error handling, and security
- Setting up RAG-based search tools (directory, PDF, CSV, code docs)
- Scraping dynamic web content with Selenium-backed tools

---

## Decision Workflow

When a user needs tool capabilities, classify the request:

```
START
  |
  v
Is there a built-in CrewAI tool for this?
  |-- YES --> Use the built-in tool (see Available Tools Catalog)
  |-- NO
       |
       v
     Does the capability exist as an MCP server?
       |-- YES --> Use MCP Integration (Simple DSL or MCPServerAdapter)
       |-- NO
            |
            v
          Is the operation async (network, file I/O, long-running)?
            |-- YES --> Create an Async Custom Tool
            |-- NO  --> Create a Sync Custom Tool
```

**Key decision factors:**
- Prefer built-in tools when they match your use case -- they include error handling and caching
- Prefer MCP integration when connecting to external services that already expose MCP endpoints
- Build custom tools only when no existing option covers your need
- Use async tools whenever the underlying operation involves waiting (HTTP calls, DB queries, file reads)

---

## Creating Custom Tools

CrewAI provides two approaches for building custom tools. Both produce fully compatible tool objects that agents can use.

### Approach 1: BaseTool Subclass

Use when you need structured input validation, rich type checking, or complex initialization logic.

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type


class KubernetesLookupInput(BaseModel):
    """Input schema for the Kubernetes pod lookup tool."""
    namespace: str = Field(..., description="Kubernetes namespace to search in.")
    label_selector: str = Field(
        default="",
        description="Optional label selector (e.g. 'app=nginx')."
    )


class KubernetesPodLookup(BaseTool):
    name: str = "kubernetes_pod_lookup"
    description: str = (
        "Look up running pods in a Kubernetes namespace, optionally filtered by labels. "
        "Returns pod names, status, and restart counts."
    )
    args_schema: Type[BaseModel] = KubernetesLookupInput

    def _run(self, namespace: str, label_selector: str = "") -> str:
        from kubernetes import client, config

        config.load_incluster_config()
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector or None
        )
        lines = []
        for pod in pods.items:
            restarts = sum(
                cs.restart_count for cs in (pod.status.container_statuses or [])
            )
            lines.append(
                f"{pod.metadata.name}  status={pod.status.phase}  restarts={restarts}"
            )
        return "\n".join(lines) if lines else "No pods found."
```

**Why BaseTool?**
- Pydantic `BaseModel` schema gives agents a typed contract for inputs
- The `description` field is critical -- agents read it to decide when to invoke the tool
- You can add class-level attributes for configuration (API keys, clients, etc.)

### Approach 2: @tool Decorator

Use for quick, function-based tools where the function signature and docstring provide enough context.

```python
from crewai.tools import tool


@tool("search_incidents")
def search_incidents(query: str, max_results: int = 5) -> str:
    """Search historical incident records by keyword.

    Useful for finding past incidents related to a service or error pattern.
    Returns incident ID, title, severity, and resolution summary.
    """
    import sqlite3

    conn = sqlite3.connect("/data/incidents.db")
    cursor = conn.execute(
        "SELECT id, title, severity, resolution FROM incidents "
        "WHERE title LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", max_results)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"No incidents found matching '{query}'."

    results = []
    for row in rows:
        results.append(
            f"INC-{row[0]}: [{row[2]}] {row[1]}\n  Resolution: {row[3]}"
        )
    return "\n\n".join(results)
```

**Why @tool?**
- Less boilerplate -- the function name becomes the tool name (or pass a custom name)
- The docstring becomes the description agents see
- Type hints on parameters are used to generate the input schema automatically

---

## Async Tool Support

For operations involving network requests, database queries, or any I/O-bound work, async tools prevent blocking the main execution thread.

### Async with @tool Decorator

```python
import asyncio
import aiohttp
from crewai.tools import tool


@tool("check_service_health")
async def check_service_health(url: str, timeout: int = 10) -> str:
    """Check the health endpoint of a service and return its status.

    Performs an async HTTP GET and reports status code, response time,
    and any error messages.
    """
    try:
        async with aiohttp.ClientSession() as session:
            start = asyncio.get_event_loop().time()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                elapsed = asyncio.get_event_loop().time() - start
                body = await resp.text()
                return (
                    f"Status: {resp.status}\n"
                    f"Response time: {elapsed:.2f}s\n"
                    f"Body: {body[:500]}"
                )
    except asyncio.TimeoutError:
        return f"TIMEOUT: {url} did not respond within {timeout}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
```

### Async with BaseTool Subclass

```python
import asyncio
from crewai.tools import BaseTool


class AsyncDatabaseQuery(BaseTool):
    name: str = "async_database_query"
    description: str = "Execute a read-only SQL query against the analytics database asynchronously."

    async def _run(self, query: str) -> str:
        """Async implementation of the tool logic."""
        import aiosqlite

        async with aiosqlite.connect("/data/analytics.db") as db:
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

        if not rows:
            return "Query returned no results."

        header = " | ".join(columns)
        lines = [header, "-" * len(header)]
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        return "\n".join(lines)
```

### Using Async Tools in Crews and Flows

CrewAI handles sync and async tools transparently. No special invocation is needed:

```python
from crewai import Agent, Task, Crew, Flow
from crewai.flow.flow import start

# Standard Crew usage -- async tools work automatically
agent = Agent(
    role="Site Reliability Engineer",
    goal="Monitor service health and query metrics",
    backstory="Expert SRE with access to monitoring tools.",
    tools=[check_service_health, AsyncDatabaseQuery()],
)

task = Task(
    description="Check the health of https://api.example.com/health and query recent error rates.",
    expected_output="Health status and error rate summary.",
    agent=agent,
)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()


# Flow-based usage with async kickoff
class MonitoringFlow(Flow):
    @start()
    async def begin(self):
        crew = Crew(agents=[agent], tasks=[task])
        result = await crew.kickoff_async()
        return result
```

---

## Available Tools Catalog

CrewAI ships with 30+ ready-to-use tools. Install them with:

```bash
pip install 'crewai[tools]'
```

| Tool | Type | Description |
|:-----|:-----|:------------|
| **SerperDevTool** | Search | Google search via Serper API -- web results, news, images |
| **EXASearchTool** | Search | Exhaustive search across multiple data sources |
| **WebsiteSearchTool** | RAG | Semantic search over website content |
| **ScrapeWebsiteTool** | Scraping | Full website content extraction via HTTP |
| **ScrapeElementFromWebsiteTool** | Scraping | Targeted element extraction with CSS selectors |
| **SeleniumScrapingTool** | Scraping | Browser-automated scraping for JavaScript-heavy sites |
| **FirecrawlSearchTool** | Search | Web search via Firecrawl with structured results |
| **FirecrawlCrawlWebsiteTool** | Scraping | Multi-page website crawling via Firecrawl |
| **FirecrawlScrapeWebsiteTool** | Scraping | Single-page scraping via Firecrawl |
| **BrowserbaseLoadTool** | Scraping | Browser interaction and data extraction |
| **DirectoryReadTool** | File I/O | Read directory structures and file contents |
| **DirectorySearchTool** | RAG | Semantic search within directory contents |
| **FileReadTool** | File I/O | Read and extract data from files (multiple formats) |
| **CSVSearchTool** | RAG | Semantic search within CSV structured data |
| **JSONSearchTool** | RAG | Semantic search within JSON files |
| **XMLSearchTool** | RAG | Semantic search within XML files |
| **TXTSearchTool** | RAG | Semantic search within text files |
| **MDXSearchTool** | RAG | Semantic search within Markdown/MDX files |
| **PDFSearchTool** | RAG | Semantic search within PDF documents |
| **DOCXSearchTool** | RAG | Semantic search within Word documents |
| **CodeDocsSearchTool** | RAG | Search through code documentation |
| **GithubSearchTool** | RAG | Search within GitHub repositories |
| **PGSearchTool** | RAG | Semantic search within PostgreSQL databases |
| **RagTool** | RAG | General-purpose RAG for any data source |
| **YoutubeChannelSearchTool** | RAG | Search within YouTube channel content |
| **YoutubeVideoSearchTool** | RAG | Search within YouTube video transcripts |
| **CodeInterpreterTool** | Execution | Execute and interpret Python code |
| **DALL-E Tool** | Generation | Generate images via DALL-E API |
| **Vision Tool** | Generation | Image analysis and generation |
| **ApifyActorsTool** | Automation | Web scraping and automation via Apify Actors |
| **ComposioTool** | Integration | Bridge to Composio tool ecosystem |
| **LlamaIndexTool** | Integration | Bridge to LlamaIndex tool ecosystem |

See `references/tools-catalog.md` for the full quick-reference with import paths and configuration.

---

## MCP Integration

The Model Context Protocol (MCP) provides a standardized way for agents to communicate with external services. CrewAI supports MCP through two approaches: a simple DSL for quick integration and the MCPServerAdapter for advanced control.

### Installation

```bash
# Simple DSL Integration (recommended)
uv add mcp

# Advanced MCPServerAdapter usage
uv pip install 'crewai-tools[mcp]'
```

### Simple DSL: String References

The fastest way to connect agents to MCP servers. Use the `mcps` field on any Agent:

```python
from crewai import Agent

agent = Agent(
    role="Research Analyst",
    goal="Research and analyze information from multiple sources",
    backstory="Expert researcher with access to external data services",
    mcps=[
        # External HTTPS MCP server -- all tools
        "https://mcp.exa.ai/mcp?api_key=YOUR_KEY",

        # Specific tool from a server (use # to select)
        "https://api.weather.com/mcp#get_forecast",

        # CrewAI AMP marketplace -- full service
        "crewai-amp:financial-data",

        # CrewAI AMP marketplace -- specific tool
        "crewai-amp:research-tools#pubmed_search",
    ]
)
```

**String format rules:**
- HTTPS URLs connect to remote MCP servers
- Append `#tool_name` to select a single tool from the server
- Use `crewai-amp:service-name` for the CrewAI AMP marketplace
- Query parameters (e.g., `?api_key=...`) pass authentication

### Simple DSL: Structured Configurations

For full control over transport, authentication, and filtering:

```python
from crewai import Agent
from crewai.mcp import MCPServerStdio, MCPServerHTTP, MCPServerSSE
from crewai.mcp.filters import create_static_tool_filter

agent = Agent(
    role="DevOps Engineer",
    goal="Manage infrastructure using local and remote tools",
    backstory="Infrastructure expert with access to multiple systems",
    mcps=[
        # Local process via stdio
        MCPServerStdio(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            env={"HOME": "/app"},
            tool_filter=create_static_tool_filter(
                allowed_tool_names=["read_file", "list_directory"]
            ),
            cache_tools_list=True,
        ),

        # Remote server via HTTP (streamable by default)
        MCPServerHTTP(
            url="https://api.example.com/mcp",
            headers={"Authorization": "Bearer YOUR_TOKEN"},
            cache_tools_list=True,
        ),

        # Real-time streaming via SSE
        MCPServerSSE(
            url="https://stream.example.com/mcp/sse",
            headers={"Authorization": "Bearer YOUR_TOKEN"},
        ),
    ]
)
```

### Transport Types

| Transport | Class | Use Case | Connection |
|:----------|:------|:---------|:-----------|
| **Stdio** | `MCPServerStdio` | Local servers, scripts, CLI tools | Spawns a child process, communicates via stdin/stdout |
| **HTTP** | `MCPServerHTTP` | Remote servers, cloud APIs | HTTPS with optional streaming (`streamable=True`) |
| **SSE** | `MCPServerSSE` | Real-time data feeds, event streams | Server-Sent Events over HTTP |

### Tool Filtering

Control which tools agents can access. Two strategies:

**Static filtering** -- allow/block lists defined at configuration time:

```python
from crewai.mcp.filters import create_static_tool_filter

# Only allow specific tools
allow_filter = create_static_tool_filter(
    allowed_tool_names=["read_file", "write_file"]
)

# Block dangerous tools
block_filter = create_static_tool_filter(
    blocked_tool_names=["delete_file", "execute_command"]
)
```

**Dynamic filtering** -- context-aware decisions at runtime:

```python
from crewai.mcp.filters import create_dynamic_tool_filter, ToolFilterContext

def role_based_filter(context: ToolFilterContext, tool: dict) -> bool:
    """Block destructive tools for read-only roles."""
    if context.agent.role == "Code Reviewer":
        destructive = ["delete", "write", "execute", "modify"]
        tool_name = tool.get("name", "").lower()
        if any(word in tool_name for word in destructive):
            return False
    return True

mcps = [
    MCPServerStdio(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"],
        tool_filter=role_based_filter,
    ),
]
```

### CrewAI AMP Marketplace

The AMP marketplace provides pre-built MCP server integrations:

```python
mcps = [
    "crewai-amp:financial-data",           # All financial tools
    "crewai-amp:research-tools#pubmed_search",  # Specific research tool
    "crewai-amp:weather-service",          # Weather data
    "crewai-amp:market-analysis",          # Market analysis tools
]
```

### MCPServerAdapter (Advanced)

For scenarios requiring manual connection lifecycle management, use `MCPServerAdapter` from `crewai-tools`. The context manager pattern ensures proper cleanup:

```python
from crewai import Agent
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters
import os

# Define server parameters
server_params = StdioServerParameters(
    command="python3",
    args=["servers/my_mcp_server.py"],
    env={"UV_PYTHON": "3.12", **os.environ},
)

# Context manager handles connection lifecycle
with MCPServerAdapter(server_params, connect_timeout=60) as mcp_tools:
    print(f"Discovered tools: {[t.name for t in mcp_tools]}")

    agent = Agent(
        role="MCP Tool User",
        goal="Use MCP-provided tools for analysis",
        backstory="Agent with access to external MCP services.",
        tools=mcp_tools,
        verbose=True,
    )
    # ... build and run your Crew
```

**Filtering with MCPServerAdapter:**

```python
# Select specific tools by name
with MCPServerAdapter(server_params, "tool_a", "tool_b") as mcp_tools:
    agent = Agent(role="...", tools=mcp_tools)

# Or use dictionary-style access
with MCPServerAdapter(server_params) as mcp_tools:
    agent = Agent(role="...", tools=[mcp_tools["specific_tool"]])
```

### Using MCP with @CrewBase

When using the `@CrewBase` decorator, MCP lifecycle is managed automatically:

```python
from crewai import Agent, Crew, Task
from crewai.project import CrewBase, agent, task, crew
from mcp import StdioServerParameters
import os

@CrewBase
class ResearchCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    # Define MCP servers for the entire crew
    mcp_server_params = [
        {
            "url": "http://localhost:8001/mcp",
            "transport": "streamable-http"
        },
        StdioServerParameters(
            command="python3",
            args=["servers/research_server.py"],
            env={"UV_PYTHON": "3.12", **os.environ},
        ),
    ]

    # Optional: custom connection timeout (default is 30s)
    mcp_connect_timeout = 60

    @agent
    def researcher(self):
        return Agent(
            config=self.agents_config["researcher"],
            tools=self.get_mcp_tools()  # All MCP tools
        )

    @agent
    def writer(self):
        return Agent(
            config=self.agents_config["writer"],
            tools=self.get_mcp_tools("summarize", "format_text")  # Filtered tools
        )

    @task
    def research_task(self):
        return Task(config=self.tasks_config["research_task"])

    @crew
    def crew(self):
        return Crew(agents=self.agents, tasks=self.tasks)
```

**Key @CrewBase behaviors:**
- `get_mcp_tools()` lazily creates a shared adapter, reused by all agents
- The adapter shuts down automatically after `kickoff()` completes
- If `mcp_server_params` is not defined, `get_mcp_tools()` returns an empty list
- Pass tool names to `get_mcp_tools("tool_a", "tool_b")` to filter

### Error Handling and Resilience

MCP integration is designed to degrade gracefully:

```python
agent = Agent(
    role="Resilient Agent",
    goal="Continue working even when some servers are unavailable",
    backstory="Agent that handles infrastructure failures gracefully",
    mcps=[
        "https://reliable-server.com/mcp",       # Will work
        "https://unreachable-server.com/mcp",    # Skipped with warning
        MCPServerHTTP(
            url="https://slow-server.com/mcp",   # Times out gracefully
        ),
    ]
)
# Agent uses tools from working servers; logs warnings for failures
```

**Failure modes handled automatically:**
- Connection failures: logged as warnings, agent proceeds with available tools
- Timeouts: default 30 seconds (configurable), no hanging connections
- Authentication errors: clear log messages for debugging
- Invalid configurations: validation errors raised at agent creation time

### Security Considerations

1. **Validate MCP servers before use** -- only connect to trusted servers
2. **Use tool filtering** to restrict destructive operations per agent role
3. **Bind local servers to localhost** (127.0.0.1), not 0.0.0.0, to prevent DNS rebinding attacks
4. **Validate Origin headers** on SSE connections to prevent cross-origin exploitation
5. **Implement proper authentication** -- use headers for tokens, env vars for secrets
6. **Never expose API keys in string references** in committed code -- use environment variables

---

## Tool Configuration

### Caching Mechanism

All CrewAI tools support caching. For fine-grained control, use `cache_function`:

```python
from crewai.tools import tool


@tool("get_exchange_rate")
def get_exchange_rate(from_currency: str, to_currency: str) -> str:
    """Get the current exchange rate between two currencies."""
    import requests
    resp = requests.get(
        f"https://api.exchangerate.host/latest?base={from_currency}&symbols={to_currency}"
    )
    data = resp.json()
    rate = data["rates"][to_currency]
    return f"1 {from_currency} = {rate} {to_currency}"


def cache_if_major_pair(args, result):
    """Only cache results for major currency pairs (more stable rates)."""
    major = {"USD", "EUR", "GBP", "JPY", "CHF"}
    from_curr = args.get("from_currency", "")
    to_curr = args.get("to_currency", "")
    return from_curr in major and to_curr in major


get_exchange_rate.cache_function = cache_if_major_pair
```

### Error Handling in Custom Tools

Build robust tools with proper error handling:

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type


class GitHubRepoInput(BaseModel):
    owner: str = Field(..., description="Repository owner (user or org)")
    repo: str = Field(..., description="Repository name")


class GitHubRepoInfo(BaseTool):
    name: str = "github_repo_info"
    description: str = "Fetch metadata about a GitHub repository (stars, forks, language, description)."
    args_schema: Type[BaseModel] = GitHubRepoInput

    def _run(self, owner: str, repo: str) -> str:
        import requests

        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.Timeout:
            return f"ERROR: Request to GitHub timed out for {owner}/{repo}"
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return f"Repository {owner}/{repo} not found."
            return f"ERROR: GitHub API returned {e.response.status_code}"
        except requests.ConnectionError:
            return "ERROR: Unable to connect to GitHub API."

        data = resp.json()
        return (
            f"Repository: {data['full_name']}\n"
            f"Description: {data.get('description', 'N/A')}\n"
            f"Language: {data.get('language', 'N/A')}\n"
            f"Stars: {data['stargazers_count']}  Forks: {data['forks_count']}\n"
            f"Open Issues: {data['open_issues_count']}"
        )
```

### Connection Timeout Configuration

For MCP servers, control timeouts at multiple levels:

```python
# MCPServerAdapter -- explicit timeout
with MCPServerAdapter(server_params, connect_timeout=60) as tools:
    pass

# @CrewBase -- class-level timeout
@CrewBase
class MyCrew:
    mcp_server_params = [...]
    mcp_connect_timeout = 90  # 90 seconds for all MCP connections
```

---

## Specific Tool Deep-Dives

### DirectorySearchTool (RAG)

Semantic search within directory contents using Retrieval-Augmented Generation. Useful for letting agents search codebases, documentation, or file collections.

```python
from crewai_tools import DirectorySearchTool

# Dynamic directory -- agent specifies at runtime
search_tool = DirectorySearchTool()

# Fixed directory -- locked to a specific path
search_tool = DirectorySearchTool(directory="./src")

# Custom embeddings and vector store
from chromadb.config import Settings

search_tool = DirectorySearchTool(
    directory="./docs",
    config={
        "embedding_model": {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
            },
        },
        "vectordb": {
            "provider": "chromadb",
            "config": {
                "settings": Settings(
                    persist_directory="/data/chroma",
                    allow_reset=True,
                    is_persistent=True,
                ),
            },
        },
    }
)
```

**When to use:** Agents that need to find relevant files or code sections based on natural language queries. Pair with `FileReadTool` for reading matched files.

### SeleniumScrapingTool

Browser-automated scraping for JavaScript-heavy websites that cannot be scraped with simple HTTP requests.

```python
from crewai import Agent, Task, Crew, Process
from crewai_tools import SeleniumScrapingTool

# Basic -- agent provides URL and selector at runtime
selenium_tool = SeleniumScrapingTool()

# Pre-configured -- locked to a specific page and selector
selenium_tool = SeleniumScrapingTool(
    website_url="https://dashboard.example.com",
    css_element=".metrics-panel",
    wait_time=5,        # seconds to wait for JS to render
    return_html=False,  # return text content, not raw HTML
)

# With authentication cookies
selenium_tool = SeleniumScrapingTool(
    cookie={"name": "session", "value": "abc123", "domain": ".example.com"},
    wait_time=8,
)

# Agent integration
scraper = Agent(
    role="Web Scraper",
    goal="Extract data from dynamic web applications",
    backstory="Expert at navigating JavaScript-heavy sites with CSS selectors.",
    tools=[selenium_tool],
)

task = Task(
    description=(
        "Scrape the pricing table from https://example.com/pricing. "
        "Use CSS selector '.pricing-table' to target the content."
    ),
    expected_output="Pricing tiers with names, prices, and feature lists.",
    agent=scraper,
)

crew = Crew(agents=[scraper], tasks=[task], process=Process.sequential)
result = crew.kickoff()
```

**Parameters:**
- `website_url` -- URL to scrape (optional at init, required at runtime)
- `css_element` -- CSS selector for target elements
- `cookie` -- dict with name/value/domain for authenticated sessions
- `wait_time` -- seconds to wait for dynamic content (default: 3)
- `return_html` -- `True` for raw HTML, `False` for text (default: `False`)

**Requires:** Chrome browser installed on the host system. The tool spawns a headless Chrome instance.

---

## Best Practices

1. **Write clear descriptions** -- The tool description is the primary way agents decide which tool to use. Be specific about what the tool does and when it is useful.

2. **Define typed input schemas** -- Use Pydantic `BaseModel` with `Field(description=...)` so agents know exactly what parameters to provide and what format is expected.

3. **Return strings** -- Tool output should be a formatted string that gives the agent enough context to proceed. Avoid returning raw objects or data structures.

4. **Handle errors gracefully** -- Never let exceptions propagate unhandled. Return descriptive error messages that help the agent (and the human reviewing logs) understand what went wrong.

5. **Use caching strategically** -- Enable caching for tools with stable outputs (reference data, static files). Use `cache_function` to skip caching for time-sensitive results (exchange rates, live metrics).

6. **Prefer async for I/O** -- Any tool that makes network requests, reads databases, or performs file I/O should be async to avoid blocking the execution thread.

7. **Apply least-privilege filtering** -- When using MCP, give each agent only the tools it needs. Use `create_static_tool_filter` for simple cases and dynamic filters for role-based access control.

8. **Test tools in isolation** -- Before assigning a tool to an agent, call `_run()` directly with sample inputs to verify it works correctly. This catches issues before they surface in a multi-agent workflow.

9. **Secure credentials** -- Never hardcode API keys or tokens. Use environment variables and pass them through `env` parameters in MCP configurations.

10. **Document side effects** -- If a tool modifies state (writes files, creates PRs, sends messages), state that clearly in the description so agents do not invoke it unexpectedly.

---

## Resources

- **references/tools-catalog.md** -- Quick-reference table of all built-in tools with import paths and MCP configuration parameters
- **CrewAI Tools Repository**: https://github.com/joaomdmoura/crewai-tools
- **MCP Specification**: https://modelcontextprotocol.io/introduction
- **CrewAI MCP Demo**: https://github.com/tonykipkemboi/crewai-mcp-demo
- **CrewAI Documentation**: https://docs.crewai.com
