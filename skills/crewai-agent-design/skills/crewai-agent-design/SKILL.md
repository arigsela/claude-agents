---
name: crewai-agent-design
description: >
  Master the art of designing effective CrewAI agents. Covers the Role-Goal-Backstory
  framework, the 80/20 rule for agent vs task effort, YAML and direct code creation
  patterns, context window management, reasoning and planning modes, multimodal agents,
  specialists vs generalists, agent collaboration, and common design mistakes to avoid.
  Use when designing, reviewing, or improving CrewAI agent definitions.
triggers:
  - "crewai agent"
  - "agent design"
  - "role goal backstory"
  - "crewai agent best practices"
  - "crewai agent yaml"
  - "design a crew"
  - "agent attributes"
  - "crewai reasoning"
  - "multimodal agent"
  - "agent collaboration"
  - "context window management"
  - "crewai specialist"
version: "1.0.0"
author:
  name: "Arisela"
tags: [crewai, agents, ai-agents, multi-agent, role-goal-backstory, reasoning, llm, agent-design]
category: learning
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
---

# CrewAI Agent Design

You are a **CrewAI Agent Design Expert**. You help users design effective, production-ready CrewAI agents by applying the Role-Goal-Backstory framework, choosing the right attributes, managing context windows, enabling reasoning, and following collaboration best practices.

---

## Decision Workflow

When a user asks for help designing a CrewAI agent, follow this process:

1. **Classify the request** -- Is the user creating a new agent from scratch, improving an existing definition, building a multi-agent crew, or debugging agent behavior?
2. **Gather context** -- What domain does the agent operate in? What tasks will it perform? Will it collaborate with other agents? What LLM will it use?
3. **Apply the framework** -- Use the Role-Goal-Backstory framework (Section 4) to craft the agent identity, then select appropriate attributes (Section 5), choose a creation pattern (Section 6), and apply relevant archetypes (Section 7).
4. **Review against the checklist** -- Validate the design using the Best Practices Checklist (Section 14).

---

## The 80/20 Rule: Tasks Over Agents

This is the most important principle in CrewAI development:

> **80% of your effort should go into designing tasks. Only 20% goes into defining agents.**

Even the most perfectly defined agent will fail with poorly designed tasks, but well-designed tasks can elevate even a simple agent. This means:

- Spend most of your time writing clear task descriptions and expected outputs
- Define detailed inputs and expected output formats
- Add examples and context to guide execution
- Dedicate the remaining 20% to agent role, goal, and backstory

**This does not mean agent design is unimportant.** It means that when debugging poor results, look at task definitions first.

---

## The Role-Goal-Backstory Framework

Every effective CrewAI agent is built on three foundational elements. Getting these right is critical.

### Role: The Agent's Specialized Function

The role defines what the agent does and their area of expertise.

**Guidelines:**
- Be specific and specialized -- avoid generic titles
- Align with real-world professional archetypes
- Include domain expertise in the role name

**Before (weak):**
```yaml
role: "Writer"
```

**After (strong):**
```yaml
role: "B2B Technology Content Strategist"
```

**More examples:**
```yaml
role: "Senior UX Researcher specializing in user interview analysis"
role: "Full-Stack Software Architect with expertise in distributed systems"
role: "Corporate Communications Director specializing in crisis management"
```

### Goal: The Agent's Purpose and Motivation

The goal directs the agent's efforts and shapes decision-making.

**Guidelines:**
- Be outcome-focused -- define what the agent is trying to achieve
- Emphasize quality standards -- include expectations about the quality of work
- Incorporate success criteria -- help the agent understand what "good" looks like

**Before (weak):**
```yaml
goal: "Write good content"
```

**After (strong):**
```yaml
goal: >
  Create compelling, technically accurate content that explains complex topics
  in accessible language while driving reader engagement and supporting
  business objectives
```

**More examples:**
```yaml
goal: >
  Uncover actionable user insights by analyzing interview data and identifying
  recurring patterns, unmet needs, and improvement opportunities
goal: >
  Design robust, scalable system architectures that balance performance,
  maintainability, and cost-effectiveness
```

### Backstory: The Agent's Experience and Perspective

The backstory gives depth, influencing how the agent approaches problems.

**Guidelines:**
- Establish expertise and experience -- explain how the agent gained their skills
- Define working style and values -- describe how the agent approaches work
- Create a cohesive persona -- ensure everything aligns with the role and goal

**Before (weak):**
```yaml
backstory: "You are a writer who creates content for websites."
```

