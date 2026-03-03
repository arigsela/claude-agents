# ==============================================================================
# Pydantic Output Models & Guardrail Validators
# ==============================================================================
#
# WHAT ARE OUTPUT MODELS?
# CrewAI agents can return structured data instead of free-form text.
# By specifying a Pydantic model as the agent's `output_pydantic`, CrewAI
# instructs the LLM to return JSON matching the schema. This ensures
# predictable, parseable output that downstream systems can consume.
#
# WHAT ARE GUARDRAILS?
# Guardrails are validation functions that run AFTER the agent produces output.
# If the guardrail returns a failure, CrewAI asks the agent to try again
# (up to max_iter times). This prevents low-quality or incomplete responses.
#
# HOW TO USE:
#   agent = Agent(
#       ...,
#       output_pydantic=AgentOutput,        # Structured output
#       guardrail=validate_agent_output,     # Quality check
#   )
# ==============================================================================

from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    """
    Structured output model for the sub-agent.

    Every response from the agent will include these fields, making it easy
    to parse and display in UIs, log for observability, or chain into other agents.

    Customize these fields based on your agent's domain. For example, a
    K8s diagnostics agent might have: service, namespace, root_cause, priority.
    """

    summary: str = Field(
        description="A concise summary of the agent's findings or answer."
    )
    details: str = Field(
        description="Detailed explanation with evidence and reasoning."
    )
    confidence: str = Field(
        default="medium",
        description="Confidence level: high, medium, or low."
    )
    sources: list[str] = Field(
        default_factory=list,
        description="List of sources consulted (files, APIs, knowledge docs)."
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable next steps or recommendations."
    )


def validate_agent_output(output: AgentOutput) -> tuple[bool, str]:
    """
    Guardrail validator for agent output quality.

    CrewAI calls this after the agent produces output. If it returns
    (False, "reason"), CrewAI asks the agent to retry with the feedback.

    Args:
        output: The parsed Pydantic model from the agent.

    Returns:
        (True, "") if valid, or (False, "feedback message") if the agent should retry.
    """
    # Reject empty or very short summaries — the agent didn't do enough work
    if len(output.summary) < 30:
        return (
            False,
            "Summary is too short. Please provide a more detailed summary of your findings."
        )

    # Reject empty details — we need the reasoning, not just the answer
    if len(output.details) < 50:
        return (
            False,
            "Details section is too brief. Include your reasoning and evidence."
        )

    return (True, "")

