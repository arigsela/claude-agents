# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## docs-checker

Read-only LangGraph agent in `docs-checker/` that finds lines in the `arigsela/kubernetes` docs that no longer match the manifests they describe and proposes the corrected line. Built as a kagent 1.0 BYO runtime, with a second AgentCore entrypoint and a per-run cost ledger.

## Commands

Run from `docs-checker/`; it has its own uv venv. Tests use scripted fake models and fake tools, make no Anthropic calls and need no key.

```bash
uv sync --extra dev
.venv/bin/pytest -q
.venv/bin/pytest tests/test_gate.py -q -k <name>        # single test
.venv/bin/black --check src tests && .venv/bin/ruff check src tests
.venv/bin/python -m tests.smoke_stack record            # re-record smoke cassettes after changing a model request

# From the repo root
docker build --platform linux/amd64 -t docs-checker:dev docs-checker
bash docs-checker/scripts/smoke.sh                      # DOCKER_CONTEXT=<context> to pick a docker context
```

## Architecture

- **Runtime contract:** targets kagent v1.0.0-alpha14 (commit `673d181e`): A2A v1 over gRPC on 80, `GET /readyz` on 8081 bound after A2A, controller TaskStore `kagent.runtime.v1`, config from `KAGENT_CONFIG_JSON` as an `ADKConfig`. Incompatible with alpha11.
- **Pins:** the `kagent` extra pins `kagent-core==1.0.0a14` and installs `kagent-proto` from git at the tag's commit; bump both in lockstep with the controller. `grpcio-health-checking` stays below 1.75 because kagent-proto needs protobuf < 7. `markdown-it-py`/`linkify-it-py` are exact pins because the fix gate's render is a security check.
- **Entrypoints:** `docs-checker` (`front.py`, kagent) and `docs-checker-agentcore` (`agentcore.py`, `Dockerfile.agentcore`, `deploy/agentcore/`: A2A JSON-RPC on 9000 for Bedrock AgentCore Runtime). The `dev` extra installs both runtime extras so their contract tests always run.
- **Flow:** one A2A task = one graph run (`executor.py` runs `graph.py`) = one ledger (`ledger.py`). Every tool call passes `tools.py` (read-only allowlist, per-server bindings, per-node and repository scoping) then the drift gate (`gate.py`). A paused call runs only when the reply approves that call's id with boolean `True`.
- **Persistence:** state that must survive a snapshot lives under `/data` (sqlite checkpointer, paused-task ledger and replay memo in `paused.py`).
- **Replay:** model calls in the smoke test come from cassettes via `DOCS_CHECKER_REPLAY_DIR`; `tests/test_smoke_stack.py` runs the same task in process and fails when a change alters a model request.

## Key Files

- `docs-checker/README.md` - runtime contract, plumbing, configuration, results
- `docs-checker/HANDOFF.md` - deploy state and open items
- `docs-checker/evals/README.md` - eval harness (record/replay, $20 spend guard, scoring)
- `docs/superpowers/specs/2026-10-18-docs-checker-design.md` - design
- `docs/superpowers/plans/2026-10-18-docs-checker-plan.md`, `docs/superpowers/plans/2026-10-19-docs-checker-agentcore-plan.md` - plans