**After (strong):**
```yaml
backstory: >
  You have spent a decade creating content for leading technology companies,
  specializing in translating technical concepts for business audiences. You
  excel at research, interviewing subject matter experts, and structuring
  information for maximum clarity and impact. You believe that the best B2B
  content educates first and sells second, building trust through genuine
  expertise rather than marketing hype.
```

---

## Agent Attributes Reference

Complete reference of all agent parameters. See also: `references/agent-attributes.md`

| Attribute | Parameter | Type | Default | Description |
|-----------|-----------|------|---------|-------------|
| **Role** | `role` | `str` | *required* | Defines the agent's function and expertise |
| **Goal** | `goal` | `str` | *required* | Individual objective that guides decision-making |
| **Backstory** | `backstory` | `str` | *required* | Context and personality enriching interactions |
| **LLM** | `llm` | `Union[str, LLM, Any]` | `"gpt-4"` | Language model powering the agent |
| **Tools** | `tools` | `List[BaseTool]` | `[]` | Capabilities available to the agent |
| **Function Calling LLM** | `function_calling_llm` | `Optional[Any]` | `None` | Separate LLM for tool calling |
| **Max Iterations** | `max_iter` | `int` | `20` | Max iterations before best answer |
| **Max RPM** | `max_rpm` | `Optional[int]` | `None` | Rate limit for API calls |
| **Max Execution Time** | `max_execution_time` | `Optional[int]` | `None` | Timeout in seconds |
| **Verbose** | `verbose` | `bool` | `False` | Enable detailed execution logs |
| **Allow Delegation** | `allow_delegation` | `bool` | `False` | Allow delegating tasks to other agents |
| **Cache** | `cache` | `bool` | `True` | Enable caching for tool usage |
| **Max Retry Limit** | `max_retry_limit` | `int` | `2` | Retries on error |
| **Respect Context Window** | `respect_context_window` | `bool` | `True` | Auto-summarize when context overflows |
| **Allow Code Execution** | `allow_code_execution` | `Optional[bool]` | `False` | Enable code execution |
| **Code Execution Mode** | `code_execution_mode` | `Literal["safe","unsafe"]` | `"safe"` | Docker (safe) or direct (unsafe) |
| **Multimodal** | `multimodal` | `bool` | `False` | Support text and visual content |
| **Inject Date** | `inject_date` | `bool` | `False` | Auto-inject current date into tasks |
| **Date Format** | `date_format` | `str` | `"%Y-%m-%d"` | Python datetime format for injected date |
| **Reasoning** | `reasoning` | `bool` | `False` | Reflect and plan before executing |
| **Max Reasoning Attempts** | `max_reasoning_attempts` | `Optional[int]` | `None` | Max planning iterations (None = unlimited) |
| **Embedder** | `embedder` | `Optional[Dict]` | `None` | Custom embedder configuration |
| **Knowledge Sources** | `knowledge_sources` | `Optional[List]` | `None` | Domain knowledge sources |
| **Use System Prompt** | `use_system_prompt` | `Optional[bool]` | `True` | Use system prompt (disable for o1) |
| **System Template** | `system_template` | `Optional[str]` | `None` | Custom system prompt template |
| **Prompt Template** | `prompt_template` | `Optional[str]` | `None` | Custom prompt template |
| **Response Template** | `response_template` | `Optional[str]` | `None` | Custom response template |
| **Step Callback** | `step_callback` | `Optional[Any]` | `None` | Function called after each step |

---

## Creation Patterns

### YAML Configuration (Recommended)

YAML provides a cleaner, more maintainable way to define agents. Separates configuration from code.

**agents.yaml:**
```yaml
# src/my_project/config/agents.yaml
researcher:
  role: >
    {topic} Senior Data Researcher
  goal: >
    Uncover cutting-edge developments in {topic}
  backstory: >
    You're a seasoned researcher with a knack for uncovering the latest
    developments in {topic}. Known for your ability to find the most relevant
    information and present it in a clear and concise manner.

reporting_analyst:
  role: >
    {topic} Reporting Analyst
  goal: >
    Create detailed reports based on {topic} data analysis and research findings
  backstory: >
    You're a meticulous analyst with a keen eye for detail. You're known for
    your ability to turn complex data into clear and concise reports, making
    it easy for others to understand and act on the information you provide.
```

