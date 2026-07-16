"""ChatAnthropic factories.

LangGraph concept — the model is just another dependency: nodes call a
LangChain chat model object; nothing about LangGraph dictates which. A BYO
container owns its own model wiring (kagent ModelConfig does not apply).
"""

from langchain_anthropic import ChatAnthropic

from homelab_agent.config import settings


def get_model() -> ChatAnthropic:
    """Main model (Sonnet): retrieval agent, drift check, synthesis."""
    return ChatAnthropic(model=settings.model_name, temperature=0, max_tokens=4096)


def get_router_model() -> ChatAnthropic:
    """Cheap model for orient's fallback classifier only."""
    return ChatAnthropic(
        model=settings.router_model_name, temperature=0, max_tokens=16
    )
