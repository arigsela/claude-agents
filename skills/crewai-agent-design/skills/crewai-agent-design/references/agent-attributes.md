# CrewAI Agent Attributes Quick Reference

Complete reference of all `Agent` constructor parameters in CrewAI.

---

## Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `role` | `str` | Defines the agent's function and expertise within the crew. Be specific and specialized. |
| `goal` | `str` | The individual objective that guides decision-making. Should be outcome-focused with quality standards. |
| `backstory` | `str` | Provides context, personality, and experience. Enriches interactions and shapes approach to problems. |

---

## Model Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm` | `Union[str, LLM, Any]` | `"gpt-4"` | Language model powering the agent. Falls back to `OPENAI_MODEL_NAME` env var. |
| `function_calling_llm` | `Optional[Any]` | `None` | Separate LLM for tool calling. Overrides crew's LLM if set. Useful for using a cheaper/faster model for tool calls. |
| `use_system_prompt` | `Optional[bool]` | `True` | Whether to use system prompt. Set `False` for older models (e.g., o1) that don't support system messages. |

---

## Execution Control

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_iter` | `int` | `20` | Maximum iterations before the agent must provide its best answer. Increase for complex tasks. |
| `max_rpm` | `Optional[int]` | `None` | Maximum requests per minute to avoid rate limits. |
| `max_execution_time` | `Optional[int]` | `None` | Maximum time in seconds for task execution. Prevents runaway agents. |
| `max_retry_limit` | `int` | `2` | Maximum retries when an error occurs. Increase for flaky operations. |
| `verbose` | `bool` | `False` | Enable detailed execution logs. Always use `True` during development. |

---

## Tools and Capabilities

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tools` | `List[BaseTool]` | `[]` | List of tools available to the agent. Supports CrewAI Toolkit and LangChain tools. |
| `allow_code_execution` | `Optional[bool]` | `False` | Enable the agent to write and execute code. |
| `code_execution_mode` | `Literal["safe", "unsafe"]` | `"safe"` | `"safe"` uses Docker (recommended for production). `"unsafe"` runs code directly. |
| `cache` | `bool` | `True` | Cache tool results for improved performance on repetitive operations. |

---

## Memory and Context

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `respect_context_window` | `bool` | `True` | Auto-summarize conversation when context exceeds LLM limits. When `False`, execution halts on overflow. |
| `knowledge_sources` | `Optional[List[BaseKnowledgeSource]]` | `None` | Domain-specific knowledge bases available to the agent. |
| `embedder` | `Optional[Dict[str, Any]]` | `None` | Configuration for the embedder used by the agent for knowledge retrieval. |

---

## Reasoning and Planning

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `reasoning` | `bool` | `False` | Enable the agent to reflect on tasks and create an execution plan before starting. Improves quality for complex tasks. |
| `max_reasoning_attempts` | `Optional[int]` | `None` | Maximum planning iterations before proceeding. `None` means the agent refines until ready. |

---

## Multimodal and Date Awareness

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `multimodal` | `bool` | `False` | Enable processing of both text and visual (image) content. |
| `inject_date` | `bool` | `False` | Automatically inject the current date into task descriptions. Useful for time-sensitive tasks. |
| `date_format` | `str` | `"%Y-%m-%d"` | Python datetime format string for the injected date. Common: `"%B %d, %Y"` for "February 26, 2026". |

---

## Collaboration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `allow_delegation` | `bool` | `False` | Allow the agent to delegate tasks to other agents in the crew. |
| `step_callback` | `Optional[Any]` | `None` | Function called after each agent step. Useful for monitoring, logging, and debugging. |

---

## Custom Templates

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `system_template` | `Optional[str]` | `None` | Custom system prompt template. Variables `{role}`, `{goal}`, `{backstory}` are auto-populated. |
| `prompt_template` | `Optional[str]` | `None` | Custom prompt template for structuring input format. |
| `response_template` | `Optional[str]` | `None` | Custom response template for formatting agent output. |

> **Note:** When using custom templates, always define both `system_template` and `prompt_template`. The `response_template` is optional but recommended for consistent output.

---

## Common Parameter Combinations

### Research Agent
```python
Agent(role=..., goal=..., backstory=...,
      tools=[SerperDevTool()], verbose=True, respect_context_window=True)
```

### Code Agent
```python
Agent(role=..., goal=..., backstory=...,
      allow_code_execution=True, code_execution_mode="safe",
      max_execution_time=300, max_retry_limit=3)
```

### High-Volume Agent (Rate Limited)
```python
Agent(role=..., goal=..., backstory=...,
      max_rpm=10, cache=True, function_calling_llm="gpt-4o-mini")
```

### Strategic Planning Agent
```python
Agent(role=..., goal=..., backstory=...,
      reasoning=True, max_reasoning_attempts=3, max_iter=30, verbose=True)
```

### Precision Agent (No Summarization)
```python
Agent(role=..., goal=..., backstory=...,
      respect_context_window=False, max_retry_limit=1)
```

### Multimodal + Date-Aware Agent
```python
Agent(role=..., goal=..., backstory=...,
      multimodal=True, inject_date=True, date_format="%B %d, %Y")
```