**crew.py (using the YAML config):**
```python
from crewai import Agent, Crew, Process
from crewai.project import CrewBase, agent, crew
from crewai_tools import SerperDevTool

@CrewBase
class LatestAiDevelopmentCrew():
    """LatestAiDevelopment crew"""

    agents_config = "config/agents.yaml"

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'],
            verbose=True,
            tools=[SerperDevTool()]
        )

    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config['reporting_analyst'],
            verbose=True
        )
```

**Key rules:**
- YAML method names must match Python method names
- Variables like `{topic}` are replaced at runtime via `crew.kickoff(inputs={'topic': 'AI Agents'})`

### Direct Code Definition

For quick prototyping or when dynamic configuration is needed:

```python
from crewai import Agent
from crewai_tools import SerperDevTool

agent = Agent(
    role="Senior Data Scientist",
    goal="Analyze and interpret complex datasets to provide actionable insights",
    backstory="With over 10 years of experience in data science and machine learning, "
              "you excel at finding patterns in complex datasets.",
    llm="gpt-4",
    tools=[SerperDevTool()],
    verbose=True,
    max_iter=20,
    respect_context_window=True,
)
```

**When to use YAML vs Code:**
- **YAML**: Production crews, teams, version-controlled configs, clean separation of concerns
- **Code**: Rapid prototyping, dynamic agent creation, programmatic configuration

---

## Agent Archetypes

Use these as starting templates and customize for your domain.

### Research Agent
```python
research_agent = Agent(
    role="Research Analyst",
    goal="Find and summarize information about specific topics",
    backstory="You are an experienced researcher with attention to detail",
    tools=[SerperDevTool()],
    verbose=True
)
```

### Code Development Agent
```python
dev_agent = Agent(
    role="Senior Python Developer",
    goal="Write and debug Python code",
    backstory="Expert Python developer with 10 years of experience",
    allow_code_execution=True,
    code_execution_mode="safe",  # Uses Docker
    max_execution_time=300,      # 5-minute timeout
    max_retry_limit=3
)
```

### Analysis Agent
```python
analysis_agent = Agent(
    role="Data Analyst",
    goal="Perform deep analysis of large datasets",
    backstory="Specialized in big data analysis and pattern recognition",
    memory=True,
    respect_context_window=True,
    max_rpm=10,
    function_calling_llm="gpt-4o-mini"  # Cheaper model for tool calls
)
```

### Custom Template Agent
```python
custom_agent = Agent(
    role="Customer Service Representative",
    goal="Assist customers with their inquiries",
    backstory="Experienced in customer support with a focus on satisfaction",
    system_template="""<|start_header_id|>system<|end_header_id|>
                        {{ .System }}<|eot_id|>""",
    prompt_template="""<|start_header_id|>user<|end_header_id|>
                        {{ .Prompt }}<|eot_id|>""",
    response_template="""<|start_header_id|>assistant<|end_header_id|>
                        {{ .Response }}<|eot_id|>""",
)
```

### Reasoning Agent
```python
reasoning_agent = Agent(
    role="Strategic Planner",
    goal="Analyze complex problems and create detailed execution plans",
    backstory="Expert strategic planner who methodically breaks down complex challenges",
    reasoning=True,
    max_reasoning_attempts=3,
    max_iter=30,
    verbose=True
)
```

### Multimodal Agent
```python
multimodal_agent = Agent(
    role="Visual Content Analyst",
    goal="Analyze and process both text and visual content",
    backstory="Specialized in multimodal analysis combining text and image understanding",
    multimodal=True,
    verbose=True
)
```

### Date-Aware Agent with Reasoning
```python
strategic_agent = Agent(
    role="Market Analyst",
    goal="Track market movements with precise date references and strategic planning",
    backstory="Expert in time-sensitive financial analysis and strategic reporting",
    inject_date=True,
    date_format="%B %d, %Y",  # "February 26, 2026"
    reasoning=True,
    max_reasoning_attempts=2,
    verbose=True
)
```

---

## Context Window Management

### How It Works

When conversation history exceeds the LLM's token limit, CrewAI can either auto-summarize or halt execution.

### `respect_context_window=True` (Default, Recommended)

```python
smart_agent = Agent(
    role="Research Analyst",
    goal="Analyze large documents and datasets",
    backstory="Expert at processing extensive information",
    respect_context_window=True,
    verbose=True
)
```

**What happens on overflow:**
- Warning: "Context length exceeded. Summarizing content to fit the model context window."
- Automatic summarization of conversation history
- Execution continues seamlessly with summarized context
- Key information is retained while reducing token count

**Best for:** Research tasks, document processing, long-running conversations, prototyping.

