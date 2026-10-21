---
name: crewai-crew-orchestration
description: >
  Build and orchestrate production-ready CrewAI multi-agent systems. Covers crew composition
  with @CrewBase decorators and YAML config, task design with context chaining and guardrails,
  sequential and hierarchical processes, Flow-based production orchestration with @start/@listen/@router
  decorators, Pydantic state management, planning with AgentPlanner, kickoff methods (sync, async,
  streaming, for_each), structured outputs, and deployment patterns with @persist.
triggers:
  - "crewai crew"
  - "crewai task"
  - "crewai flow"
  - "crew orchestration"
  - "multi-agent system"
  - "sequential process"
  - "hierarchical process"
  - "crewai production"
  - "crewai state management"
  - "crewai guardrails"
  - "crewai kickoff"
  - "crewai planning"
  - "task context chaining"
  - "crewai structured output"
  - "crewai @persist"
  - "crewai router"
  - "flow-based orchestration"
version: "1.0.0"
author:
  name: "Arisela"
tags: [crewai, crews, tasks, flows, orchestration, multi-agent, production, sequential, hierarchical, state-management]
category: learning
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
---

# CrewAI Crew Orchestration

You are an expert at building production-ready CrewAI multi-agent systems. You understand crew composition, task design, process selection, Flow-based orchestration, state management, planning, and deployment patterns. When a user asks about CrewAI orchestration, you follow a structured decision workflow and apply the right pattern for their use case.

## Decision Workflow

When a user asks for help with CrewAI orchestration, follow this workflow:

1. **Classify the request**: Is the user building a new crew, adding tasks to an existing crew, designing a production flow, choosing a process type, debugging execution, or optimizing performance?
2. **Gather context**: What agents do they have? What is the desired output? Is this a simple pipeline or a multi-crew production system?
3. **Recommend the right pattern**:
   - Single crew with 2-3 agents doing sequential work --> Sequential process with context chaining
   - Dynamic task assignment with manager oversight --> Hierarchical process
   - Multi-crew production system with state --> Flow-based orchestration
   - Batch processing over a list of inputs --> `kickoff_for_each()` or `akickoff_for_each()`
   - Need conditional branching or routing --> Flow with `@router` decorator
4. **Provide implementation**: Give concrete code with YAML config (recommended) or direct Python, following the patterns in this skill.

---

## 1. Crew Composition

A Crew is a collaborative group of agents working together on a set of tasks. There are two ways to define crews.

### YAML Configuration (Recommended)

YAML config separates agent/task definitions from Python logic. The `@CrewBase` class decorators auto-collect agents and tasks.

```python
from crewai import Agent, Crew, Task, Process
from crewai.project import CrewBase, agent, task, crew, before_kickoff, after_kickoff
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

@CrewBase
class ResearchCrew:
    """Research and reporting crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Paths to YAML config files
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @before_kickoff
    def prepare_inputs(self, inputs):
        # Modify inputs before the crew starts
        inputs['date'] = "2025-01-15"
        return inputs

    @after_kickoff
    def process_output(self, output):
        # Post-process the crew output
        return output

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'],
            verbose=True,
            tools=[SearchTool()]
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config['writer'],
            verbose=True
        )

    @task
    def research_task(self) -> Task:
        return Task(config=self.tasks_config['research_task'])

    @task
    def writing_task(self) -> Task:
        return Task(
            config=self.tasks_config['writing_task'],
            context=[self.research_task()]  # Chain task outputs
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,   # Auto-collected by @agent decorator
            tasks=self.tasks,     # Auto-collected by @task decorator
            process=Process.sequential,
            verbose=True,
        )

# Run it
ResearchCrew().crew().kickoff(inputs={"topic": "AI Agents"})
```

**Decorator reference:**
| Decorator | Purpose |
|-----------|---------|
| `@CrewBase` | Marks the class as a crew base, enables auto-collection |
| `@agent` | Registers a method that returns an Agent |
| `@task` | Registers a method that returns a Task |
| `@crew` | Marks the method that assembles and returns the Crew |
| `@before_kickoff` | Hook that runs before crew execution; can modify inputs |
| `@after_kickoff` | Hook that runs after crew execution; can modify output |

**Important**: YAML method names must match the keys in your `agents.yaml` and `tasks.yaml` files.

### Direct Code Definition

For smaller projects or prototyping, define everything inline:

```python
from crewai import Agent, Crew, Task, Process

researcher = Agent(
    role="Data Analyst",
    goal="Analyze data trends in the market",
    backstory="An experienced data analyst with a background in economics",
    verbose=True,
    tools=[SearchTool()]
)

writer = Agent(
    role="Report Writer",
    goal="Create clear, actionable reports",
    backstory="A technical writer who excels at translating data into insights",
    verbose=True
)

research_task = Task(
    description="Research the latest developments in {topic}",
    expected_output="A list of 10 key findings about {topic}",
    agent=researcher
)

writing_task = Task(
    description="Write a report based on the research findings",
    expected_output="A well-structured report in markdown format",
    agent=writer,
    context=[research_task]  # Gets research_task output as context
)

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, writing_task],
    process=Process.sequential,
    verbose=True
)

result = crew.kickoff(inputs={"topic": "AI Agents"})
```

### Key Crew Attributes

| Attribute | Parameter | Description |
|-----------|-----------|-------------|
| Tasks | `tasks` | List of tasks assigned to the crew |
| Agents | `agents` | List of agents in the crew |
| Process | `process` | `Process.sequential` (default) or `Process.hierarchical` |
| Memory | `memory` | Enable short-term, long-term, entity memory |
| Cache | `cache` | Cache tool execution results (default: True) |
| Planning | `planning` | Enable AgentPlanner for step-by-step task planning |
| Planning LLM | `planning_llm` | LLM used by the AgentPlanner |
| Manager LLM | `manager_llm` | Required for hierarchical process |
| Manager Agent | `manager_agent` | Custom manager agent for hierarchical process |
| Max RPM | `max_rpm` | Rate limit (overrides agent-level settings) |
| Verbose | `verbose` | Enable detailed logging |
| Stream | `stream` | Enable streaming output |
| Embedder | `embedder` | Config for memory embedder (default: `{"provider": "openai"}`) |
| Step Callback | `step_callback` | Called after each agent step |
| Task Callback | `task_callback` | Called after each task completion |
| Output Log File | `output_log_file` | Save execution logs (`True` for logs.txt, or a filename) |
| Knowledge Sources | `knowledge_sources` | Crew-level knowledge accessible to all agents |

---

## 2. Task Design

Tasks are the units of work agents execute. Good task design is the most important factor in crew performance.

### Writing Effective Tasks

The two required fields are `description` and `expected_output`. They must be specific and detailed:

```yaml
# config/tasks.yaml
research_task:
  description: >
    Conduct thorough research about {topic}.
    Find the 10 most significant recent developments,
    focusing on practical applications and impact.
    Current year is 2025.
  expected_output: >
    A numbered list of 10 findings, each with:
    - A one-sentence summary
    - Why it matters
    - Source reference
  agent: researcher

analysis_task:
  description: >
    Analyze the research findings and identify the top 3 trends.
    For each trend, assess market impact, timeline, and confidence level.
  expected_output: >
    A structured analysis with 3 trends, each containing:
    market_impact (high/medium/low), timeline (months), confidence (0-100%)
  agent: analyst
  context:
    - research_task
```

### Context Chaining

Use `context` to pass one task's output as input to another. This is how you build pipelines:

```python
task_a = Task(description="Gather data...", expected_output="Raw data...", agent=gatherer)
task_b = Task(description="Analyze...", expected_output="Analysis...", agent=analyst, context=[task_a])
task_c = Task(description="Report on...", expected_output="Report...", agent=writer, context=[task_a, task_b])
```

In sequential mode, tasks without explicit `context` automatically receive the previous task's output. Use explicit `context` to pull from non-adjacent tasks.

### Structured Output

Always use structured outputs when passing data between tasks or to your application:

```python
from pydantic import BaseModel
from typing import List

class ResearchResult(BaseModel):
    summary: str
    sources: List[str]
    confidence: float

task = Task(
    description="Research the topic...",
    expected_output="Structured research findings",
    agent=researcher,
    output_pydantic=ResearchResult  # Forces structured output
)
```

You can also use `output_json=ResearchResult` to get a JSON dict instead of a Pydantic object.

### Task Guardrails

Guardrails validate task output before it is accepted. They catch bad outputs early and give the agent feedback to retry.

**Function-based guardrail** (deterministic validation):

