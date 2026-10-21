---
name: crewai-testing-observability
description: >
  Test, monitor, and customize CrewAI applications with CLI testing, event listeners,
  fingerprinting, prompt customization, and multimodal file handling. Covers the full
  observability lifecycle from development testing through production monitoring.
triggers:
  - "crewai test"
  - "crewai event"
  - "event listener"
  - "crewai prompt"
  - "crewai fingerprint"
  - "crewai observability"
  - "crewai monitoring"
  - "crewai files"
  - "crewai multimodal"
  - "crewai debug"
  - "crewai performance"
  - "crewai trace"
  - "crewai scoring"
  - "crewai replay"
  - "crewai log"
  - "crew testing"
  - "agent tracking"
  - "prompt customization crewai"
  - "custom prompts crewai"
  - "file handling crewai"
version: "1.0.0"
author:
  name: "Arisela"
tags: [crewai, testing, observability, events, prompts, fingerprinting, monitoring, files, multimodal]
category: learning
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
---

# CrewAI Testing & Observability Expert

Build reliable, observable, and customizable CrewAI applications. This skill covers the full
lifecycle of quality assurance for CrewAI projects -- from iterative CLI testing and performance
scoring, through real-time event monitoring and component tracking, to deep prompt customization
and multimodal file handling.

## When to Use This Skill

- Running performance tests on a CrewAI crew and interpreting score tables
- Building custom event listeners for logging, analytics, or external integrations
- Tracking agents, crews, and tasks with fingerprints across their lifecycle
- Customizing or overriding CrewAI's default prompt injections
- Passing images, PDFs, audio, video, or text files to agents for multimodal processing
- Debugging agent behavior with observability tooling
- Replaying or inspecting individual task outputs

---

## Decision Workflow

When a user asks about CrewAI quality or observability, classify their need:

```
User Request
    |
    +-- "How do I test my crew?" -----------> Section 1: Testing with CLI
    |
    +-- "How do I monitor events?" ---------> Section 2: Event Listener System
    |
    +-- "How do I track components?" -------> Section 3: Fingerprinting
    |
    +-- "How do I customize prompts?" ------> Section 4: Prompt Customization
    |
    +-- "How do I pass files to agents?" ---> Section 5: Multimodal File Handling
    |
    +-- "How do I debug agent behavior?" ---> Combine Sections 1 + 2 + 4
    |
    +-- "How do I set up observability?" ---> Combine Sections 2 + 3
```

---

## 1. Testing with the CLI

CrewAI ships a built-in `crewai test` command that runs your crew multiple times against an
evaluator LLM, then scores each task on a 1-10 scale. This is the fastest way to benchmark
crew quality without writing custom evaluation code.

### Basic Usage

```bash
# Default: 2 iterations, gpt-4o-mini as evaluator
crewai test

# Custom iterations and evaluator model
crewai test --n_iterations 5 --model gpt-4o

# Short form
crewai test -n 5 -m gpt-4o
```

**Parameters:**

| Flag | Long Form | Default | Purpose |
|------|-----------|---------|---------|
| `-n` | `--n_iterations` | `2` | Number of evaluation runs |
| `-m` | `--model` | `gpt-4o-mini` | Evaluator model (OpenAI only for now) |

### Reading the Score Table

After all iterations complete, you get a performance summary:

```
                      Tasks Scores (1-10 Higher is better)

| Tasks/Crew/Agents  | Run 1 | Run 2 | Avg. Total |          Agents          |
| :----------------- | :---: | :---: | :--------: | :----------------------: |
| Task 1             |  9.0  |  9.5  |   9.2      | Professional Researcher  |
| Task 2             |  9.0  | 10.0  |   9.5      | Profile Investigator     |
| Task 3             |  9.0  |  9.0  |   9.0      | Automation Specialist    |
| Task 4             |  9.0  |  9.0  |   9.0      | Final Report Compiler    |
| Crew               |  9.00 |  9.38 |   9.2      |                          |
| Execution Time (s) |  126  |  145  |   135      |                          |
```

