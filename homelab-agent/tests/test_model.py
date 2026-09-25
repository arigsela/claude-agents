"""Model factories: the request shape the configured models accept."""

from homelab_agent.model import get_model


def test_main_model_sends_no_sampling_params():
    # claude-sonnet-5 rejects non-default temperature/top_p/top_k with a 400.
    model = get_model()
    assert model.temperature is None
    assert model.top_p is None
    assert model.top_k is None


def test_main_model_leaves_room_for_adaptive_thinking():
    # claude-sonnet-5 thinks by default, and max_tokens caps thinking and the
    # answer together; 4096 (sized for thinking-off Sonnet 4.6) can truncate.
    assert get_model().max_tokens >= 16000