```python
from typing import Tuple, Any
from crewai import TaskOutput

def validate_report(result: TaskOutput) -> Tuple[bool, Any]:
    """Validate the report meets quality standards."""
    word_count = len(result.raw.split())
    if word_count < 100:
        return (False, f"Report too short ({word_count} words). Expand to at least 100 words.")
    if "PLACEHOLDER" in result.raw:
        return (False, "Report contains placeholder text. Replace all placeholders.")
    return (True, result.raw)

task = Task(
    description="Write a detailed report...",
    expected_output="A comprehensive report...",
    agent=writer,
    guardrail=validate_report,
    guardrail_max_retries=3
)
```

**LLM-based guardrail** (subjective validation via string):

```python
task = Task(
    description="Write a blog post about AI",
    expected_output="An engaging blog post",
    agent=writer,
    guardrail="The post must be professional in tone, free of jargon, and under 500 words"
)
```

**Multiple guardrails** (executed sequentially, can mix types):

```python
task = Task(
    description="Write content...",
    expected_output="Quality content...",
    agent=writer,
    guardrails=[
        validate_word_count,        # Function: check length
        validate_no_profanity,      # Function: check content
        "Must be engaging and suitable for a general audience",  # LLM: subjective check
    ],
    guardrail_max_retries=3
)
```

### Async and Conditional Tasks

```python
# Async execution -- runs in parallel with next task
async_task = Task(
    description="Long-running research...",
    expected_output="Research results",
    agent=researcher,
    async_execution=True
)

# Output to file
file_task = Task(
    description="Generate the final report...",
    expected_output="Markdown report",
    agent=writer,
    output_file="output/report.md",
    markdown=True  # Instructs agent to use markdown formatting
)
```

### Key Task Attributes

See `references/task-attributes.md` for the complete attribute reference.

---

## 3. Processes

Processes define how tasks are distributed and executed across agents.

### Sequential Process (Default)

Tasks execute in order. Each task's output becomes context for the next. Use when you have a clear pipeline.

```python
crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, analysis_task, writing_task],
    process=Process.sequential  # This is the default
)
```

**When to use**: Research-then-write pipelines, data transformation chains, any workflow where each step depends on the previous one.

### Hierarchical Process

A manager agent coordinates the crew. Tasks are not pre-assigned; the manager delegates based on agent capabilities, reviews outputs, and validates completion.

```python
# Option A: Auto-created manager with specified LLM
crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, analysis_task, writing_task],
    process=Process.hierarchical,
    manager_llm="gpt-4o"  # Required for hierarchical
)

# Option B: Custom manager agent
manager = Agent(
    role="Project Manager",
    goal="Coordinate the team to deliver high-quality output",
    backstory="Experienced PM who ensures quality and deadlines"
)

crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, analysis_task, writing_task],
    process=Process.hierarchical,
    manager_agent=manager  # Use instead of manager_llm
)
```

**When to use**: Complex projects where task assignment benefits from reasoning, when agents have overlapping capabilities, when you want automatic delegation and quality review.

### Choosing Between Processes

| Factor | Sequential | Hierarchical |
|--------|-----------|-------------|
| Task order | Fixed, predictable | Dynamic, manager decides |
| Agent assignment | Pre-assigned per task | Manager delegates |
| Overhead | Lower (no manager) | Higher (manager LLM calls) |
| Quality control | Manual (guardrails) | Built-in (manager reviews) |
| Best for | Simple pipelines | Complex, multi-skill projects |
| Required config | None extra | `manager_llm` or `manager_agent` |

---

## 4. Flows (Production Orchestration)

Flows are the recommended architecture for production CrewAI applications. They provide structured, event-driven orchestration with state management, conditional routing, and persistence.

### Why Flows?

- **State management**: Pydantic-based state persisted across steps
- **Control**: Precise execution paths with conditionals, loops, branching
- **Observability**: Clear structure for tracing, debugging, monitoring
- **Composability**: Combine crews, direct LLM calls, and regular code in one system

### Basic Flow Structure

```python
from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

class PipelineState(BaseModel):
    topic: str = ""
    research: str = ""
    report: str = ""

class ContentPipeline(Flow[PipelineState]):

    @start()
    def gather_input(self):
        self.state.topic = "AI Safety"
        return self.state.topic

    @listen(gather_input)
    def run_research(self, topic):
        crew = ResearchCrew()
        result = crew.crew().kickoff(inputs={"topic": topic})
        self.state.research = result.raw
        return result.raw

    @listen(run_research)
    def write_report(self, research):
        crew = WritingCrew()
        result = crew.crew().kickoff(inputs={
            "topic": self.state.topic,
            "research": research
        })
        self.state.report = result.raw
        return result.raw

# Execute
flow = ContentPipeline()
result = flow.kickoff()
```

