# OnCall Agent API — Custom System Prompt Pass-Through Implementation Plan

## Overview
Add a `system_prompt` field to the `/query` endpoint that allows callers to pass a custom system prompt which gets prepended to the built-in prompt before being sent to the Anthropic SDK. This gives callers the ability to customize the agent's behavior per-request while preserving the existing DevOps/general knowledge context.

## Success Criteria
- [x] `/query` endpoint accepts an optional `system_prompt` field
- [x] When provided, the custom prompt is prepended to the auto-selected built-in prompt (DevOps or general)
- [x] When not provided, behavior is unchanged — zero regression
- [x] The combined prompt is passed to the Anthropic SDK `system` parameter
- [x] Existing callers (Slack, n8n, Quake Copilot) continue working identically
- [x] New field has proper validation (max length, optional)
- [x] Tests cover: custom prompt provided, custom prompt absent, interaction with context-based prompt selection

## Research Findings

### Relevant Files
- `src/api/models.py` — `QueryRequest` model (lines 17-49): needs new `system_prompt` field
- `src/api/api_server.py` — `/query` endpoint (line 257): needs to pass `system_prompt` to `agent.query()`
- `src/api/agent_client.py` — `query()` method (line 827): needs to accept and prepend custom prompt

### Existing Patterns
- **Context passing**: `QueryRequest.context` is already forwarded from the endpoint through to `agent.query()` — we follow the same pattern
- **System prompt selection**: `agent.query()` selects between DevOps and general prompts based on `context.source` — we prepend before this selected prompt

### Callers of `agent.query()`
1. `/query` endpoint in `api_server.py` (line 257) — passes `context`, will now also pass `system_prompt`
2. Slack integration (line 130) — no context, no system_prompt — unchanged
3. Hermes chartdata (line 725) — no context, no system_prompt — unchanged

## Architecture Decisions

### Decision 1: Custom prompt placement
**Options considered:**
1. Full replacement — custom prompt replaces built-in entirely
2. Prepend — custom prompt goes before built-in prompt
3. Append — custom prompt goes after built-in prompt

**Chosen:** Option 2 (Prepend) — per user preference. The custom prompt is placed first so the caller's instructions take priority, followed by the built-in DevOps/general context. Combined as: `f"{custom_prompt}\n\n{built_in_prompt}"`

### Decision 2: Field naming and validation
**Chosen:** Field name `system_prompt` with max length 10,000 chars (matching the existing `prompt` field limit). Optional, defaults to `None`.

## Implementation

### Phase 1: Add `system_prompt` field to QueryRequest
**Status:** ✅ Complete (1/1 tasks)

#### Task 1.1: Add field to Pydantic model
**Files:** `src/api/models.py`
**Steps:**
1. Add `system_prompt: str | None = Field(default=None, max_length=10000, description="Optional system prompt to prepend to the agent's built-in prompt")` to `QueryRequest`
2. Update the `json_schema_extra` example to show the new field
**Testing:**
- [x] Model accepts request with `system_prompt` present
- [x] Model accepts request with `system_prompt` absent (backward compat)
- [x] Model rejects `system_prompt` exceeding 10,000 chars

### Phase 2: Wire system_prompt through API server to agent
**Status:** ✅ Complete (1/1 tasks)

#### Task 2.1: Pass system_prompt to agent.query()
**Files:** `src/api/api_server.py`
**Steps:**
1. On line 257, add `system_prompt=query_request.system_prompt` to the `agent.query()` call
**Testing:**
- [x] Verify `system_prompt` is forwarded when present
- [x] Verify existing calls without `system_prompt` still work

### Phase 3: Accept and prepend custom prompt in agent_client
**Status:** ✅ Complete (1/1 tasks)

#### Task 3.1: Update `query()` to accept and use `system_prompt`
**Files:** `src/api/agent_client.py`
**Steps:**
1. Add `system_prompt: str | None = None` parameter to `query()` method signature
2. After the built-in prompt is selected (lines 839-848), if `system_prompt` is not None, prepend it: `final_prompt = f"{system_prompt}\n\n{selected_prompt}"`
3. Use the combined prompt in the Anthropic API call
**Testing:**
- [x] Custom prompt is prepended when provided
- [x] Built-in prompt is used alone when custom prompt is None
- [x] Works correctly with both DevOps and general modes

### Phase 4: Testing
**Status:** ✅ Complete (2/2 tasks)

#### Task 4.1: Unit tests for system_prompt pass-through
**Files:** `tests/api/test_system_prompt.py` (new file)
**Steps:**
1. Test `QueryRequest` model accepts `system_prompt`
2. Test `agent.query()` prepends custom prompt to DevOps prompt
3. Test `agent.query()` prepends custom prompt to general prompt (quake-copilot)
4. Test `agent.query()` uses built-in prompt alone when `system_prompt` is None
**Testing:**
- [x] All new tests pass (9/9)
- [x] Existing tests still pass

#### Task 4.2: Run full test suite
**Steps:**
1. Run `PYTHONPATH=oncall-agent-api/src pytest oncall-agent-api/tests/ -v`
2. Verify no regressions
**Testing:**
- [x] No regressions in existing test suite (pre-existing failures confirmed unrelated)

## End-to-End Testing
1. Send a `/query` request WITHOUT `system_prompt` — verify unchanged behavior
2. Send a `/query` request WITH `system_prompt: "Always respond in Spanish."` — verify the agent's response incorporates the custom instruction while still having DevOps context
3. Send a `/query` request with BOTH `system_prompt` and `context: {"source": "quake-copilot"}` — verify custom prompt is prepended to the general-purpose prompt

## Risks and Mitigations
- **Risk: Combined prompt too long** — Mitigation: 10,000 char limit on custom prompt; built-in prompts are ~2K chars; Anthropic supports very large system prompts
- **Risk: Custom prompt contradicts built-in prompt** — Mitigation: Prepend ordering means custom instructions come first, but built-in context is still present; this is the intended behavior

## Progress Tracking
- **Overall:** 5/5 tasks complete (100%)
- **Last Updated:** 2026-02-21
- **Current Status:** All phases complete. Ready for commit, build, and deploy.

### Phase Summary
| Phase | Status | Tasks |
|-------|--------|-------|
| Phase 1: QueryRequest Model | ✅ Complete | 1/1 |
| Phase 2: API Server Wiring | ✅ Complete | 1/1 |
| Phase 3: Agent Client | ✅ Complete | 1/1 |
| Phase 4: Testing | ✅ Complete | 2/2 |

### Test Results
- New tests: **9/9 passing** (`test_system_prompt.py`)
- Existing tests: **No regressions** (pre-existing failures confirmed unrelated)