**How to interpret:**
- Each task receives an independent 1-10 score per run
- The Crew row shows the average across all tasks for that run
- Execution Time tracks wall-clock seconds to detect performance regressions
- Scores below 7.0 on any task warrant investigation

### Debugging Individual Tasks

When a task scores poorly, drill into its output:

```bash
# View stored outputs from the last run
crewai log-tasks-outputs

# Replay a specific task by its ID (from the log output)
crewai replay -t <task_id>
```

`log-tasks-outputs` shows the full output each task produced. `replay` re-executes a single
task in isolation so you can iterate on its agent's configuration without rerunning the entire
crew.

### Testing Workflow

1. **Baseline**: Run `crewai test -n 3` to establish baseline scores
2. **Identify**: Find the lowest-scoring task
3. **Inspect**: Use `crewai log-tasks-outputs` to see what the agent actually produced
4. **Iterate**: Adjust the agent's role/goal/backstory or the task's description/expected_output
5. **Replay**: Run `crewai replay -t <task_id>` to test the single task
6. **Validate**: Run `crewai test -n 3` again to confirm improvement
7. **Compare**: Check that improving one task did not degrade others

---

## 2. Event Listener System

CrewAI emits events at every significant point during execution. You can hook into these events
to build logging, analytics, debugging, or integration layers without modifying core crew logic.

### Architecture

```
CrewAI Runtime
    |
    v
CrewAIEventsBus (singleton)
    |
    +---> MyLoggingListener.on(CrewKickoffStartedEvent)
    +---> MyAnalyticsListener.on(TaskCompletedEvent)
    +---> MySlackListener.on(CrewKickoffFailedEvent)
```

The `CrewAIEventsBus` is a process-wide singleton. When any CrewAI component (Crew, Agent,
Task, Tool, LLM) performs an action, it emits a typed event through the bus. Your listeners
receive these events with two arguments: `source` (the emitting object) and `event` (the
typed event instance).

### Creating a Custom Listener

```python
from crewai.events import (
    BaseEventListener,
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    CrewKickoffFailedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    ToolUsageErrorEvent,
    LLMCallCompletedEvent,
)

class ObservabilityListener(BaseEventListener):
    """Logs crew execution lifecycle for monitoring dashboards."""

    def __init__(self):
        super().__init__()

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def on_crew_started(source, event):
            print(f"[CREW START] {event.crew_name} at {event.timestamp}")

        @crewai_event_bus.on(CrewKickoffCompletedEvent)
        def on_crew_completed(source, event):
            print(f"[CREW DONE] {event.crew_name} output={event.output}")

        @crewai_event_bus.on(CrewKickoffFailedEvent)
        def on_crew_failed(source, event):
            print(f"[CREW FAIL] {event.crew_name} error={event.error}")

        @crewai_event_bus.on(TaskCompletedEvent)
        def on_task_completed(source, event):
            print(f"[TASK DONE] {event.task.description[:60]}")

        @crewai_event_bus.on(ToolUsageErrorEvent)
        def on_tool_error(source, event):
            print(f"[TOOL ERR] {event.tool_name}: {event.error}")

        @crewai_event_bus.on(LLMCallCompletedEvent)
        def on_llm_done(source, event):
            print(f"[LLM] tokens={event.token_usage} model={event.model}")
```

### Registering Listeners

Defining the class is not enough -- you must instantiate it and ensure the instance stays alive
(not garbage collected) for the duration of execution.

**Option A: Import in your crew file (simplest)**

```python
# crew.py
from crewai import Agent, Crew, Task
from my_listeners import ObservabilityListener

# Instantiate at module level -- handlers register on import
obs_listener = ObservabilityListener()

class MyCrew:
    def crew(self):
        return Crew(agents=[...], tasks=[...])
```

**Option B: Listener package (for multiple listeners)**

```
my_project/
  listeners/
    __init__.py              # imports instances from each module
    observability.py         # ObservabilityListener + instance
    analytics.py             # AnalyticsListener + instance
```

