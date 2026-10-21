#!/usr/bin/env python
"""Run the golden questions against both agents over A2A; write parity-report.md.

Usage (both agents must be reachable, e.g. via kubectl port-forward):
    OLD_AGENT_URL=http://localhost:18080 NEW_AGENT_URL=http://localhost:8080 \
        python scripts/parity_check.py
"""

import asyncio
import os
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from homelab_agent.parity import build_report, format_check, read_only_check  # noqa: E402
from homelab_agent.tools import a2a_send  # noqa: E402

GOLDEN = pathlib.Path(__file__).parent.parent / "tests" / "parity" / "golden_questions.yaml"


async def ask(url: str, question: str) -> str:
    try:
        return await a2a_send(url, question, timeout=300.0)
    except Exception as exc:  # a dead agent shouldn't kill the whole run
        return f"(error: {exc})"


async def main() -> int:
    old_url = os.environ["OLD_AGENT_URL"]
    new_url = os.environ["NEW_AGENT_URL"]
    questions = yaml.safe_load(GOLDEN.read_text())

    results = []
    for item in questions:
        question = item["question"]
        print(f"asking both agents: {question}")
        old_answer = await ask(old_url, question)
        new_answer = await ask(new_url, question)
        results.append({
            "skill": item["skill"],
            "question": question,
            "old_answer": old_answer,
            "new_answer": new_answer,
            "new_violations": format_check(new_answer) + read_only_check(new_answer),
        })

    report = build_report(results)
    out = pathlib.Path("parity-report.md")
    out.write_text(report)
    failures = sum(1 for r in results if r["new_violations"])
    print(f"wrote {out} — {len(results)} questions, {failures} with violations")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
