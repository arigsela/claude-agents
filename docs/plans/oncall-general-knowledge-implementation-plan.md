# OnCall Agent API — General Knowledge Mode & Web Search Implementation Plan

## Overview
Expand the oncall-agent-api to serve as a general-purpose AI assistant for the Quake Copilot desk assistant, while preserving the existing DevOps-focused behavior for all other clients (Slack, n8n, etc.). Add web search and data retrieval tools powered by Tavily.

## Success Criteria
- [x] Desk assistant (`context.source = "quake-copilot"`) receives a general-purpose assistant that can answer any question
- [x] All other clients (Slack, n8n) continue to get the DevOps-focused on-call agent — zero behavior change
- [x] `web_search` tool returns relevant search results via Tavily API
- [x] `fetch_webpage` tool extracts clean text content from URLs
- [x] `get_current_datetime` tool provides current date/time/timezone info
- [x] Web tools are available to the desk assistant; DevOps tools remain available too
- [x] Graceful degradation when Tavily API key is not configured
- [x] Existing tests pass, new tools have tests

## Research Findings

### Relevant Files
- `src/api/agent_client.py` — Core agent: system prompt, tool definitions, tool execution loop, query method
- `src/api/custom_tools.py` — All 22 tool implementations (K8s, GitHub, AWS, GitOps, etc.)
- `src/api/api_server.py` — FastAPI app, `/query` endpoint assembles context and calls `agent.query()`
- `src/api/models.py` — Pydantic models for `QueryRequest`, `QueryResponse`
- `requirements.txt` — Current dependencies
- `.env.example` — Environment variable template

### Existing Patterns
- **Tool registration**: 3-step pattern — (1) implement async function in `custom_tools.py`, (2) add Anthropic tool schema in `_define_tools()`, (3) add to `tool_map` in `_execute_tool()`
- **Context passing**: `QueryRequest.context` is a `dict[str, Any]` — the desk assistant sends `{"source": "quake-copilot"}`
- **System prompt**: Single static string returned by `_get_system_prompt()` — needs to become context-aware

### Dependencies
- Tavily Python SDK (`tavily-python`) — for web search
- BeautifulSoup4 (`beautifulsoup4`) — for HTML text extraction from web pages
- `httpx` — already installed, used for HTTP requests

## Architecture Decisions

### Decision 1: Context-Aware System Prompt Selection
**Options considered:**
1. **Separate endpoint** (`/query/general`) — clean separation but requires desk assistant code changes
2. **Mode field on QueryRequest** — flexible but adds API surface
3. **Context-based detection** (`source: quake-copilot`) — no API changes, no client changes needed

**Chosen:** Option 3 — detect `source` in the existing context dict. The desk assistant already sends `context: {"source": "quake-copilot"}`. This requires zero changes to the desk assistant's `OnCallService` and zero changes to the API contract.

### Decision 2: Tool Availability per Mode
**Options considered:**
1. **All tools available in both modes** — general mode gets DevOps + web tools
2. **Separate tool sets** — general mode only gets web tools, no DevOps
3. **Superset for general** — general mode gets web + DevOps tools, DevOps mode stays as-is

**Chosen:** Option 3 — the desk assistant gets all tools (web search + DevOps). This means you can ask "search for FastAPI best practices" AND "check the health of chores-tracker" from the same desk device. DevOps-only clients don't get web tools (no need, reduces token usage).

## Implementation

### Phase 1: Add Web Tools to `custom_tools.py`
**Status:** ✅ Complete (3/3 tasks)

#### Task 1.1: Add `web_search` tool implementation
**Files:** `src/api/custom_tools.py`
**Steps:**
1. Add a new section `# Web Search & Data Retrieval Tools` at the bottom of the file
2. Implement `async def web_search(args: dict) -> dict` that:
   - Takes `query` (required), `max_results` (default 5), `search_depth` (basic/advanced, default basic)
   - Uses Tavily `AsyncTavilyClient` for search
   - Returns `{"results": [...], "query": str, "answer": str}` — Tavily provides an AI-generated answer plus source results
   - Gracefully handles missing `TAVILY_API_KEY` by returning an error message
   - Truncates individual result content to 1000 chars to avoid token bloat