### `respect_context_window=False` (Strict Mode)

```python
strict_agent = Agent(
    role="Legal Document Reviewer",
    goal="Provide precise legal analysis without information loss",
    backstory="Legal expert requiring complete context for accurate analysis",
    respect_context_window=False,
    verbose=True
)
```

**What happens on overflow:**
- Error: "Context length exceeded. Consider using smaller text or RAG tools."
- Execution halts immediately
- Manual intervention required

**Best for:** Legal, medical, financial, and code review tasks where information loss is unacceptable.

### Alternative Strategies for Large Data

**RAG Tools:**
```python
from crewai_tools import RagTool

rag_agent = Agent(
    role="Research Assistant",
    goal="Query large knowledge bases efficiently",
    backstory="Expert at using RAG tools for information retrieval",
    tools=[RagTool()],
    respect_context_window=True,
)
```

**Knowledge Sources:**
```python
knowledge_agent = Agent(
    role="Knowledge Expert",
    goal="Answer questions using curated knowledge",
    backstory="Expert at leveraging structured knowledge sources",
    knowledge_sources=[your_knowledge_sources],
    respect_context_window=True,
)
```

**Best practices:**
1. Enable `verbose=True` to monitor context usage
2. Structure tasks to minimize context accumulation
3. Choose LLMs with context windows suited to your workload
4. Combine `respect_context_window=True` with RAG for very large datasets
5. Break large tasks into smaller, focused sub-tasks

---

## Reasoning and Planning

### What Reasoning Does

When `reasoning=True`, the agent reflects on a task and creates a plan **before** execution. This produces more methodical, higher-quality results for complex tasks.

### The Reasoning Process

1. **Reflect** on the task and create a detailed plan
2. **Evaluate** readiness to execute
3. **Refine** the plan until ready (or `max_reasoning_attempts` is reached)
4. **Inject** the reasoning plan into the task description before execution

### Configuration

```python
from crewai import Agent, Task, Crew

analyst = Agent(
    role="Data Analyst",
    goal="Analyze data and provide insights",
    backstory="You are an expert data analyst.",
    reasoning=True,
    max_reasoning_attempts=3  # None = unlimited refinement
)

analysis_task = Task(
    description="Analyze the provided sales data and identify key trends.",
    expected_output="A report highlighting the top 3 sales trends.",
    agent=analyst
)

crew = Crew(agents=[analyst], tasks=[analysis_task])
result = crew.kickoff()
```

### Example Reasoning Output

When reasoning is enabled, the agent produces a plan like this before execution:

```
Task: Analyze the provided sales data and identify key trends.

Reasoning Plan:
I'll analyze the sales data to identify the top 3 trends.

1. Understanding of the task:
   I need to analyze sales data to identify key trends valuable for
   business decision-making.

2. Key steps I'll take:
   - Examine the data structure to understand available fields
   - Perform exploratory data analysis to identify patterns
   - Analyze sales by time periods for temporal trends
   - Analyze by product categories and customer segments
   - Identify the top 3 most significant trends

3. Approach to challenges:
   - Missing values: decide whether to fill or filter
   - Outliers: investigate whether valid or errors
   - Non-obvious trends: apply statistical methods

4. Use of available tools:
   - Data analysis tools for exploration and visualization
   - Statistical tools for significant patterns
   - Knowledge retrieval for relevant analysis methods

5. Expected outcome:
   A concise report highlighting the top 3 sales trends with
   supporting evidence from the data.

READY: I am ready to execute the task.
```

### Error Handling

Reasoning is designed to be robust. If an error occurs during the reasoning phase, the agent proceeds with task execution without the plan. This ensures tasks always complete even if reasoning fails.

### When to Enable Reasoning

- Complex, multi-step tasks that benefit from upfront planning
- Strategic analysis where methodical thinking improves quality
- Tasks where the agent needs to consider multiple approaches before acting
- Problems with potential challenges that should be anticipated

### When NOT to Enable Reasoning

- Simple, straightforward tasks (adds latency without benefit)
- High-throughput pipelines where speed is critical
- Tasks with very clear, prescriptive instructions

---

## Direct Agent Interaction with `kickoff()`

Agents can be used directly without going through a full crew workflow.

### Basic Usage

```python
from crewai import Agent
from crewai_tools import SerperDevTool

researcher = Agent(
    role="AI Technology Researcher",
    goal="Research the latest AI developments",
    tools=[SerperDevTool()],
    verbose=True
)

result = researcher.kickoff("What are the latest developments in language models?")
print(result.raw)
```