### Flow Decorators

| Decorator | Purpose | Signature |
|-----------|---------|-----------|
| `@start()` | Marks the entry point of the flow | `def method(self)` |
| `@listen(method)` | Runs when the specified method completes | `def method(self, previous_result)` |
| `@router(method)` | Routes to different listeners based on return value | Returns a string label |

### Conditional Routing with @router

```python
from crewai.flow.flow import Flow, start, listen, router
from pydantic import BaseModel

class ReviewState(BaseModel):
    content: str = ""
    quality_score: float = 0.0
    revision_count: int = 0

class ReviewFlow(Flow[ReviewState]):

    @start()
    def generate_content(self):
        crew = WritingCrew()
        result = crew.crew().kickoff(inputs={"topic": "AI"})
        self.state.content = result.raw
        return result.raw

    @router(generate_content)
    def evaluate_quality(self, content):
        # Score the content (could use an LLM call here)
        self.state.quality_score = score_content(content)
        if self.state.quality_score >= 0.8:
            return "approved"
        elif self.state.revision_count < 3:
            return "revise"
        else:
            return "escalate"

    @listen("approved")
    def publish(self):
        return f"Published: {self.state.content[:50]}..."

    @listen("revise")
    def revise_content(self):
        self.state.revision_count += 1
        # Re-run writing crew with feedback
        crew = WritingCrew()
        result = crew.crew().kickoff(inputs={
            "topic": "AI",
            "feedback": f"Score was {self.state.quality_score}. Improve quality."
        })
        self.state.content = result.raw
        return result.raw

    @listen("escalate")
    def escalate_to_human(self):
        return "Content needs human review"
```

### State Management

Use Pydantic models for type-safe state that persists across flow steps:

```python
from pydantic import BaseModel
from typing import List, Dict, Optional

class AppState(BaseModel):
    user_input: str = ""
    research_results: str = ""
    sections: Dict[str, str] = {}
    final_output: str = ""
    error_count: int = 0

class MyFlow(Flow[AppState]):
    @start()
    def begin(self):
        self.state.user_input = "Build an AI agent"
        # State is automatically available in all subsequent steps

    @listen(begin)
    def process(self, _):
        # Access state with type safety and IDE autocompletion
        topic = self.state.user_input
        self.state.research_results = do_research(topic)
```

**Unstructured state** (dictionary-based) is also supported for prototyping:

```python
class SimpleFlow(Flow):  # No type parameter
    @start()
    def begin(self):
        self.state["topic"] = "AI"  # Dictionary-style access
```

### Parallel Execution and Composition

Use `and_` to wait for multiple methods, `or_` to proceed when any completes:

```python
from crewai.flow.flow import Flow, start, listen, and_, or_

class ParallelFlow(Flow[AppState]):
    @start()
    def begin(self):
        return "start"

    @listen(begin)
    def research_track(self, _):
        return "research done"

    @listen(begin)
    def analysis_track(self, _):
        return "analysis done"

    @listen(and_(research_track, analysis_track))
    def combine_results(self, _):
        # Runs only after BOTH tracks complete
        return "combined"

    @listen(or_(research_track, analysis_track))
    def early_notification(self, _):
        # Runs as soon as EITHER track completes
        return "first result available"
```

### Persistence with @persist

Save flow state to survive crashes or support human-in-the-loop:

```python
from crewai.flow.flow import Flow, start, listen
from crewai.flow.persistence import persist
from pydantic import BaseModel

class OrderState(BaseModel):
    order_id: str = ""
    status: str = "pending"

@persist()  # Saves state after every method
class OrderFlow(Flow[OrderState]):
    @start()
    def create_order(self):
        self.state.order_id = "ORD-001"
        self.state.status = "created"

    @listen(create_order)
    def process_order(self, _):
        self.state.status = "processing"
        # If this crashes, state is already saved from create_order
```

Method-level `@persist()` is also supported for granular control.

---

## 5. Planning

Enable automatic task planning before crew execution. An AgentPlanner creates step-by-step plans that are injected into each task's description.

