"""
MCPs can be defined programmatically or loaded from an .mcp.json file.

For more details, see: https://docs.claude.com/en/api/agent-sdk/mcp
"""

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from rich import print
from rich.console import Console
from cli_tools import parser, print_rich_message, parse_and_print_message, get_user_input
from dotenv import load_dotenv
load_dotenv()


async def main():
    console = Console()
    args = parser.parse_args()

    
    options = ClaudeAgentOptions(
        model=args.model,
        allowed_tools=[
            'Read',
            'Write',
            'Edit',
            'MultiEdit',
            'Grep',
            'Glob',
            # Notice that you MUST allow MCP tools otherwise they will not be available by default.
            # 'mcp__Playwright__browser_navigate'
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

    print_rich_message(
        "system",
        f"Welcome to your personal assistant, Kaya!\n\nSelected model: {args.model}",
        console
        )

    async with ClaudeSDKClient(options=options) as client:

        while True:
            input_prompt = get_user_input(console)
            if input_prompt == "exit":
                break

            await client.query(input_prompt)

            async for message in client.receive_response():
                # Uncomment to print raw messages for debugging
                # print(message)
                parse_and_print_message(message, console)


if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.run(main())
