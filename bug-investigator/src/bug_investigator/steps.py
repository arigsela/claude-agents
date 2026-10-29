"""The UI step format: validate a list of steps, describe one, load a repro file.

Standard library only; the replay engine (browser.py) is the one place that
drives a browser.
"""

from __future__ import annotations

import json

ACTIONS = ("click", "fill", "select", "press", "goto")
CHECKS = ("expect_visible", "expect_absent", "expect_text")
MAX_STEPS = 15
MAX_TEXT = 200

NEEDS_VALUE = ("fill", "select", "press", "goto", "expect_text")
LOCATORS = ("role", "label", "placeholder", "text")
STEP_KEYS = {"do", "target", "value", "note"}
TARGET_KEYS = set(LOCATORS) | {"name", "within"}
WITHIN_KEYS = {"css", "text"}


def _nonempty(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _check_target(t) -> list[str]:
    if not isinstance(t, dict):
        return ["target must be an object"]
    probs = []
    unknown = sorted(set(t) - TARGET_KEYS)
    if unknown:
        probs.append(f"target has unknown keys: {', '.join(unknown)}")
    if sum(1 for k in LOCATORS if k in t) != 1:
        probs.append("target needs exactly one of role, label, placeholder, text")
    for k in LOCATORS + ("name",):
        if k in t and not _nonempty(t[k]):
            probs.append(f"target {k} must be a non-empty string")
        elif k in t and len(t[k]) > MAX_TEXT:
            probs.append(f"target {k} is longer than {MAX_TEXT} characters")
    if "name" in t and "role" not in t:
        probs.append("target name is allowed only with role")
    if "within" in t:
        w = t["within"]
        if not isinstance(w, dict):
            probs.append("target within must be an object")
        else:
            if set(w) != WITHIN_KEYS or not all(_nonempty(w.get(k)) for k in WITHIN_KEYS):
                probs.append("target within needs non-empty css and text, and nothing else")
            elif any(len(w[k]) > MAX_TEXT for k in WITHIN_KEYS):
                probs.append(f"target within is longer than {MAX_TEXT} characters")
    return probs


def _check_step(s) -> list[str]:
    if not isinstance(s, dict):
        return ["a step must be an object"]
    do = s.get("do")
    if do not in ACTIONS + CHECKS:
        return [f"do must be one of {', '.join(ACTIONS + CHECKS)}"]
    probs = []
    unknown = sorted(set(s) - STEP_KEYS)
    if unknown:
        probs.append(f"unknown keys: {', '.join(unknown)}")
    if do == "goto":
        if "target" in s:
            probs.append("goto takes no target")
    elif "target" not in s:
        probs.append(f"{do} needs a target")
    else:
        probs += _check_target(s["target"])
    v = s.get("value")
    if do in NEEDS_VALUE:
        if not isinstance(v, str) or v == "":
            probs.append(f"{do} needs a value")
        elif len(v) > MAX_TEXT:
            probs.append(f"value is longer than {MAX_TEXT} characters")
        elif do == "goto" and not (v.startswith("/") and not v.startswith("//")):
            probs.append("goto value must be a path starting with / (not //)")
        elif do == "goto" and any(c == "\\" or ord(c) < 0x20 or ord(c) == 0x7F for c in v):
            # A browser normalises "/\evil" and "/<tab>/evil" to //evil, another origin.
            probs.append("goto value must not contain a backslash or control characters")
    elif "value" in s:
        probs.append(f"{do} takes no value")
    if "note" in s and not (isinstance(s["note"], str) and len(s["note"]) <= MAX_TEXT):
        probs.append(f"note must be a string of at most {MAX_TEXT} characters")
    return probs


def validate(steps, fails_at=None) -> list[str]:
    """Problems with a list of steps (and the claimed failing step); [] when valid."""
    if not isinstance(steps, list) or not steps:
        return ["steps must be a non-empty list"]
    probs = []
    if len(steps) > MAX_STEPS:
        probs.append(f"at most {MAX_STEPS} steps are allowed, got {len(steps)}")
    for i, s in enumerate(steps, 1):
        probs += [f"step {i}: {p}" for p in _check_step(s)]
    if fails_at is not None and (
        isinstance(fails_at, bool) or not isinstance(fails_at, int) or not 1 <= fails_at <= len(steps)
    ):
        probs.append(f"fails_at must be null or a step number from 1 to {len(steps)}")
    return probs


def phrase(t: dict) -> str:
    """A (valid) target in words: 'button "Done" in .card "Update the cookie banner copy"'."""
    if "role" in t:
        p = f'{t["role"]} "{t["name"]}"' if t.get("name") else t["role"]
    elif "label" in t:
        p = f'the field labelled "{t["label"]}"'
    elif "placeholder" in t:
        p = f'the field with placeholder "{t["placeholder"]}"'
    else:
        p = f'the text "{t["text"]}"'
    w = t.get("within")
    return f'{p} in {w["css"]} "{w["text"]}"' if w else p


def describe(step: dict) -> str:
    """One plain sentence for a (valid) step."""
    do, v = step["do"], step.get("value")
    if do == "goto":
        return f"open {v}"
    t = phrase(step["target"])
    return {
        "click": f"click {t}",
        "fill": f'fill {t} with "{v}"',
        "select": f'select "{v}" in {t}',
        "press": f"press {v} in {t}",
        "expect_visible": f"expect {t} to be visible",
        "expect_absent": f"expect no {t}",
        "expect_text": f'expect {t} to contain "{v}"',
    }[do]


def load_repro(path) -> dict:
    """Read and validate a repro file; ValueError listing every problem."""
    with open(path, encoding="utf-8") as f:
        try:
            doc = json.load(f)
        except ValueError as e:
            raise ValueError(f"{path}: not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: a repro must be a JSON object")
    probs = []
    if not _nonempty(doc.get("title")):
        probs.append("title must be a non-empty string")
    issue = doc.get("issue")
    if issue is not None and (isinstance(issue, bool) or not isinstance(issue, int)):
        probs.append("issue must be an integer or null")
    unknown = sorted(set(doc) - {"title", "issue", "steps"})
    if unknown:
        probs.append(f"unknown keys: {', '.join(unknown)}")
    probs += validate(doc.get("steps"), fails_at=None)
    if probs:
        raise ValueError(f"{path}: " + "; ".join(probs))
    doc.setdefault("issue", None)
    return doc
