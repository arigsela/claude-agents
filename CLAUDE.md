# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains educational materials and examples for the **Claude Agent SDK**, a Python framework for building custom AI agent systems. The primary focus is a step-by-step tutorial located in `docs/examples/claude-agent-sdk-intro/`.

## Key Technologies

- **Python 3.13+** - Primary language
- **Claude Agent SDK** - Core framework for building AI agents
- **uv** - Python package manager (preferred over pip)
- **Rich** - CLI formatting and display
- **asyncio & nest_asyncio** - Asynchronous operations
- **MCP (Model Context Protocol)** - External tool integration
- **Playwright MCP** - Browser automation (requires Node.js and Chrome)

## Package Management

**ALWAYS use `uv` for Python package management, never `pip`.**

Common commands:
```bash
# Install dependencies and create virtual environment
uv sync

# Run a Python script
uv run <script.py>

# Run scripts with model selection
uv run <script.py> --model claude-sonnet-4-20250514

# Run with stats output
uv run <script.py> --stats True
```

## Project Structure

```
claude-agents/
└── docs/
    └── examples/
        └── claude-agent-sdk-intro/
            ├── 0_querying.py          # Basic query() vs ClaudeSDKClient patterns
            ├── 1_messages.py          # Message parsing and Rich CLI display
            ├── 2_tools.py             # Custom tool creation with MCP
            ├── 3_options.py           # ClaudeAgentOptions configuration
            ├── 4_convo_loop.py        # Continuous conversation loops
            ├── 5_mcp.py               # MCP integration (Playwright)
            ├── 6_subagents.py         # Multi-agent systems with subagents
            ├── cli_tools.py           # CLI utilities and message formatting
            ├── db/products.json       # Sample data for custom tools
            ├── .claude/               # Claude Code configuration
            │   ├── settings.json      # Output styles and hooks
            │   ├── hooks/             # Custom hook scripts
            │   ├── agents/            # Agent definitions
            │   └── commands/          # Slash commands
            └── docs/                  # Module documentation
```

## Core Architecture

### Claude Agent SDK Concepts

1. **Query Methods**:
   - `query()` - One-off tasks, new session each time
   - `ClaudeSDKClient` - Continuous conversations, stateful sessions

2. **Message Types** (from `claude_agent_sdk`):
   - `AssistantMessage` - Contains `TextBlock`, `ToolUseBlock`, `ThinkingBlock`
   - `UserMessage` - Contains `ToolResultBlock`
   - `SystemMessage` - System notifications (e.g., compaction events)
   - `ResultMessage` - Session statistics and metadata

3. **Agent Options** (`ClaudeAgentOptions`):
   - `model` - Model selection (haiku/sonnet/opus)
   - `allowed_tools` - Whitelist of permitted tools
   - `disallowed_tools` - Blacklist of forbidden tools
   - `permission_mode` - Control approval flow ("default", "acceptEdits", etc.)
   - `system_prompt` - Custom system instructions
   - `mcp_servers` - External MCP server configuration
   - `agents` - Subagent definitions (`AgentDefinition`)
   - `setting_sources` - Load settings from ["project", "global"]

4. **Custom Tools**:
   - Use `@tool` decorator to define functions
   - Create MCP server with `create_sdk_mcp_server()`
   - Add to `mcp_servers` in agent options
   - Tool naming convention: `mcp__<server_name>__<tool_name>`

5. **Subagents**:
   - Defined via `AgentDefinition` in `ClaudeAgentOptions.agents`
   - Require `Task` tool in parent agent's `allowed_tools`
   - Have isolated context and tool permissions
   - Can run in parallel for complex workflows
   - Examples: `youtube-analyst`, `researcher`

### Claude Code Configuration

The `.claude/` directory contains project-specific configuration:

- **settings.json**: Output styles, hooks, and preferences
- **hooks/**: Python scripts triggered on events (Stop, Notification, etc.)
- **agents/**: Specialized agent definitions
- **commands/**: Custom slash commands

Hooks use JSON payload with `transcript_path` and `session_id` from stdin.

## Common Development Commands

### Running Modules

```bash
# Basic modules (0-2) have hardcoded models
python 0_querying.py
python 1_messages.py
python 2_tools.py

# Advanced modules (3-6) accept --model flag
python 3_options.py --model sonnet
python 4_convo_loop.py --model claude-sonnet-4-20250514
python 5_mcp.py --model opus
python 6_subagents.py --model claude-opus-4-20250514

# Show session statistics
python <module>.py --stats True
```

### Testing and Debugging

```bash
# Print raw messages for debugging
# Uncomment `print(message)` in the script's receive_response() loop

# View agent action logs
cat logs/<timestamp>_<session_id>.log
```

### MCP Prerequisites (Modules 5-6)

```bash
# Ensure Node.js and Chrome are installed
node --version
which chrome  # or 'where chrome' on Windows

# Test Playwright MCP manually
npx -y @playwright/mcp@latest
```

## Important Patterns

### Message Parsing

The `cli_tools.py` module provides standardized message parsing:

```python
from cli_tools import parse_and_print_message, print_rich_message

# Parse and display messages with Rich formatting
parse_and_print_message(message, console, print_stats=True)

# Print custom messages with type-based styling
print_rich_message("user", "Hello", console)
print_rich_message("assistant", "Response", console)
```

### Async Context Management

Always use context managers for `ClaudeSDKClient`:

```python
async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    async for message in client.receive_response():
        # Process messages
```

### Tool Result Formatting

Tool results may contain nested JSON. Use `format_tool_result()` from `cli_tools.py` to handle this properly.

### Conversation Loops

Use `while True` with exit condition for continuous conversations:

```python
while True:
    input_prompt = get_user_input(console)
    if input_prompt == "exit":
        break
    await client.query(input_prompt)
    # ... process responses
```

## Agent Configuration Examples

### Minimal Configuration

```python
options = ClaudeAgentOptions(model="haiku")
```

### Custom Tools Configuration

```python
options = ClaudeAgentOptions(
    model="sonnet",
    mcp_servers={"products": products_server},
    allowed_tools=["Read", "Write", "mcp__products__search_products"]
)
```

### Subagent Configuration

```python
options = ClaudeAgentOptions(
    model="sonnet",
    allowed_tools=["Task", "Read", "Write", "WebSearch"],
    agents={
        "researcher": AgentDefinition(
            description="Expert researcher and documentation writer",
            prompt="You are an expert researcher...",
            model="sonnet",
            tools=["Read", "Write", "WebSearch", "WebFetch"]
        )
    }
)
```

## Environment Variables

Create a `.env` file for API configuration (optional if using Claude Code authentication):

```
ANTHROPIC_API_KEY=your_api_key_here
```

## Platform-Specific Notes

### macOS
- Default sound commands use `afplay` with system sounds
- Paths like `/System/Library/Sounds/Funk.aiff` work out of the box

### Linux
- Replace `afplay` with `aplay`, `paplay`, or `play` (sox)
- Update sound file paths in `.claude/settings.json`

### Windows
- Use PowerShell for sound: `powershell -c (New-Object Media.SoundPlayer "C:\Windows\Media\notify.wav").PlaySync()`
- Or remove sound commands entirely

## Troubleshooting

### Import Errors
- Ensure `uv sync` has been run
- Virtual environment must be active (or use `uv run`)

### MCP Connection Failures
- Verify Node.js and Chrome are installed (for Playwright)
- Check internet connection for first-time package downloads
- Test MCP command manually: `npx -y @playwright/mcp@latest`

### Hook Execution Errors
- Update file paths in `.claude/settings.json` to match your system
- Ensure hook scripts have proper permissions
- Use absolute paths or `uv run` for Python hooks

## Documentation Resources

- [Claude Agent SDK Python Docs](https://docs.claude.com/en/api/agent-sdk/python)
- [MCP Servers Directory](https://github.com/modelcontextprotocol/servers)
- [Anthropic API Docs](https://docs.anthropic.com)
- Module-specific documentation in `docs/examples/claude-agent-sdk-intro/docs/`

## Development Philosophy

This is an educational codebase focused on progressive learning:
1. Start with basics (query patterns, message handling)
2. Build up to tools (custom MCP tools)
3. Add configuration (agent options)
4. Implement conversation loops
5. Integrate external tools (MCP servers)
6. Create multi-agent systems (subagents)

Each module is self-contained and can be run independently.
