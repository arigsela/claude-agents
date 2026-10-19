"""The seven cost levers, each a switch, so a run can measure what one saves.

``DOCS_CHECKER_LEVERS`` selects them: ``all``, ``none``, a list (``cache_prefix,
short_circuit``) or leave-one-out (``-right_size``; several allowed: ``-a,-b``).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Levers:
    cache_prefix: bool = True
    typed_handoffs: bool = True
    short_circuit: bool = True
    tools_on_demand: bool = True
    retry_limits: bool = True
    right_size: bool = True
    shrink_results: bool = True

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def all_on(cls) -> Levers:
        return cls()

    @classmethod
    def all_off(cls) -> Levers:
        return cls(**{name: False for name in cls.names()})

    @classmethod
    def only(cls, name: str) -> Levers:
        _check(name)
        return replace(cls.all_off(), **{name: True})

    @classmethod
    def without(cls, name: str) -> Levers:
        _check(name)
        return replace(cls.all_on(), **{name: False})


def _check(name: str) -> str:
    if name not in Levers.names():
        raise ValueError(f"unknown lever {name!r}; known: {', '.join(Levers.names())}")
    return name


def parse_levers(spec: str) -> Levers:
    text = (spec or "all").strip()
    if text == "all":
        return Levers.all_on()
    if text == "none":
        return Levers.all_off()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("DOCS_CHECKER_LEVERS is empty; use all, none, a,b or -a")
    removed = [p for p in parts if p.startswith("-")]
    if removed and len(removed) != len(parts):
        raise ValueError(f"cannot mix included and excluded levers: {spec!r}")
    if removed:
        levers = Levers.all_on()
        for part in removed:
            levers = replace(levers, **{_check(part[1:]): False})
        return levers
    return replace(Levers.all_off(), **{_check(p): True for p in parts})