```python
# listeners/observability.py
from crewai.events import BaseEventListener, CrewKickoffStartedEvent

class ObservabilityListener(BaseEventListener):
    def __init__(self):
        super().__init__()

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def on_start(source, event):
            print(f"Crew {event.crew_name} started")

# Create the instance so handlers register
observability_listener = ObservabilityListener()
```

```python
# listeners/__init__.py
from .observability import observability_listener
from .analytics import analytics_listener

__all__ = ["observability_listener", "analytics_listener"]
```

```python
# crew.py -- single import activates all listeners
import my_project.listeners
```

### Available Event Types

Events are organized by the component that emits them. See `references/event-types.md` for
the complete list with properties. Here is the category summary:

| Category | Events | Key Use Cases |
|----------|--------|---------------|
| **Crew** | KickoffStarted/Completed/Failed, TestStarted/Completed/Failed, TrainStarted/Completed/Failed | Lifecycle tracking, alerting on failures |
| **Agent** | ExecutionStarted/Completed/Error | Per-agent performance, error rates |
| **Task** | Started/Completed/Failed, Evaluation | Task-level scoring, SLA monitoring |
| **Tool** | UsageStarted/Finished/Error, ValidateInputError, ExecutionError, SelectionError | Tool reliability, debugging bad inputs |
| **Knowledge** | RetrievalStarted/Completed, QueryStarted/Completed/Failed, SearchQueryFailed | RAG pipeline monitoring |
| **Flow** | Created/Started/Finished, MethodExecutionStarted/Finished/Failed, Plot | Flow orchestration tracing |
| **LLM** | CallStarted/Completed/Failed, StreamChunk | Token usage, latency, cost tracking |
| **Memory** | QueryStarted/Completed/Failed, SaveStarted/Completed/Failed, RetrievalStarted/Completed | Memory subsystem health |
| **LLMGuardrail** | Started/Completed | Guardrail validation tracking |

### Scoped Handlers for Testing

When you need temporary event handling (inside tests, one-off debugging), use the
`scoped_handlers` context manager. Handlers registered inside the scope are automatically
removed when the context exits:

```python
from crewai.events import crewai_event_bus, CrewKickoffStartedEvent

captured_events = []

with crewai_event_bus.scoped_handlers():
    @crewai_event_bus.on(CrewKickoffStartedEvent)
    def capture(source, event):
        captured_events.append(event)

    crew.kickoff()

# Outside the scope: capture handler is removed
assert len(captured_events) == 1
```

### Practical Use Cases

**Structured JSON logging:**
```python
import json, datetime
from crewai.events import BaseEventListener, TaskCompletedEvent, LLMCallCompletedEvent

class JSONLogger(BaseEventListener):
    def __init__(self, log_file="crew_events.jsonl"):
        super().__init__()
        self.log_file = log_file

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(TaskCompletedEvent)
        def log_task(source, event):
            self._write({"type": "task_completed", "task": event.task.description})

        @crewai_event_bus.on(LLMCallCompletedEvent)
        def log_llm(source, event):
            self._write({"type": "llm_call", "model": event.model, "tokens": event.token_usage})

    def _write(self, record):
        record["ts"] = datetime.datetime.utcnow().isoformat()
        with open(self.log_file, "a") as f:
            f.write(json.dumps(record) + "\n")

json_logger = JSONLogger()
```

**Slack alerting on crew failure:**
```python
import requests
from crewai.events import BaseEventListener, CrewKickoffFailedEvent

class SlackAlertListener(BaseEventListener):
    def __init__(self, webhook_url):
        super().__init__()
        self.webhook_url = webhook_url

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(CrewKickoffFailedEvent)
        def alert(source, event):
            requests.post(self.webhook_url, json={
                "text": f"CrewAI FAILURE: {event.crew_name} - {event.error}"
            })

slack_alerts = SlackAlertListener(webhook_url="https://hooks.slack.com/...")
```