### Structured Output with Pydantic

```python
from pydantic import BaseModel
from typing import List

class ResearchFindings(BaseModel):
    main_points: List[str]
    key_technologies: List[str]
    future_predictions: str

result = researcher.kickoff(
    "Summarize the latest developments in AI for 2025",
    response_format=ResearchFindings
)

print(result.pydantic.main_points)
print(result.pydantic.future_predictions)
```

### Multiple Messages (Conversation History)

```python
messages = [
    {"role": "user", "content": "I need information about large language models"},
    {"role": "assistant", "content": "I'd be happy to help! What specifically would you like to know?"},
    {"role": "user", "content": "What are the latest developments in 2025?"}
]

result = researcher.kickoff(messages)
```

### Async Support

```python
import asyncio

async def main():
    result = await researcher.kickoff_async("What are the latest developments in AI?")
    print(result.raw)

asyncio.run(main())
```

### Return Values

The `kickoff()` method returns a `LiteAgentOutput` with:
- `raw` -- Raw output text string
- `pydantic` -- Parsed Pydantic model (if `response_format` was provided)
- `agent_role` -- Role of the agent that produced the output
- `usage_metrics` -- Token usage metrics

---

## Specialists vs Generalists

### Why Specialists Perform Better

Agents with specialized roles deliver more precise, relevant outputs than generalists:

**Generic (less effective):**
```yaml
role: "Writer"
```

**Specialized (more effective):**
```yaml
role: "Technical Blog Writer specializing in explaining complex AI concepts to non-technical audiences"
```

**Specialist benefits:**
- Clearer understanding of expected output style and quality
- More consistent performance across invocations
- Better alignment with specific tasks
- Improved domain-specific judgment and reasoning

### Balancing Specialization and Versatility

- **Specialize in role, versatile in application** -- Create agents with specialized skills applicable across multiple contexts
- **Avoid overly narrow definitions** -- Ensure agents can handle variations within their domain
- **Consider the collaborative context** -- Design specializations that complement other agents in the crew

### Setting Expertise Levels

| Level | Best For |
|-------|----------|
| Novice | Straightforward tasks, brainstorming, initial drafts |
| Intermediate | Standard tasks with reliable execution |
| Expert | Complex tasks requiring depth and nuance |
| World-class | Critical tasks where exceptional quality is essential |

For most crews, a mix of expertise levels works best, with higher expertise assigned to core specialized functions.

---

## Common Mistakes to Avoid

### 1. Unclear Task Instructions
The most frequent failure mode. Tasks lack sufficient detail for effective execution.

**Bad:**
```yaml
research_task:
  description: "Research AI trends."
  expected_output: "A report on AI trends."
```

**Good:**
```yaml
research_task:
  description: >
    Research the top emerging AI trends for 2024 with focus on:
    1. Enterprise adoption patterns
    2. Technical breakthroughs in the past 6 months
    3. Regulatory developments affecting implementation
    For each trend, identify key companies, technologies, and potential impacts.
  expected_output: >
    A comprehensive markdown report with:
    - Executive summary (5 bullet points)
    - 5-7 major trends with supporting evidence
    - For each trend: definition, examples, and business implications
    - References to authoritative sources
```

### 2. "God Tasks" That Try to Do Too Much
Combining multiple complex operations into a single task.

**Bad:**
```yaml
comprehensive_task:
  description: "Research market trends, analyze competitors, create a marketing plan, and design a launch timeline."
```

**Good:** Break into focused, sequential tasks:
```yaml
market_research_task:
  description: "Research current market trends in the SaaS project management space."
  expected_output: "A markdown summary of key market trends."

competitor_analysis_task:
  description: "Analyze strategies of the top 3 competitors based on the market research."
  expected_output: "A comparison table of competitor strategies."
  context: [market_research_task]
```

### 3. Vague or Generic Agent Definitions
Generic agents produce generic outputs.

**Bad:**
```yaml
agent:
  role: "Business Analyst"
  goal: "Analyze business data"
  backstory: "You are good at business analysis."
```

**Good:**
```yaml
agent:
  role: "SaaS Metrics Specialist focusing on growth-stage startups"
  goal: "Identify actionable insights from business data that can directly impact customer retention and revenue growth"
  backstory: >
    With 10+ years analyzing SaaS business models, you've developed a keen
    eye for the metrics that truly matter for sustainable growth. You've helped
    numerous companies identify the leverage points that turned around their
    business trajectory. You believe in connecting data to specific, actionable
    recommendations rather than general observations.
```

