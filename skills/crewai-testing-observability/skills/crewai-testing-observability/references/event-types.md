# CrewAI Event Types Reference

Quick-reference for all event types emitted by the CrewAI event bus. Every event inherits
from `BaseEvent` and includes `timestamp` (datetime) and `type` (string identifier).

Import events from `crewai.events`.

---

## Crew Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `CrewKickoffStartedEvent` | Crew begins execution | `crew_name` |
| `CrewKickoffCompletedEvent` | Crew finishes successfully | `crew_name`, `output` |
| `CrewKickoffFailedEvent` | Crew fails during execution | `crew_name`, `error` |
| `CrewTestStartedEvent` | `crewai test` begins | `crew_name` |
| `CrewTestCompletedEvent` | `crewai test` finishes | `crew_name` |
| `CrewTestFailedEvent` | `crewai test` fails | `crew_name`, `error` |
| `CrewTrainStartedEvent` | Crew training begins | `crew_name` |
| `CrewTrainCompletedEvent` | Crew training finishes | `crew_name` |
| `CrewTrainFailedEvent` | Crew training fails | `crew_name`, `error` |

---

## Agent Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `AgentExecutionStartedEvent` | Agent starts executing a task | `agent` (Agent object) |
| `AgentExecutionCompletedEvent` | Agent completes a task | `agent`, `output` |
| `AgentExecutionErrorEvent` | Agent encounters an error | `agent`, `error` |

---

## Task Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `TaskStartedEvent` | Task execution begins | `task` (Task object) |
| `TaskCompletedEvent` | Task completes successfully | `task`, `output` |
| `TaskFailedEvent` | Task fails during execution | `task`, `error` |
| `TaskEvaluationEvent` | Task is evaluated (during testing) | `task`, `score` |

---

## Tool Usage Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `ToolUsageStartedEvent` | Tool execution begins | `tool_name`, `input` |
| `ToolUsageFinishedEvent` | Tool execution completes | `tool_name`, `output` |
| `ToolUsageErrorEvent` | Tool execution fails | `tool_name`, `error` |
| `ToolValidateInputErrorEvent` | Tool input validation fails | `tool_name`, `input`, `error` |
| `ToolExecutionErrorEvent` | Tool execution encounters error | `tool_name`, `error` |
| `ToolSelectionErrorEvent` | Error selecting a tool | `error` |

---

## Knowledge Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `KnowledgeRetrievalStartedEvent` | Knowledge retrieval begins | -- |
| `KnowledgeRetrievalCompletedEvent` | Knowledge retrieval completes | `results` |
| `KnowledgeQueryStartedEvent` | Knowledge query begins | `query` |
| `KnowledgeQueryCompletedEvent` | Knowledge query completes | `query`, `results` |
| `KnowledgeQueryFailedEvent` | Knowledge query fails | `query`, `error` |
| `KnowledgeSearchQueryFailedEvent` | Knowledge search query fails | `query`, `error` |

---

## Flow Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `FlowCreatedEvent` | Flow instance is created | `flow_name` |
| `FlowStartedEvent` | Flow begins execution | `flow_name` |
| `FlowFinishedEvent` | Flow completes execution | `flow_name`, `output` |
| `FlowPlotEvent` | Flow is plotted/visualized | `flow_name` |
| `MethodExecutionStartedEvent` | Flow method starts | `method_name` |
| `MethodExecutionFinishedEvent` | Flow method completes | `method_name`, `output` |
| `MethodExecutionFailedEvent` | Flow method fails | `method_name`, `error` |

---

## LLM Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `LLMCallStartedEvent` | LLM API call begins | `model`, `prompt` |
| `LLMCallCompletedEvent` | LLM API call completes | `model`, `token_usage`, `response` |
| `LLMCallFailedEvent` | LLM API call fails | `model`, `error` |
| `LLMStreamChunkEvent` | Streaming chunk received | `model`, `chunk` |

---

## Memory Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `MemoryQueryStartedEvent` | Memory query begins | `query`, `limit`, `score_threshold` |
| `MemoryQueryCompletedEvent` | Memory query completes | `query`, `results`, `limit`, `score_threshold`, `execution_time` |
| `MemoryQueryFailedEvent` | Memory query fails | `query`, `limit`, `score_threshold`, `error` |
| `MemorySaveStartedEvent` | Memory save begins | `value`, `metadata`, `agent_role` |
| `MemorySaveCompletedEvent` | Memory save completes | `value`, `metadata`, `agent_role`, `execution_time` |
| `MemorySaveFailedEvent` | Memory save fails | `value`, `metadata`, `agent_role`, `error` |
| `MemoryRetrievalStartedEvent` | Task prompt memory retrieval begins | `task_id` |
| `MemoryRetrievalCompletedEvent` | Task prompt memory retrieval completes | `task_id`, `memory_content`, `execution_time` |

---

## LLM Guardrail Events

| Event | Emitted When | Key Properties |
|-------|-------------|----------------|
| `LLMGuardrailStartedEvent` | Guardrail validation begins | `guardrail_name`, `retry_count` |
| `LLMGuardrailCompletedEvent` | Guardrail validation completes | `guardrail_name`, `success`, `results`, `error_message` |

---

## Handler Signature

All event handlers receive two arguments:

```python
@crewai_event_bus.on(SomeEvent)
def handler(source, event):
    # source: the object that emitted the event (Agent, Crew, Task, etc.)
    # event: the typed event instance with properties listed above
    #        event.timestamp -- when the event was emitted
    #        event.type      -- string identifier for the event type
    pass
```

---

## Import Examples

```python
# Import specific events
from crewai.events import (
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    AgentExecutionCompletedEvent,
    TaskCompletedEvent,
    ToolUsageErrorEvent,
    LLMCallCompletedEvent,
    MemoryQueryCompletedEvent,
)

# Import the event bus for scoped handlers
from crewai.events import crewai_event_bus

# Import the base class for custom listeners
from crewai.events import BaseEventListener
```
