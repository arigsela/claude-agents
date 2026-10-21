"""ChatAnthropic factories.

LangGraph concept — the model is just another dependency: nodes call a
LangChain chat model object; nothing about LangGraph dictates which. A BYO
container owns its own model wiring (kagent ModelConfig does not apply).
"""

from langchain_anthropic import ChatAnthropic

from homelab_agent.config import settings


def get_model() -> ChatAnthropic:
    """Main model (Sonnet): retrieval agent, drift check, synthesis.

    No temperature: claude-sonnet-5 rejects non-default sampling params (400).
    It also runs adaptive thinking by default, and max_tokens caps thinking and
    the answer together, so leave headroom. Replies then carry a thinking block
    before the text — read them with `.text`, never `.content`.
    """
    return ChatAnthropic(model=settings.model_name, max_tokens=16000)


def get_router_model() -> ChatAnthropic:
    """Cheap model for orient's fallback classifier only."""
    return ChatAnthropic(model=settings.router_model_name, temperature=0, max_tokens=16)