**Testing:**
- [x] Test with valid query returns results
- [x] Test with missing API key returns graceful error
- [x] Test result truncation works correctly

#### Task 1.2: Add `fetch_webpage` tool implementation
**Files:** `src/api/custom_tools.py`
**Steps:**
1. Implement `async def fetch_webpage(args: dict) -> dict` that:
   - Takes `url` (required), `max_length` (default 5000 chars)
   - Uses `httpx.AsyncClient` to fetch the URL (10s timeout)
   - Uses BeautifulSoup to extract text from `<body>`, stripping scripts/styles
   - Truncates to `max_length`
   - Returns `{"url": str, "title": str, "content": str, "content_length": int}`
   - Handles errors (timeout, connection error, non-200 status)
**Testing:**
- [x] Test with valid URL returns content
- [x] Test with invalid URL returns error
- [x] Test content truncation
- [x] Test timeout handling

#### Task 1.3: Add `get_current_datetime` tool implementation
**Files:** `src/api/custom_tools.py`
**Steps:**
1. Implement `async def get_current_datetime(args: dict) -> dict` that:
   - Takes optional `timezone` (default "UTC")
   - Returns current date, time, day of week, unix timestamp
   - Uses `datetime` and `zoneinfo.ZoneInfo`
**Testing:**
- [x] Test returns valid datetime info
- [x] Test with different timezone

### Phase 2: Register Tools & Context-Aware System Prompt in `agent_client.py`
**Status:** ✅ Complete (3/3 tasks)

#### Task 2.1: Add context-aware system prompt
**Files:** `src/api/agent_client.py`
**Steps:**
1. Add a new method `_get_general_system_prompt()` that returns a general-purpose assistant prompt:
   - "You are a helpful AI assistant on Ari's desktop device (Quake Copilot)..."
   - Mentions web search and webpage tools are available
   - Notes that DevOps/K8s tools are also available for infrastructure questions
   - Keeps responses concise (bar display is small)
2. Modify `query()` method signature to accept optional `context: dict | None = None`
3. In `query()`, check if `context.get("source") == "quake-copilot"` and select the appropriate system prompt
4. When in general mode, use the combined tool set (web + DevOps)
**Testing:**
- [x] Verify general prompt is selected when source is quake-copilot
- [x] Verify DevOps prompt is selected for all other sources
- [x] Verify None context defaults to DevOps prompt

#### Task 2.2: Add web tool schemas to `_define_tools()`
**Files:** `src/api/agent_client.py`
**Steps:**
1. Add Anthropic tool schemas for `web_search`, `fetch_webpage`, `get_current_datetime`
2. Store them in a separate list `_web_tools` so they can be conditionally included
3. Modify `_define_tools()` to return base DevOps tools
4. Add `_define_web_tools()` that returns the web-specific tool schemas
5. In `query()`, combine tool sets based on context
**Testing:**
- [x] Verify tool schemas are valid Anthropic format
- [x] Verify web tools are included for quake-copilot queries
- [x] Verify web tools are NOT included for other queries

#### Task 2.3: Add web tools to `_execute_tool()` map
**Files:** `src/api/agent_client.py`
**Steps:**
1. Import `web_search`, `fetch_webpage`, `get_current_datetime` from `custom_tools`
2. Add them to the `tool_map` dict in `_execute_tool()`
**Testing:**
- [x] Verify tool dispatch works for all three new tools

### Phase 3: Wire Up Context in API Server
**Status:** ✅ Complete (1/1 tasks)

#### Task 3.1: Pass context to agent.query()
**Files:** `src/api/api_server.py`
**Steps:**
1. In `query_agent()`, pass `query_request.context` to `agent.query()`
2. Currently: `agent_result = await agent.query(full_query)`
3. Change to: `agent_result = await agent.query(full_query, context=query_request.context)`
**Testing:**
- [x] Verify context is passed through correctly
- [x] Verify existing queries without context still work

