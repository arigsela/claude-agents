You are drafting a code-review rubric for the repo at the current working
directory. Explore it (manifests, lint/test config, CI, existing code) to
determine its stack and conventions.

Output ONLY the contents of .judge/rubric.md, a markdown document with no
fences and no prose before or after it. Structure it as a single '#' title
line naming the repo, followed by exactly five '##' sections in this order:
Correctness, Security, Tests, Scope, Reject on sight. Fill each section with
concrete, stack-specific bullets, not generic advice, based on what you find
in the repo. Keep the whole document under 60 lines.

STYLE EXAMPLE, a rubric written for a different, Python-based repo. Match
its level of concreteness and structure, not its content:
{{example_rubric}}
