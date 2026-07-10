---
description: Draft a .judge/rubric.md for this repo via Codex, then review and write it
allowed-tools: Bash(bash "${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh":*), Write
---

Scaffold a rubric for this repo:

1. Execute: `bash "${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh"`
2. If it exits non-zero, show the error to the user verbatim and stop; there
   is nothing to write.
3. On success, show the drafted rubric to the user verbatim.
4. Check whether `.judge/rubric.md` already exists in this repo. If it does,
   warn the user that this will overwrite it and confirm before proceeding.
5. Write the drafted content to `.judge/rubric.md` using the Write tool. Do
   not commit it; let the user review and commit normally.