```python
# Basic planning (uses gpt-4o-mini by default)
crew = Crew(
    agents=my_agents,
    tasks=my_tasks,
    process=Process.sequential,
    planning=True
)

# Custom planning LLM
crew = Crew(
    agents=my_agents,
    tasks=my_tasks,
    process=Process.sequential,
    planning=True,
    planning_llm="gpt-4o"  # Or any supported model
)
```

**How it works**: Before each iteration, all crew info (agents, tasks, goals) is sent to the AgentPlanner. The planner generates a step-by-step execution plan that gets prepended to each task description, giving agents clearer guidance.

**Warning**: Planning defaults to `gpt-4o-mini`, which requires an OpenAI API key even if your agents use a different provider. Set `planning_llm` explicitly to avoid confusion.

---

## 6. Kickoff Methods

### Synchronous

```python
# Standard kickoff
result = crew.kickoff(inputs={"topic": "AI"})

# Batch processing -- runs sequentially for each input
inputs = [{"topic": "AI"}, {"topic": "ML"}, {"topic": "Robotics"}]
results = crew.kickoff_for_each(inputs=inputs)
```

### Asynchronous

```python
# Native async (recommended for high concurrency)
result = await crew.akickoff(inputs={"topic": "AI"})
results = await crew.akickoff_for_each(inputs=inputs)

# Thread-based async (wraps sync in asyncio.to_thread)
result = await crew.kickoff_async(inputs={"topic": "AI"})
results = await crew.kickoff_for_each_async(inputs=inputs)
```

For high-concurrency workloads, prefer `akickoff()` and `akickoff_for_each()` as they use native async throughout execution, memory, and knowledge retrieval.

### Streaming

```python
crew = Crew(
    agents=[researcher],
    tasks=[task],
    stream=True
)

streaming = crew.kickoff(inputs={"topic": "AI"})
for chunk in streaming:
    print(chunk.content, end="", flush=True)

# Access final result after streaming completes
result = streaming.result
```

---

## 7. Crew Output

The `CrewOutput` class provides structured access to execution results:

```python
crew_output = crew.kickoff(inputs={"topic": "AI"})

# Access results
print(crew_output.raw)           # Raw string output
print(crew_output.pydantic)      # Pydantic model (if output_pydantic set)
print(crew_output.json_dict)     # Dict (if output_json set)
print(crew_output.tasks_output)  # List of TaskOutput objects
print(crew_output.token_usage)   # Token usage summary
```

Each `TaskOutput` in `tasks_output` contains: `description`, `summary`, `raw`, `pydantic`, `json_dict`, `agent`, `output_format`.

---

## 8. Production Architecture

### The Flow-First Mindset

For production systems, always start with a Flow. While standalone crews work for simple cases, Flows provide the structure needed for robust, scalable applications.

```
Flow Orchestrator
  |
  v
State Management (Pydantic BaseModel)
  |
  +---> Step 1: Data Gathering ---> Research Crew
  |                                      |
  +---> State Updated <-----------------+
  |
  +---> Step 2: Condition Check (Router)
  |         |             |
  |     "valid"       "invalid"
  |         |             |
  +---> Step 3 ------> End
  |   Action Crew
  |       |
  +---> End
```

### Production Best Practices

1. **Start with a Flow**: Wrap all crews in a Flow for state, control, and observability
2. **Define clear State**: Use Pydantic models; store only what you need between steps
3. **Crews as units of work**: Each crew should have a focused goal (e.g., "research", "write", "review")
4. **Pass state explicitly**: Send data from Flow state to crew inputs, not implicit globals
5. **Use task guardrails**: Validate outputs before accepting them
6. **Use structured outputs**: `output_pydantic` or `output_json` for data passed between tasks
7. **Deploy with persistence**: Use `@persist` for crash recovery and human-in-the-loop
8. **Use async for APIs**: `kickoff_async` or `akickoff` for non-blocking execution in web servers

### Control Primitives Checklist

- [ ] Task guardrails on every task that feeds another task or the final output
- [ ] Structured outputs (`output_pydantic`) for inter-task and inter-crew data
- [ ] Pydantic state model in your Flow (not unstructured dicts)
- [ ] `@persist` on production Flows for resilience
- [ ] `@router` for conditional branching instead of if/else in listener methods
- [ ] Explicit `context` on tasks that need outputs from non-adjacent tasks
- [ ] `guardrail_max_retries` set appropriately (default is 3)

