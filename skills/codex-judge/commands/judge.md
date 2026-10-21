---
description: Run the Codex judge on the current working-tree diff (manual mode)
allowed-tools: Bash(bash:*)
---

Run the Codex judge manually and report its verdict:

1. Execute: `bash "${CLAUDE_PLUGIN_ROOT}/hooks/judge.sh" --manual`
2. Show the verdict and rationale to the user verbatim.
3. If the verdict is REWORK, address each finding in the rationale, then run
   the judge again. Stop after the judge approves or after 3 rework rounds —
   if still failing, summarize the unresolved findings for the user instead.
