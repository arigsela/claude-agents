# Module 5: Model Context Protocol (MCP)

> [!IMPORTANT] 
> Created by RAIA!

## Overview

This module demonstrates how to integrate **Model Context Protocol (MCP) servers** with Claude Agent SDK. MCP allows Claude to interact with external tools and services, dramatically expanding its capabilities beyond the built-in SDK tools.

In this example, we integrate the Playwright MCP server, which gives Claude the ability to control a web browser, take screenshots, fill forms, and interact with web pages.

## What is MCP?

Model Context Protocol (MCP) is an open protocol that standardizes how AI applications connect to external data sources and tools. Think of it as a universal adapter that lets Claude communicate with various services, databases, APIs, and tools.

**Key benefits:**
- Access to external tools beyond the SDK's built-in capabilities
- Standardized protocol for tool integration
- Community-driven ecosystem of MCP servers
- Easy to add or remove tools as needed

📚 **Learn more:** [Official MCP Documentation](https://docs.claude.com/en/api/agent-sdk/mcp)

## Code Walkthrough

### 1. Configuration with MCP Servers

```python
options = ClaudeAgentOptions(
    model=args.model,
    allowed_tools=[
        'Read',
        'Write',
        'Edit',
        'MultiEdit',
        'Grep',
        'Glob'
    ],
    permission_mode="acceptEdits",
    setting_sources=["project"],
    # Note: Playwright requires Node.js and Chrome to be installed!
    mcp_servers={
        "Playwright": {
            "command": "npx",
            "args": [
                "-y",
                "@playwright/mcp@latest"
            ]
        }
    }
)
```

The `mcp_servers` parameter accepts a dictionary where:
- **Key**: Name of the MCP server (e.g., "Playwright")
- **Value**: Configuration object with:
  - `command`: The executable command to launch the MCP server
  - `args`: List of arguments passed to the command

In this example:
- `npx` runs the Node Package Runner
- `-y` automatically confirms package installation
- `@playwright/mcp@latest` specifies the Playwright MCP package

### 2. Prerequisites for Playwright MCP

⚠️ **Important:** The Playwright MCP server requires:
1. **Node.js** installed on your system
2. **Chrome browser** installed
3. Internet connection (first run downloads Playwright package)

### 3. How It Works

Once configured, the Playwright MCP tools become available to Claude automatically:

1. SDK initializes connection to the MCP server
2. MCP server exposes its tools to Claude
3. Claude can now call Playwright tools like:
   - `browser_navigate` - Navigate to URLs
   - `browser_snapshot` - Capture page accessibility snapshots
   - `browser_click` - Click elements
   - `browser_type` - Fill in forms
   - `browser_take_screenshot` - Take screenshots
   - And many more!

The rest of the code follows the same pattern as previous modules - query/response loop with the SDK client.

## Available MCP Servers

Here are some popular MCP servers you can integrate:

| MCP Server | Description | Use Cases |
|------------|-------------|-----------|
| **Playwright** | Browser automation | Web scraping, testing, screenshots |
| **Filesystem** | File operations | Enhanced file management |
| **GitHub** | GitHub API access | Repository management, issue tracking |
| **PostgreSQL** | Database access | Query databases, manage data |
| **Google Drive** | Drive integration | Access documents, sheets |
| **Brave Search** | Web search | Research, fact-checking |

📚 **Explore more:** [MCP Servers Directory](https://github.com/modelcontextprotocol/servers)

## Running the Module

```bash
python 5_mcp.py --model claude-sonnet-4-20250514
```

### Example Interactions

Try these prompts to see MCP in action:

1. **Web Navigation:**
   ```
   Go to anthropic.com and take a screenshot
   ```

2. **Web Research:**
   ```
   Visit wikipedia.org and search for "Model Context Protocol"
   ```

3. **Form Interaction:**
   ```
   Navigate to example.com/contact and show me the form fields
   ```

## Key Differences from Previous Modules

| Aspect | Previous Modules | This Module |
|--------|-----------------|-------------|
| Tools | Built-in SDK tools only | SDK tools + MCP tools |
| Capabilities | File operations, code editing | + Browser control, web interaction |
| Configuration | Simple tool list | Requires MCP server config |
| Dependencies | Python packages only | + Node.js, Chrome |

## Adding Your Own MCP Server

To add another MCP server:

1. Find the MCP server you want (e.g., from the MCP servers directory)
2. Add it to the `mcp_servers` dictionary:

```python
mcp_servers={
    "Playwright": {
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"]
    },
    "GitHub": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"]
    }
}
```

3. Ensure any prerequisites (API keys, installations) are met
4. Run your agent - the new tools will be automatically available!

## Troubleshooting

### Common Issues

**Error: "Cannot find npx"**
- Solution: Install Node.js from [nodejs.org](https://nodejs.org)

**Error: "Browser not installed"**
- Solution: Install Chrome browser

**MCP server connection fails**
- Check your internet connection
- Verify the MCP package name is correct
- Check console logs for detailed error messages

**Tools not appearing**
- Ensure the MCP server started successfully (check console output)
- Verify the command and args are correct
- Try running the npx command manually to test

## Additional Resources

- 📖 [Claude Agent SDK - MCP Integration](https://docs.claude.com/en/api/agent-sdk/mcp)
- 🛠️ [MCP Server Registry](https://github.com/modelcontextprotocol/servers)
- 🌐 [Playwright MCP Documentation](https://www.npmjs.com/package/@playwright/mcp)
- 📚 [Building Custom MCP Servers](https://modelcontextprotocol.io/docs/building-mcp-servers)
- 🎯 [Agent SDK Python Reference](https://docs.claude.com/en/api/agent-sdk/python)

## Next Steps

After mastering MCP integration, you can:

1. **Combine multiple MCP servers** for complex workflows
2. **Build custom MCP servers** for your specific needs
3. **Chain tool calls** across different MCP servers
4. **Explore the MCP ecosystem** for specialized tools

---

💡 **Pro Tip:** Start with one MCP server and understand how it works before adding multiple servers. This makes debugging much easier!
