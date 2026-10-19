import pytest

from docs_checker.levers import Levers, parse_levers

NAMES = (
    "cache_prefix",
    "typed_handoffs",
    "short_circuit",
    "tools_on_demand",
    "retry_limits",
    "right_size",
    "shrink_results",
)


def test_parse_levers_forms():
    assert Levers.names() == NAMES
    assert parse_levers("all") == Levers.all_on()
    assert parse_levers("none") == Levers.all_off()
    assert parse_levers("") == Levers.all_on()
    assert parse_levers("cache_prefix, short_circuit") == Levers(
        **{n: n in {"cache_prefix", "short_circuit"} for n in NAMES}
    )
    assert parse_levers("-right_size") == Levers.without("right_size")
    assert parse_levers("-right_size,-cache_prefix") == Levers(
        **{n: n not in {"right_size", "cache_prefix"} for n in NAMES}
    )
    assert Levers.only("shrink_results").shrink_results
    assert sum(vars(Levers.only("shrink_results")).values()) == 1
    assert sum(vars(Levers.without("shrink_results")).values()) == 6


@pytest.mark.parametrize("spec", ["bogus", "-bogus", "cache_prefix,-right_size", ",", "all,none"])
def test_parse_levers_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        parse_levers(spec)
