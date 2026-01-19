# Prompt Engineering Patterns

Master advanced prompt engineering techniques to maximize LLM performance, reliability, and controllability in production. Use when optimizing prompts, improving LLM outputs, or designing production prompt templates.

## Installation

```bash
# From this repository
claude skill add ./skills/prompt-engineering-patterns

# Manual installation
cp -r skills/prompt-engineering-patterns ~/.claude/skills/
```

## Documentation

See [SKILL.md](./SKILL.md) for full skill instructions and usage.

## Files

- `SKILL.md` - Claude Code skill definition
- `references/` - Extended documentation
  - `few-shot-learning.md` - Example selection strategies
  - `chain-of-thought.md` - Reasoning elicitation techniques
  - `prompt-optimization.md` - Systematic refinement workflows
  - `prompt-templates.md` - Reusable template patterns
  - `system-prompts.md` - System-level prompt design
- `assets/` - Templates and examples
  - `prompt-template-library.md` - Battle-tested prompt templates
  - `few-shot-examples.json` - Curated example datasets
- `scripts/` - Utility scripts
  - `optimize-prompt.py` - Automated prompt optimization tool