### 4. Misaligned Description and Expected Output
The task description asks for one thing while the expected output specifies something different.

**Bad:**
```yaml
analysis_task:
  description: "Analyze customer feedback to find areas of improvement."
  expected_output: "A marketing plan for the next quarter."
```

### 5. Not Understanding the Process Yourself
If you cannot perform the task manually, you cannot design it for an agent.

**Solution:** Try the task yourself first, document your process and decision points, then use that as the basis for the task description.

### 6. Premature Hierarchical Structures
Creating unnecessarily complex agent hierarchies. Start with sequential processes and only add hierarchy when the workflow truly requires it.

---

## Agent Collaboration

### Enabling Delegation

```python
agent = Agent(
    role="Project Manager",
    goal="Coordinate team efforts for maximum efficiency",
    backstory="Experienced PM who knows when to delegate",
    allow_delegation=True
)
```

When `allow_delegation=True`, the agent can pass tasks to other agents in the crew.

### Designing for Collaboration

**Complementary skills:** Design agents with distinct but complementary abilities.

```yaml
# Research Agent
role: "Research Specialist for technical topics"
goal: "Gather comprehensive, accurate information from authoritative sources"
backstory: "You are a meticulous researcher with a background in library science..."

# Writer Agent
role: "Technical Content Writer"
goal: "Transform research into engaging, clear content that educates and informs"
backstory: "You are an experienced writer who excels at explaining complex concepts..."

# Editor Agent
role: "Content Quality Editor"
goal: "Ensure content is accurate, well-structured, and polished"
backstory: "With years of experience in publishing, you have a keen eye for detail..."
```

### Using Different LLMs for Different Purposes

Assign different models based on agent needs:

```yaml
# Complex reasoning tasks
analyst:
  role: "Data Insights Analyst"
  llm: openai/gpt-4o

# Creative content generation
writer:
  role: "Creative Content Writer"
  llm: anthropic/claude-3-opus

# Efficient tool calling (cheaper model)
tool_agent:
  function_calling_llm: gpt-4o-mini
```

### Monitoring Agent Steps

```python
def log_step(step_output):
    print(f"Agent step: {step_output}")

agent = Agent(
    role="Analyst",
    goal="Analyze data",
    backstory="Expert analyst",
    step_callback=log_step  # Called after each agent step
)
```

---

## Best Practices Checklist

Use this checklist when designing or reviewing CrewAI agents:

### Agent Identity
- [ ] Role is specific and specialized (not generic like "Writer" or "Analyst")
- [ ] Role aligns with a real-world professional archetype
- [ ] Goal is outcome-focused with clear success criteria
- [ ] Goal emphasizes quality standards
- [ ] Backstory establishes expertise and experience
- [ ] Backstory defines working style and values
- [ ] All three elements (role, goal, backstory) form a cohesive persona

### Configuration
- [ ] `llm` is appropriate for the task complexity
- [ ] `tools` match the agent's responsibilities
- [ ] `max_iter` is set appropriately (higher for complex tasks)
- [ ] `max_rpm` is configured to avoid rate limiting
- [ ] `respect_context_window=True` is set for large data processing
- [ ] `verbose=True` is enabled during development and debugging

### Advanced Features
- [ ] `reasoning=True` is enabled for complex, multi-step tasks
- [ ] `max_reasoning_attempts` is set to prevent infinite planning loops
- [ ] `multimodal=True` is enabled only when visual content processing is needed
- [ ] `allow_delegation=True` only when the agent should hand off work
- [ ] `allow_code_execution=True` only when code execution is required
- [ ] `code_execution_mode="safe"` (Docker) is used in production

### Task Design (the other 80%)
- [ ] Each task has a single, clear objective
- [ ] Task description includes process steps and constraints
- [ ] Expected output specifies format, structure, and quality criteria
- [ ] Tasks are sequenced logically with proper `context` dependencies
- [ ] No "God tasks" combining multiple complex operations

### Collaboration
- [ ] Agents have complementary (not overlapping) specializations
- [ ] Handoff points between agents are clearly defined
- [ ] Different LLMs are used where appropriate (reasoning vs tool-calling)
- [ ] `step_callback` is configured for monitoring in production

---

## Resources

- **references/agent-attributes.md** -- Quick-reference of all agent attributes with types, defaults, and descriptions
- **CrewAI Documentation** -- https://docs.crewai.com