**Token cost tracker:**
```python
from crewai.events import BaseEventListener, LLMCallCompletedEvent

class CostTracker(BaseEventListener):
    COST_PER_1K = {"gpt-4o": 0.005, "gpt-4o-mini": 0.00015, "claude-sonnet-4-20250514": 0.003}

    def __init__(self):
        super().__init__()
        self.total_tokens = 0
        self.total_cost = 0.0

    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(LLMCallCompletedEvent)
        def track(source, event):
            self.total_tokens += event.token_usage
            rate = self.COST_PER_1K.get(event.model, 0.001)
            self.total_cost += (event.token_usage / 1000) * rate

    def report(self):
        return f"Tokens: {self.total_tokens}, Est. Cost: ${self.total_cost:.4f}"

cost_tracker = CostTracker()
```

---

## 3. Fingerprinting

Every Agent, Crew, and Task in CrewAI automatically receives a UUID-based fingerprint at
creation time. Fingerprints provide a stable identity for components across their lifecycle,
enabling auditing, tracking, and correlation of events back to specific components.

### How Fingerprints Work

A fingerprint is an instance of `crewai.security.Fingerprint` containing:

| Property | Type | Mutable | Description |
|----------|------|---------|-------------|
| `uuid_str` | `str` | No | Auto-generated UUID v4 |
| `created_at` | `datetime` | No | Timestamp of creation |
| `metadata` | `dict` | Yes | User-defined key-value pairs |

Fingerprints are auto-generated. You cannot manually set the UUID or timestamp, which
guarantees identity integrity.

### Accessing Fingerprints

```python
from crewai import Agent, Crew, Task

agent = Agent(role="Analyst", goal="Analyze data", backstory="Expert analyst")
task = Task(description="Run analysis", expected_output="Report", agent=agent)
crew = Crew(agents=[agent], tasks=[task])

# Each component exposes a read-only .fingerprint property
print(agent.fingerprint.uuid_str)    # "a1b2c3d4-..."
print(task.fingerprint.uuid_str)     # "e5f6g7h8-..."
print(crew.fingerprint.uuid_str)     # "i9j0k1l2-..."
print(agent.fingerprint.created_at)  # datetime object
```

### Attaching Metadata

Metadata lets you tag components with project context, versioning, or organizational info:

```python
agent.security_config.fingerprint.metadata = {
    "version": "2.1",
    "team": "data-science",
    "environment": "staging",
}

# Read it back through the public property
print(agent.fingerprint.metadata)
# {"version": "2.1", "team": "data-science", "environment": "staging"}
```

### Persistence Across Modifications

Fingerprints survive component changes. If you modify an agent's goal, role, or any other
attribute, the fingerprint remains the same:

```python
original_id = agent.fingerprint.uuid_str
agent.goal = "Completely different goal"
assert agent.fingerprint.uuid_str == original_id  # passes
```

This makes fingerprints reliable for audit logs and event correlation, even as you iterate
on agent configurations during development.

### Deterministic Fingerprints with Seeds

For reproducible environments (testing, CI/CD, migrations), you can generate deterministic
fingerprints from a seed string. The same seed always produces the same UUID:

```python
from crewai.security import Fingerprint

fp1 = Fingerprint.generate(seed="my-data-analyst-v2")
fp2 = Fingerprint.generate(seed="my-data-analyst-v2")
assert fp1.uuid_str == fp2.uuid_str  # always true

# Combine with metadata
fp = Fingerprint.generate(
    seed="production-crew-alpha",
    metadata={"release": "2025.03", "region": "us-east-1"}
)
```

### Use Cases

- **Audit trails**: Log fingerprint UUIDs alongside event data to trace which specific
  agent/task/crew produced each output
- **A/B testing**: Compare performance metrics between two agent configurations by their
  fingerprints
- **Event correlation**: Join event listener data with fingerprint metadata for rich
  dashboards
- **Migration tracking**: Use deterministic seeds to maintain stable IDs across deployments

---

## 4. Prompt Customization

CrewAI automatically injects default instructions into every agent's prompt. Understanding
and controlling these injections is essential for production systems that need full prompt
transparency and model-specific optimization.

### What CrewAI Injects by Default

When you define an agent with `role`, `goal`, and `backstory`, CrewAI wraps those values in
additional formatting instructions depending on the agent's configuration:

**Agents without tools:**
```
"I MUST use these formats, my job depends on it!"
```

**Agents with tools:**
```
"IMPORTANT: Use the following format in your response:

Thought: you should always think about what to do
Action: the action to take, only one name of [tool_names]
Action Input: the input to the action, just a simple JSON object..."
```

**Agents with structured output (JSON/Pydantic):**
```
"Ensure your final answer contains only the content in the following format: {output_format}
Ensure the final output does not include any code block markers like ```json or ```python."
```

These defaults work well in many cases, but they can conflict with domain-specific
requirements or model-specific prompt formats.

### Viewing the Complete System Prompt

Before customizing, inspect exactly what CrewAI sends to the LLM:

```python
from crewai import Agent, Task
from crewai.utilities.prompts import Prompts

agent = Agent(
    role="Data Analyst",
    goal="Analyze data and provide insights",
    backstory="Expert data analyst with 10 years of experience.",
    verbose=True,
)

prompt_gen = Prompts(
    agent=agent,
    has_tools=len(agent.tools) > 0,
    use_system_prompt=agent.use_system_prompt,
)

generated = prompt_gen.task_execution()

if "system" in generated:
    print("=== SYSTEM ===")
    print(generated["system"])
    print("=== USER ===")
    print(generated["user"])
else:
    print("=== PROMPT ===")
    print(generated["prompt"])
```

Always run this inspection before deploying to production so you know exactly what the model
receives.

### Custom Templates (Recommended Approach)

Override the system, prompt, and response templates directly on the Agent:

```python
from crewai import Agent

custom_system = """You are {role}. {backstory}
Your goal is: {goal}

Respond naturally and conversationally. Provide helpful, accurate information."""

custom_prompt = """Task: {input}

Complete this task thoughtfully."""

agent = Agent(
    role="Research Assistant",
    goal="Find accurate information",
    backstory="Helpful research assistant.",
    system_template=custom_system,
    prompt_template=custom_prompt,
    use_system_prompt=True,
)
```

Available template variables: `{role}`, `{goal}`, `{backstory}`, `{input}`, `{tools}`,
`{tool_names}`, `{output_format}`.

### Custom Prompt JSON Files

For team-wide prompt overrides, create a JSON file and pass it to the Crew via `prompt_file`.
CrewAI merges your overrides with its defaults, so you only need to specify the slices you
want to change:

```json
{
  "slices": {
    "no_tools": "\nProvide your best answer naturally.",
    "tools": "\nYou have these tools: {tools}\n\nUse them when helpful.",
    "formatted_task_instructions": "Format your response as: {output_format}",
    "format": "THOUGHTS: Your reasoning\nACTION: Tool to use\nRESULT: Final answer"
  }
}
```

```python
crew = Crew(
    agents=[agent],
    tasks=[task],
    prompt_file="prompts/custom_prompts.json",
    verbose=True,
)
```

