# Review rubric — claude-agents

Python-first repo (black / ruff / pytest). AI agents that talk to the Anthropic
API, Kubernetes, Slack, and GitOps. Hold the diff to the bar below.

## Correctness
- Logic matches the apparent intent; no off-by-one, inverted conditions, or
  unhandled empty/None/error cases.
- Changed a public function signature? Every caller in the diff is updated.
- No bare `except:` and no `except Exception: pass` — exceptions are either
  handled meaningfully or allowed to propagate.
- New public functions/methods have type hints; non-obvious ones have a concise
  docstring.
- No debug leftovers: stray `print()`, commented-out code, or `TODO`/`FIXME`
  without an issue/PR reference.

## Security
- No secrets, API keys, or tokens in code, config, or fixtures — read from env
  or a secret store. Anthropic keys and Slack tokens especially.
- External input (Slack payloads, HTTP request bodies, LLM tool arguments) is
  validated before use; no shell/SQL/path injection; no `eval`/`exec` on it.
- No `subprocess` with `shell=True` on interpolated input.
- kubectl / k8s client calls that mutate cluster state are gated and scoped —
  no unbounded delete/apply across namespaces.
- No new third-party dependency without a clear need.

## Tests
- New behavior or a bug fix ships with a pytest test that would FAIL without
  the change.
- Tests assert on real outcomes, not just "it ran without raising."
- External calls (Anthropic API, k8s, Slack, HTTP) are mocked/stubbed — tests
  don't hit live services or require network.

## Scope
- The diff does one thing. No opportunistic refactors folded into a fix.
- No black/ruff reformatting churn on lines unrelated to the change.
- No unrelated dependency bumps.

## Reject on sight
- Swallowed exceptions (bare `except`, `except: pass`) with no handling.
- Weakened, skipped, or deleted tests to make a build go green.
- Hardcoded secret, key, or token anywhere in the diff.
- Cluster-mutating operation with no scope limit or guard.
