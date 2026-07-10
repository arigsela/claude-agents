# /judge-init — Design

**Date:** 2026-07-10
**Status:** Approved
**Owner (harness):** Claude Code — all `~/.claude` resources
**Owner (judgment content):** Codex CLI — drafted `.judge/rubric.md`, per repo

## Problem

Activating codex-judge in a new repo requires a hand-written `.judge/rubric.md`.
The one rubric that exists today (`claude-agents/.judge/rubric.md`) was in
practice authored by Claude (`d791405`, co-authored-by Claude Opus 4.8),
despite the original codex-judge design stating "Claude never writes the
rubric grading its own diffs" (`2026-07-06-codex-judge-stop-hook-design.md`).
`/judge-init` closes that gap: it drafts a repo-tailored rubric via Codex,
restoring cross-family separation, and gives the user a repeatable way to
bootstrap codex-judge across different repos and stacks (Python, Terraform,
etc.) instead of hand-authoring each one.

## Architecture

Claude runs `rubric_init.sh` in the target repo → the script asks Codex to
explore the repo and draft a rubric → Claude presents the draft and writes it:

```
/judge-init ──▶ Claude runs rubric_init.sh
                 │ gate: git repo?           no ──▶ exit 1, message
                 │ gate: codex on PATH?      no ──▶ exit 1, message
                 │ prompt: rubric-init.prompt.md (fixed 5-section skeleton
                 │         + bundled example-rubric.md as style example)
                 ▼
        codex exec --sandbox read-only --output-last-message <tmpfile> \
          - < prompt.md          (cwd = target repo root; Codex explores
                                   the repo itself via its own read access)
                 │
                 ▼ read last-message file as raw markdown, no JSON contract
        print drafted rubric to stdout, exit 0
                 │
                 ▼ (command instructions take back over)
        Claude shows the draft verbatim
        if .judge/rubric.md exists ──▶ warn + confirm before overwrite
        Claude writes the file via its own Write tool
        user reviews/edits/commits normally — no auto-commit
```

Fail-loud, not fail-open: unlike `judge.sh`, this command doesn't gate a Stop
event, so a failure isn't silently absorbed — it's reported to the user with
enough detail to fix and retry. There is no round counter and no verdict log;
this is a one-shot scaffolding action, not part of the judge/rework loop.

## Components

Repo source is versioned for plugin packaging (`skills/codex-judge/`); live
copies mirror the existing dual-install pattern that `/judge`/`judge.sh`
already use (settings.json and `~/.claude/commands/judge.md` invoke the live
`~/.claude/hooks/judge.sh` directly, not the plugin-packaged copy).

| Path | Repo source | Live copy | Responsibility |
|---|---|---|---|
| `rubric_init.sh` | `skills/codex-judge/hooks/rubric_init.sh` | `~/.claude/hooks/rubric_init.sh` | Gate checks (git repo, `codex` on `PATH`), builds the prompt, invokes `codex exec` in the target repo root, prints the drafted rubric markdown to stdout on success. |
| `rubric-init.prompt.md` | `skills/codex-judge/rubric-init.prompt.md` | `~/.claude/judge/rubric-init.prompt.md` | Prompt template: fixed section headers (Correctness/Security/Tests/Scope/Reject on sight), instructs Codex to explore the repo's stack/conventions and fill in stack-specific bullets. |
| `example-rubric.md` | `skills/codex-judge/example-rubric.md` | `~/.claude/judge/example-rubric.md` | Frozen copy of `claude-agents/.judge/rubric.md`, taken at authoring time and bundled alongside the prompt template. Substituted into `{{example_rubric}}` as a fixed style reference — never read live from the claude-agents repo, so `/judge-init` has no cross-repo or single-machine path dependency. |
| `judge-init.md` | `skills/codex-judge/commands/judge-init.md` | `~/.claude/commands/judge-init.md` | Slash command: run the script, show the draft, warn + confirm before overwrite if `.judge/rubric.md` already exists, write via Claude's own Write tool. |

`rubric_init.sh` never writes `.judge/rubric.md` itself — the overwrite check
and the file write both happen on the Claude side, so the drafted content is
always visible to the user before it lands on disk, and a hand-tuned rubric
is never silently clobbered.

## Prompt contract

`rubric-init.prompt.md` generates content, not a verdict — no JSON, unlike
`prompt.default.md`:

```
You are drafting a code-review rubric for the repo at the current working
directory. Explore it (manifests, lint/test config, CI, existing code) to
determine its stack and conventions.

Output ONLY the contents of .judge/rubric.md — a markdown document, no
fences, no prose before or after. Use exactly these five top-level sections,
in this order: Correctness, Security, Tests, Scope, Reject on sight. Fill
each with concrete, stack-specific bullets (not generic advice) based on
what you find in the repo. Keep it under 60 lines.

STYLE EXAMPLE (a rubric for a different, Python-based repo — match this
level of concreteness, not its content):
{{example_rubric}}
```

`rubric_init.sh` substitutes `{{example_rubric}}` from the bundled
`example-rubric.md` file (see Components), using the same whole-line
placeholder technique `judge.sh` already uses for `{{rubric}}`/`{{diff}}` —
immune to the substituted content containing shell or `{{`-like metacharacters.
No `{{diff}}` placeholder is needed here.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Rubric authorship | Codex, via `codex exec` | Restores the original design's cross-family intent — Claude never authors the criteria its own diffs are graded against — which the actual `claude-agents` rubric violated in practice. |
| Write flow | Script drafts to stdout only; Claude presents and writes | Keeps the script side-effect-free and the draft always visible before disk write, matching how the real `claude-agents` rubric actually got committed (Claude wrote it, normal review/commit flow). |
| Rubric shape | Fixed 5-section skeleton (Correctness/Security/Tests/Scope/Reject on sight) across all repos, stack-specific bullets underneath | Keeps every repo's rubric predictable and comparable across the fleet; the judge prompt/parsing logic never has to special-case section names. |
| Existing-rubric handling | Always draft fresh from repo exploration; Claude warns + confirms before overwrite if `.judge/rubric.md` exists | Simplest single code path. A revise/refresh mode that feeds the old rubric back to Codex is deferred (see Out of scope). |
| Script structure | New standalone `rubric_init.sh`, not a mode on `judge.sh` | Keeps the already-shipped, tested `judge.sh` untouched; ~20-30 lines of codex-invocation boilerplate duplicated is cheaper than refactoring working code into a shared lib for one new caller. |
| Failure policy | Fail-loud: every gate exits nonzero with a clear message | Unlike the Stop hook, there's no in-flight session to protect — a failed draft just means "fix the problem and try again." |
| Rollout | Ship to both the repo-tracked plugin source (`skills/codex-judge/`) and live `~/.claude/{hooks,judge,commands}/` copies | Mirrors how `/judge` itself is actually installed and invoked today (settings.json and `commands/judge.md` point at the live `~/.claude/hooks/judge.sh`, not the plugin cache) — without the live copies, `/judge-init` wouldn't run until a plugin update cycle. |

## Known drift (out of scope for this change)

The live `~/.claude/hooks/judge.sh` and the plugin-packaged
`skills/codex-judge/hooks/judge.sh` have already diverged: the live copy
hardcodes `JUDGE_HOME="${HOME}/.claude/judge"`, while the plugin copy resolves
it portably via `${CLAUDE_PLUGIN_ROOT}` (with a fallback for direct invocation).
`/judge-init`'s new files are added to both locations as-is, matching each
location's existing convention; reconciling the two `judge.sh` copies is a
separate concern and is not addressed here.

## Edge cases

- Not a git repo → exit 1, "Not inside a git repository."
- `codex` not on `PATH` → exit 1, "codex CLI not on PATH — install/auth it first."
- `codex exec` fails or produces empty last-message output → exit 1, "Codex produced no output — try again."
- Repo has no clear stack signals (e.g. empty repo) → Codex still emits the
  fixed five sections; bullets may be generic. Not treated as an error.
- `.judge/rubric.md` already exists → script behavior is unchanged (it never
  writes the file); Claude warns and confirms before overwriting.

## Testing

1. **Unit sanity (Claude runs):** non-git scratch dir → refuses; git repo
   with `codex` off `PATH` → refuses with a clear message.
2. **Skeleton consistency (Claude runs):** run against two different scratch
   repos (e.g. a Python one, a Terraform one) → confirm both drafts carry the
   same five section headers with stack-appropriate bullets underneath.
3. **Live end-to-end (user runs):** `/judge-init` in a second real repo →
   review the draft, confirm the overwrite-warning path when a rubric already
   exists, write the file, then confirm `/judge` picks it up on a scratch diff
   there.

## Out of scope (v1)

Revise/refresh mode that feeds an existing rubric back to Codex for updates,
per-repo prompt overrides for rubric-init itself (no `.judge/rubric-init-prompt.md`
concept), a target-repo path argument (the command always operates on the
current working directory's repo root, consistent with `/judge`), reconciling
the `judge.sh` drift noted above, and auto-committing the generated rubric.