### Phase 4: Dependencies & Configuration
**Status:** ✅ Complete (2/2 tasks)

#### Task 4.1: Add new dependencies
**Files:** `requirements.txt`
**Steps:**
1. Add `tavily-python>=0.5.0`
2. Add `beautifulsoup4>=4.12.0`
**Testing:**
- [x] Verify `pip install -r requirements.txt` succeeds

#### Task 4.2: Add environment variable documentation
**Files:** `.env.example`
**Steps:**
1. Add section for web search configuration:
   ```
   # Web Search (Tavily) — Required for AI Desk Assistant web search
   TAVILY_API_KEY=tvly-your-key-here
   ```
**Testing:**
- [x] Verify .env.example is complete and documented

### Phase 5: Testing
**Status:** ✅ Complete (3/3 tasks)

#### Task 5.1: Unit tests for web tools
**Files:** `tests/api/test_web_tools.py` (new file)
**Steps:**
1. Test `web_search` with mocked Tavily client
2. Test `fetch_webpage` with mocked httpx response
3. Test `get_current_datetime` (no mocking needed)
4. Test error handling for all tools
**Testing:**
- [x] All new tests pass (15/15)
- [x] `pytest tests/api/test_web_tools.py -v` green

#### Task 5.2: Test context-aware prompt selection
**Files:** `tests/api/test_agent_client.py` (existing or new)
**Steps:**
1. Test that quake-copilot context selects general prompt
2. Test that missing context selects DevOps prompt
3. Test that Slack context selects DevOps prompt
**Testing:**
- [x] All prompt selection tests pass (3/3 in TestContextAwarePromptSelection)

#### Task 5.3: Run existing test suite
**Steps:**
1. Run `PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/ -v`
2. Verify no regressions
**Testing:**
- [x] No regressions (verified pre-existing failures are unrelated to changes)

## End-to-End Testing
1. Start oncall-agent-api locally
2. Create a session with `user_id: "quake-copilot"`
3. Send a general knowledge query with `context: {"source": "quake-copilot"}` — verify it answers naturally
4. Send a web search query (e.g., "search for latest Python 3.13 features") — verify it uses the web_search tool
5. Send a DevOps query from the desk assistant (e.g., "check chores-tracker health") — verify it still uses K8s tools
6. Send a query WITHOUT quake-copilot context — verify it stays in DevOps-only mode
7. Verify Slack `/oncall` commands still work identically

## Risks and Mitigations
- **Risk: Tavily API key not set** — Mitigation: `web_search` returns a clear error message; agent still answers from its own knowledge
- **Risk: Web search returns too much text** — Mitigation: Truncate results to 1000 chars each, limit to 5 results max
- **Risk: General mode confuses DevOps queries** — Mitigation: The general prompt explicitly mentions DevOps tools are available for infrastructure questions
- **Risk: Increased token usage from larger tool set** — Mitigation: Web tools are only included for quake-copilot requests; 3 extra tool schemas add ~500 tokens which is negligible

## Progress Tracking
- **Overall:** 12/12 tasks complete (100%)
- **Last Updated:** 2026-02-21
- **Current Status:** All phases complete. Ready for E2E testing and deployment.

### Phase Summary
| Phase | Status | Tasks |
|-------|--------|-------|
| Phase 1: Web Tools | ✅ Complete | 3/3 |
| Phase 2: Agent Registration | ✅ Complete | 3/3 |
| Phase 3: API Wiring | ✅ Complete | 1/1 |
| Phase 4: Dependencies | ✅ Complete | 2/2 |
| Phase 5: Testing | ✅ Complete | 3/3 |

### Test Results
- New tests: **15/15 passing** (`test_web_tools.py`)
- Existing tests: **No regressions** (pre-existing failures confirmed on main branch)