---

## 9. Pattern Catalog

### Pattern A: Sequential Research-Then-Write

The simplest and most common pattern. One crew, sequential tasks.

```python
crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, writing_task],
    process=Process.sequential
)
result = crew.kickoff(inputs={"topic": "AI Safety"})
```

### Pattern B: Hierarchical Delegation

Manager assigns tasks dynamically. Good when agents have overlapping skills.

```python
crew = Crew(
    agents=[senior_dev, junior_dev, tester],
    tasks=[feature_task, test_task, review_task],
    process=Process.hierarchical,
    manager_llm="gpt-4o"
)
```

### Pattern C: Flow-Based Multi-Crew Pipeline

Multiple focused crews orchestrated by a Flow. The production pattern.

```python
class PipelineState(BaseModel):
    topic: str = ""
    research: str = ""
    draft: str = ""
    final: str = ""

class ContentPipeline(Flow[PipelineState]):
    @start()
    def begin(self):
        self.state.topic = "AI Agents"

    @listen(begin)
    def research_phase(self, _):
        result = ResearchCrew().crew().kickoff(
            inputs={"topic": self.state.topic}
        )
        self.state.research = result.raw

    @listen(research_phase)
    def writing_phase(self, _):
        result = WritingCrew().crew().kickoff(
            inputs={"topic": self.state.topic, "research": self.state.research}
        )
        self.state.draft = result.raw

    @listen(writing_phase)
    def review_phase(self, _):
        result = ReviewCrew().crew().kickoff(
            inputs={"draft": self.state.draft}
        )
        self.state.final = result.raw
```

### Pattern D: Conditional Routing with Quality Gate

Flow with a router that sends content back for revision or forward for publication.

```python
class QualityGateFlow(Flow[ContentState]):
    @start()
    def generate(self):
        # Generate initial content via crew
        ...

    @router(generate)
    def quality_check(self, content):
        score = evaluate(content)
        if score >= 0.8:
            return "publish"
        elif self.state.retries < 3:
            return "revise"
        return "fallback"

    @listen("publish")
    def publish(self):
        ...

    @listen("revise")
    def revise(self):
        self.state.retries += 1
        # Re-generate with feedback, then route back through quality_check
        ...

    @listen("fallback")
    def human_review(self):
        ...
```

### Pattern E: Batch Processing

Process a list of items through the same crew:

```python
inputs = [
    {"topic": "Machine Learning"},
    {"topic": "Natural Language Processing"},
    {"topic": "Computer Vision"}
]

# Synchronous batch
results = crew.kickoff_for_each(inputs=inputs)

# Async batch (recommended for high concurrency)
results = await crew.akickoff_for_each(inputs=inputs)
```

---

## 10. Best Practices Checklist

### Crew Design
- [ ] Each crew has a single, focused goal
- [ ] Agents have distinct, non-overlapping roles
- [ ] YAML configuration used for maintainability
- [ ] `@before_kickoff` validates and enriches inputs
- [ ] `@after_kickoff` post-processes outputs

### Task Design
- [ ] `description` is specific and actionable (not vague)
- [ ] `expected_output` describes the exact format and content
- [ ] `context` explicitly chains task dependencies
- [ ] Guardrails validate critical outputs
- [ ] Structured outputs (`output_pydantic`) used for inter-task data
- [ ] `output_file` set for tasks that produce artifacts

### Process Selection
- [ ] Sequential for predictable pipelines (most cases)
- [ ] Hierarchical only when dynamic delegation adds value
- [ ] `manager_llm` or `manager_agent` set for hierarchical

### Production Architecture
- [ ] Flow wraps all crews
- [ ] Pydantic state model defined
- [ ] `@persist` enabled for resilience
- [ ] `@router` used for conditional logic
- [ ] Crews receive data via explicit `inputs`, not shared globals
- [ ] Async kickoff used in API/web contexts
- [ ] Logging enabled (`output_log_file=True`)

### Performance
- [ ] `planning=True` enabled for complex crews
- [ ] `cache=True` (default) to avoid redundant tool calls
- [ ] `max_rpm` set to avoid rate limits
- [ ] `akickoff()` used for concurrent workloads
- [ ] Token usage monitored via `crew_output.token_usage`

## Resources

- **references/task-attributes.md**: Complete attribute reference for all Task and Crew parameters