See the [default prompt slices](https://github.com/crewAIInc/crewAI/blob/main/src/crewai/translations/en.json)
for the complete list of overridable keys.

### Model-Specific Optimization

Different LLMs perform better with prompts formatted for their architecture. Here is an
example optimizing for Meta Llama 3.3:

```python
from crewai import Agent, Crew, Task, Process

# Llama 3.x uses special header tokens
system_template = (
    "<|begin_of_text|><|start_header_id|>system<|end_header_id|>"
    "{{ .System }}<|eot_id|>"
)
prompt_template = (
    "<|start_header_id|>user<|end_header_id|>"
    "{{ .Prompt }}<|eot_id|>"
)
response_template = (
    "<|start_header_id|>assistant<|end_header_id|>"
    "{{ .Response }}<|eot_id|>"
)

agent = Agent(
    role="Principal Engineer",
    goal="Review AI architecture",
    backstory="Lead engineer for critical AI systems",
    llm="groq/llama-3.3-70b-versatile",
    system_template=system_template,
    prompt_template=prompt_template,
    response_template=response_template,
    tools=[],
)
```

### Disabling System Prompts (for o1 Models)

OpenAI's o1 models do not support system messages. Disable system prompt separation so
everything goes into the user message:

```python
agent = Agent(
    role="Analyst",
    goal="Analyze data",
    backstory="Expert analyst",
    use_system_prompt=False,  # Everything in user message
)
```

### Prompt Management Best Practices

1. **Inspect before deploying** -- always view the generated prompt to know what the LLM sees
2. **Override minimally** -- only change the slices you need; keep defaults for the rest
3. **Version control prompt files** -- treat `custom_prompts.json` as code
4. **Organize by model** -- use names like `prompts_llama.json`, `prompts_claude.json`
5. **Document intent** -- comment why each override exists, not just what it does

---

## 5. Multimodal File Handling

CrewAI natively supports passing images, PDFs, audio, video, and text files to agents. Files
are automatically formatted for each LLM provider's API.

### Installation

File support requires an optional package:

```bash
uv add 'crewai[file-processing]'
```

### File Types

| Type | Class | Typical Sources |
|------|-------|-----------------|
| Image | `ImageFile` | Screenshots, charts, diagrams |
| PDF | `PDFFile` | Reports, papers, invoices |
| Audio | `AudioFile` | Recordings, podcasts, meetings |
| Video | `VideoFile` | Screen recordings, presentations |
| Text | `TextFile` | Code files, logs, CSV data |
| Generic | `File` | Auto-detect type from content |

```python
from crewai_files import File, ImageFile, PDFFile, AudioFile, VideoFile, TextFile

image = ImageFile(source="screenshot.png")          # local path
pdf   = PDFFile(source="https://example.com/r.pdf") # URL
audio = AudioFile(source=audio_bytes)                # raw bytes
```

### Sources

The `source` parameter auto-detects the input type:

| Source Type | Example | Behavior |
|-------------|---------|----------|
| Local path | `"./charts/q4.png"` | Reads from filesystem |
| URL | `"https://cdn.example.com/img.png"` | Fetched or passed as reference |
| Bytes | `FileBytes(data=raw, filename="img.png")` | Embedded directly |

### Passing Files to CrewAI Components

**With Crews** -- files available to all tasks in the crew:

```python
from crewai import Crew
from crewai_files import ImageFile, PDFFile

result = crew.kickoff(
    inputs={"topic": "Q4 Sales"},
    input_files={
        "chart": ImageFile(source="sales_chart.png"),
        "report": PDFFile(source="quarterly_report.pdf"),
    },
)
```

**With Tasks** -- files scoped to a specific task:

```python
from crewai import Task
from crewai_files import ImageFile

task = Task(
    description="Analyze the sales chart in {chart} and identify trends",
    expected_output="Summary of key trends",
    input_files={"chart": ImageFile(source="sales_chart.png")},
)
```

**With Flows** -- files inherited by all crews in the flow:

```python
from crewai.flow.flow import Flow, start
from crewai_files import ImageFile

class AnalysisFlow(Flow):
    @start()
    def analyze(self):
        return self.analysis_crew.kickoff()

flow = AnalysisFlow()
result = flow.kickoff(
    input_files={"image": ImageFile(source="data.png")}
)
```

**With Standalone Agents:**

```python
from crewai import Agent
from crewai_files import ImageFile

agent = Agent(role="Image Analyst", goal="Analyze images", backstory="Visual expert", llm="gpt-4o")

result = agent.kickoff(
    messages="What's in this image?",
    input_files={"photo": ImageFile(source="photo.jpg")},
)
```

### File Precedence

When files with the same key are defined at multiple levels, the most specific level wins:

```
Flow input_files  <  Crew input_files  <  Task input_files
     (lowest)          (medium)              (highest)
```

If both Flow and Task define `"chart"`, the Task's version is used for that task.

### Provider Support Matrix

| Provider | Image | PDF | Audio | Video | Text |
|----------|:-----:|:---:|:-----:|:-----:|:----:|
| OpenAI (completions) | Y | | | | |
| OpenAI (responses) | Y | Y | Y | | |
| Anthropic (claude-3.x) | Y | Y | | | |
| Google Gemini (1.5/2.0/2.5) | Y | Y | Y | Y | Y |
| AWS Bedrock (claude-3) | Y | Y | | | |
| Azure OpenAI (gpt-4o) | Y | | Y | | |

Google Gemini supports the widest range of file types including video (up to 1 hour, 2GB).
Choose your provider based on the file types you need to process. Passing an unsupported
file type raises `UnsupportedFileTypeError`.

### How Files Are Transmitted

CrewAI automatically picks the optimal transmission method:

| Method | When Used | Description |
|--------|-----------|-------------|
| Inline Base64 | Small files (< 5MB) | Embedded directly in the API request |
| File Upload API | Large files over threshold | Uploaded separately, referenced by ID |
| URL Reference | Source is already a URL | URL passed directly to the model |

Upload thresholds by provider: OpenAI > 5MB, Anthropic > 5MB, Gemini > 20MB.

### File Handling Modes

Control behavior when files exceed provider constraints:

```python
from crewai_files import ImageFile, PDFFile

# strict: raise error if constraints exceeded
image = ImageFile(source="huge.png", mode="strict")

# auto: automatically resize/compress to fit (default)
image = ImageFile(source="huge.png", mode="auto")

# warn: process anyway but log a warning
image = ImageFile(source="huge.png", mode="warn")

# chunk: split large documents into processable segments
pdf = PDFFile(source="500_page_report.pdf", mode="chunk")
```

### Provider Constraints Quick Reference

| Provider | Images | PDFs | Audio | Video |
|----------|--------|------|-------|-------|
| OpenAI | 20MB, 10/req | 32MB, 100pg | 25MB, 25min | -- |
| Anthropic | 5MB, 8000x8000, 100/req | 32MB, 100pg | -- | -- |
| Gemini | 100MB | 50MB | 100MB, 9.5hr | 2GB, 1hr |
| Bedrock | 4.5MB, 8000x8000 | 3.75MB, 100pg | -- | -- |

### Referencing Files in Task Prompts

Use the file key name in curly braces within task descriptions:

```python
task = Task(
    description="""
    Analyze the provided materials:
    1. Review the chart in {sales_chart}
    2. Cross-reference with {quarterly_report}
    3. Summarize key findings
    """,
    expected_output="Analysis summary with key insights",
    input_files={
        "sales_chart": ImageFile(source="chart.png"),
        "quarterly_report": PDFFile(source="report.pdf"),
    },
)
```

---

## 6. Best Practices

### Testing
- Run `crewai test -n 3` as part of your CI pipeline to catch regressions
- Use `crewai replay -t <task_id>` for focused iteration on individual tasks
- Establish baseline scores before making agent changes
- Test across multiple evaluator models to avoid evaluator bias

### Event Listeners
- Keep handlers lightweight -- offload heavy work (DB writes, API calls) to background queues
- Always include try/except in handlers to prevent listener errors from crashing the crew
- Use `scoped_handlers` in tests to avoid global state pollution
- Only subscribe to events you actually use; unnecessary handlers add overhead

### Fingerprinting
- Never hardcode fingerprint UUIDs; always access them through the `.fingerprint` property
- Use deterministic seeds in CI/CD for reproducible component tracking
- Attach environment metadata (staging vs production) to fingerprints for multi-env tracking

### Prompt Customization
- Inspect generated prompts before every production deployment
- Override only the minimum number of slices needed
- Version-control all prompt files alongside your crew code
- Test prompt changes with `crewai test` to measure impact on scores

### File Handling
- Check the provider support matrix before selecting an LLM for multimodal tasks
- Use `mode="auto"` in development and `mode="strict"` in production
- Keep file sizes within provider limits to avoid silent truncation or errors
- Reference files by key in task descriptions (`{key}`) rather than hardcoding paths

---

## Resources

- **references/event-types.md**: Complete event type reference with properties
- [CrewAI default prompt templates (GitHub)](https://github.com/crewAIInc/crewAI/blob/main/src/crewai/translations/en.json)
- [CrewAI documentation](https://docs.crewai.com)
