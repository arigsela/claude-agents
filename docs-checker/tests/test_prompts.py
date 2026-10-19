"""Lever 1 at the wire: what ChatAnthropic would send, built offline (no request is made).

``_get_request_payload`` is private to langchain-anthropic 1.7; if it moves, this
test should move with it rather than be deleted, because it is the only check
that the breakpoint, the tool order and the per-node effort reach the request.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

import pytest
from langchain_core.messages import HumanMessage

from docs_checker import prompts
from docs_checker.config import load_settings
from docs_checker.gate import RecordingGate
from docs_checker.models import AnthropicModels
from docs_checker.prompts import (
    CHECKER_VERSION,
    DATA_RULE,
    DEFAULT_NODE_MODELS,
    POLICY,
    PROMPTS,
    checker_version,
    fence,
    fence_token,
    validate_replacement,
)
from docs_checker.tools import ToolBelt
from tests.fakes import FAKE_BINDINGS, fake_tools_by_server


def payload(node: str, messages, tools=None):
    settings = load_settings({})
    model = AnthropicModels(
        settings.node_models, settings.levers, http_timeout_s=settings.http_timeout_s
    ).get(node)
    if tools:
        model = model.bind_tools(tools)
        return model.bound._get_request_payload(messages, **model.kwargs)
    return model._get_request_payload(messages)


def test_the_system_prompt_is_a_cached_frozen_prefix():
    system = prompts.AGENT_DESCRIPTION
    question = [HumanMessage("check base-apps/vault/docs.md")]
    first = payload("intake", [prompts.system_message(system, cache=True), *question])
    second = payload("intake", [prompts.system_message(system, cache=True), *question])

    assert first["system"] == second["system"]  # byte-identical across runs
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert first["model"] == "claude-haiku-5-5"
    assert first["output_config"]["effort"] == "low"  # lever 6: effort per node


def test_node_tools_are_sent_sorted_and_scoped():
    belt = ToolBelt(fake_tools_by_server(), RecordingGate(), bindings=FAKE_BINDINGS)
    sent = payload(
        "judge_escalate",
        [prompts.system_message(prompts.AGENT_DESCRIPTION, cache=True), HumanMessage("q")],
        tools=belt.schemas_for("scope"),
    )
    assert [t["name"] for t in sent["tools"]] == ["get_commit", "get_file_contents", "list_commits"]
    assert sent["model"] == "claude-sonnet-5-5"


# --- frozen prompts, fences and the checker version ---------------------------

SYSTEM_PROMPTS = (prompts.INTAKE, prompts.EXTRACT, prompts.JUDGE, prompts.FIX)
_FINGERPRINT = (
    "import hashlib, json\n"
    "from docs_checker import prompts as p\n"
    "print(json.dumps({'version': p.CHECKER_VERSION, 'prompts': "
    "{k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(p.PROMPTS.items())}}))"
)


def test_prompts_are_byte_identical_across_runs():
    """Two fresh interpreters (different hash seeds) build the same prompts and version."""
    here = json.dumps(
        {
            "version": CHECKER_VERSION,
            "prompts": {
                k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(PROMPTS.items())
            },
        }
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", _FINGERPRINT],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("1", "2")
    ]
    assert runs == [here, here]
    for prompt in SYSTEM_PROMPTS:
        assert prompt in PROMPTS.values()
        # No per-run data: no hashes or ids, no dates.
        assert not re.search(r"\b[0-9a-f]{12,}\b|\b\d{4}-\d{2}-\d{2}\b", prompt)


def test_every_system_prompt_says_fenced_text_is_data():
    for prompt in SYSTEM_PROMPTS:
        assert prompt.endswith(DATA_RULE)
    assert "<data-TOKEN>" in DATA_RULE and "never" in DATA_RULE and "instructions" in DATA_RULE


def test_checker_version_changes_when_a_prompt_changes():
    base = checker_version(PROMPTS, DEFAULT_NODE_MODELS, POLICY)
    assert base == CHECKER_VERSION and re.fullmatch(r"[0-9a-f]{12}", base)
    assert checker_version({**PROMPTS, "judge": PROMPTS["judge"] + " "}, DEFAULT_NODE_MODELS, POLICY) != base  # fmt: skip
    assert checker_version(PROMPTS, {**DEFAULT_NODE_MODELS, "judge": "claude-sonnet-5-5"}, POLICY) != base  # fmt: skip
    assert checker_version(PROMPTS, DEFAULT_NODE_MODELS, {**POLICY, "escalate_below": 0.7}) != base
    assert DEFAULT_NODE_MODELS["judge"] == "claude-haiku-5-5"
    assert DEFAULT_NODE_MODELS["judge_escalate"] == "claude-sonnet-5-5"
    assert POLICY["escalate_below"] == 0.8


def test_fence_token_is_deterministic_and_unambiguous():
    commit = "c0ffee" + "1" * 34
    token = fence_token(commit, "docs/a.md", 5, 9)
    assert token == fence_token(commit, "docs/a.md", 5, 9)
    assert re.fullmatch(r"[0-9a-f]{12}", token)
    assert fence_token("f" * 40, "docs/a.md", 5, 9) != token  # a new commit, a new token
    assert fence_token("ab", "c", 1, 2) != fence_token("a", "bc", 1, 2)
    assert fence_token(commit, "p", 1, 23) != fence_token(commit, "p", 12, 3)
    block = fence("line one\nline two", token)
    assert block == f"<data-{token}>\nline one\nline two\n</data-{token}>"


# --- validate_replacement ----------------------------------------------------

OLD = "Vault runs chart version 0.30.1 in namespace vault."
EVIDENCE = "chart: vault\nversion: 0.31.0\nimage:\n  repository: hashicorp/vault\n  tag: 1.15.6"


@pytest.mark.parametrize(
    "old, new, evidence",
    [
        (OLD, "Vault runs chart version 0.31.0 in namespace vault.", EVIDENCE),
        # Plain words may change; the new value still comes from the evidence.
        (OLD, "Vault now runs chart version 0.31.0 in namespace vault.", EVIDENCE),
        # An image reference: each part (split at ":" and "@") comes from somewhere.
        ("Image `hashicorp/vault:1.15.2`.", "Image `hashicorp/vault:1.15.6`.", EVIDENCE),
        # A leading "v" on a version is ignored, either way round.
        ("Runs vault v1.15.2.", "Runs vault v1.15.6.", EVIDENCE),
        ("Runs vault 1.15.2.", "Runs vault 1.15.6.", "tag: v1.15.6"),
        # Tokens already in the old line may stay.
        (
            "Set in base-apps/vault/values.yaml: 0.30.1",
            "Set in base-apps/vault/values.yaml: 0.31.0",
            EVIDENCE,
        ),
    ],
)
def test_validate_replacement_accepts_values_from_the_evidence(old, new, evidence):
    assert validate_replacement(old, new, evidence) == new


@pytest.mark.parametrize(
    "new",
    [
        "Vault runs chart version 0.31.0, see https://evil.example/install.sh",
        "Vault runs chart version 0.31.0 (www.evil.example).",
        "Vault runs chart version 0.31.0 in base-apps/evil/values.yaml.",
        "Vault runs chart version 0.31.0 from evil.example.com.",
        "Vault runs chart version 9.9.9 in namespace vault.",
        "Vault runs chart version 0.31.0 as evil:latest.",
        "Vault runs chart version [0.31.0](notes) in namespace vault.",
        "Vault runs chart version ![chart](chart) in namespace vault.",
        "Vault runs chart version <a href=x>0.31.0</a>.",
        "Vault runs chart\nversion 0.31.0 in namespace vault.",
        "",
        "  \n",
        OLD + " and more" * 30,
    ],
    ids=[
        "url", "www", "new-path", "new-host", "value-from-nowhere", "image-part-from-nowhere",
        "markdown-link", "markdown-image", "html-link", "line-count", "empty", "blank", "too-long",
    ],
)  # fmt: skip
def test_validate_replacement_rejects(new):
    assert validate_replacement(OLD, new, EVIDENCE) is None


def test_a_url_is_rejected_even_when_the_old_line_has_it():
    old = "Chart 0.30.1 from https://helm.releases.hashicorp.com"
    new = "Chart 0.31.0 from https://helm.releases.hashicorp.com"
    assert validate_replacement(old, new, EVIDENCE) is None


def test_a_token_must_match_whole_not_as_part_of_another():
    assert validate_replacement("Runs 1.15.2.", "Runs 1.15.6.", "tag: 11.15.6") is None
    assert validate_replacement("Runs 1.15.2.", "Runs 1.15.", "tag: 1.15.6") is None
    assert validate_replacement("Host a.example.com.", "Host example.com.", "mail.example.com") is None  # fmt: skip


def test_validate_replacement_cleans_line_endings():
    assert validate_replacement("a 1.0\nb", "a 1.1\r\nb\n", "v: 1.1") == "a 1.1\nb"
