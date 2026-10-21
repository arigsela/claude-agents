# CrewAI Quick Reference: Task and Crew Attributes

A complete reference of all configurable attributes for CrewAI Tasks and Crews.

---

## Task Attributes

| Attribute | Parameter | Type | Required | Description |
|-----------|-----------|------|----------|-------------|
| Description | `description` | `str` | Yes | Clear, specific statement of what the task entails. Supports `{variable}` interpolation from kickoff inputs. |
| Expected Output | `expected_output` | `str` | Yes | Detailed description of what the completed task looks like. Drives agent behavior. |
| Name | `name` | `Optional[str]` | No | Identifier for the task. |
| Agent | `agent` | `Optional[BaseAgent]` | No | The agent responsible. If omitted in hierarchical process, the manager assigns it. |
| Tools | `tools` | `List[BaseTool]` | No | Tools the agent can use for this specific task (overrides agent-level tools). |
| Context | `context` | `Optional[List[Task]]` | No | Other tasks whose outputs are passed as context. Critical for building pipelines. |
| Async Execution | `async_execution` | `Optional[bool]` | No | Run task asynchronously (in parallel with next task). Default: `False`. |
| Human Input | `human_input` | `Optional[bool]` | No | Require human review of the agent's final answer. Default: `False`. |
| Markdown | `markdown` | `Optional[bool]` | No | Instruct the agent to format output in Markdown. Default: `False`. |
| Config | `config` | `Optional[Dict[str, Any]]` | No | Task-specific configuration parameters. |
| Output File | `output_file` | `Optional[str]` | No | File path to write task output. |
| Create Directory | `create_directory` | `Optional[bool]` | No | Auto-create directory for `output_file`. Default: `True`. |
| Output JSON | `output_json` | `Optional[Type[BaseModel]]` | No | Pydantic model to structure output as JSON dict. |
| Output Pydantic | `output_pydantic` | `Optional[Type[BaseModel]]` | No | Pydantic model for typed output object. |
| Callback | `callback` | `Optional[Any]` | No | Function executed after task completion. |
| Guardrail | `guardrail` | `Optional[Callable or str]` | No | Single validation function or LLM-based string description. |
| Guardrails | `guardrails` | `Optional[List[Callable or str]]` | No | List of guardrails executed sequentially. Takes precedence over `guardrail`. |
| Guardrail Max Retries | `guardrail_max_retries` | `Optional[int]` | No | Max retries when guardrail validation fails. Default: `3`. |

### Task Output Attributes (TaskOutput class)

| Attribute | Type | Description |
|-----------|------|-------------|
| `description` | `str` | The task description. |
| `summary` | `Optional[str]` | Auto-generated from the first 10 words of description. |
| `raw` | `str` | Raw string output (always present). |
| `pydantic` | `Optional[BaseModel]` | Structured output (only if `output_pydantic` was set). |
| `json_dict` | `Optional[Dict[str, Any]]` | JSON output (only if `output_json` was set). |
| `agent` | `str` | Name of the agent that executed the task. |
| `output_format` | `OutputFormat` | RAW, JSON, or Pydantic. Default: RAW. |

---

## Crew Attributes

| Attribute | Parameter | Type | Required | Description |
|-----------|-----------|------|----------|-------------|
| Tasks | `tasks` | `List[Task]` | Yes | List of tasks for the crew to execute. |
| Agents | `agents` | `List[Agent]` | Yes | List of agents in the crew. |
| Process | `process` | `Process` | No | `Process.sequential` (default) or `Process.hierarchical`. |
| Verbose | `verbose` | `bool` | No | Enable detailed execution logging. Default: `False`. |
| Manager LLM | `manager_llm` | `str` | Cond. | LLM for the auto-created manager. Required if `process=hierarchical` and no `manager_agent`. |
| Manager Agent | `manager_agent` | `Agent` | Cond. | Custom manager agent. Alternative to `manager_llm` for hierarchical. |
| Function Calling LLM | `function_calling_llm` | `str` | No | Override LLM for tool calling across all agents. |
| Config | `config` | `Dict[str, Any]` | No | Optional crew configuration. |
| Max RPM | `max_rpm` | `int` | No | Rate limit for the crew (overrides agent-level). Default: `None`. |
| Memory | `memory` | `bool` | No | Enable short-term, long-term, and entity memory. |
| Cache | `cache` | `bool` | No | Cache tool execution results. Default: `True`. |
| Embedder | `embedder` | `Dict` | No | Embedder config for memory. Default: `{"provider": "openai"}`. |
| Step Callback | `step_callback` | `Callable` | No | Called after each agent step. Does not override agent-level callbacks. |
| Task Callback | `task_callback` | `Callable` | No | Called after each task completion. |
| Share Crew | `share_crew` | `bool` | No | Share execution data with CrewAI for model training. |
| Output Log File | `output_log_file` | `bool or str` | No | `True` saves as `logs.txt`. String saves as that filename. `.json` suffix for JSON format. |
| Prompt File | `prompt_file` | `str` | No | Path to custom prompt JSON file. |
| Planning | `planning` | `bool` | No | Enable AgentPlanner before each iteration. |
| Planning LLM | `planning_llm` | `str` | No | LLM for planning. Default: `gpt-4o-mini` (requires OpenAI key). |
| Knowledge Sources | `knowledge_sources` | `List` | No | Crew-level knowledge accessible to all agents. |
| Stream | `stream` | `bool` | No | Enable streaming output. Returns `CrewStreamingOutput`. Default: `False`. |

### Crew Output Attributes (CrewOutput class)

| Attribute | Type | Description |
|-----------|------|-------------|
| `raw` | `str` | Raw string output from the final task. |
| `pydantic` | `Optional[BaseModel]` | Structured output from the final task (if configured). |
| `json_dict` | `Optional[Dict[str, Any]]` | JSON dict from the final task (if configured). |
| `tasks_output` | `List[TaskOutput]` | Individual outputs from every task in the crew. |
| `token_usage` | `Dict[str, Any]` | Token usage summary across all tasks. |

---

## Flow Decorators Reference

| Decorator | Import | Purpose | Return |
|-----------|--------|---------|--------|
| `@start()` | `from crewai.flow.flow import start` | Entry point of the flow | Any value passed to listeners |
| `@listen(method)` | `from crewai.flow.flow import listen` | Triggered when `method` completes | Any value passed to next listeners |
| `@router(method)` | `from crewai.flow.flow import router` | Routes to named listeners based on return string | A string label (e.g., `"approved"`, `"retry"`) |
| `@persist()` | `from crewai.flow.persistence import persist` | Saves state after method execution | N/A (decorator) |
| `and_(a, b)` | `from crewai.flow.flow import and_` | Wait for all listed methods to complete | Used inside `@listen()` |
| `or_(a, b)` | `from crewai.flow.flow import or_` | Proceed when any listed method completes | Used inside `@listen()` |

## Kickoff Methods Reference

| Method | Type | Description |
|--------|------|-------------|
| `kickoff(inputs)` | Sync | Standard execution |
| `kickoff_for_each(inputs)` | Sync | Execute for each item in a list |
| `akickoff(inputs)` | Native async | True async throughout execution chain |
| `akickoff_for_each(inputs)` | Native async | Native async for each input |
| `kickoff_async(inputs)` | Thread-based | Wraps sync in `asyncio.to_thread` |
| `kickoff_for_each_async(inputs)` | Thread-based | Thread-based async for each input |
