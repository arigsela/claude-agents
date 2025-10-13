"""
Subagents are a way to delegate tasks to specialized agents.

Advantages include:
- Context isolation: Subagents have their own context and do not share it with the main agent.
- Tool isolation: Subagents can have their own set of allowed tools, which can be useful for security and manageability.
- Parallelization: Subagents can run in parallel, which can improve performance.

For more details, see: https://docs.claude.com/en/api/agent-sdk/subagents
"""

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AgentDefinition
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
        permission_mode="acceptEdits",
        setting_sources=["project"],
        allowed_tools=[
            'Read',
            'Write',
            'Edit',
            'MultiEdit',
            'Grep',
            'Glob',
            # Task tool is required to use subagents!
            'Task',
            'TodoWrite',
            'WebSearch',
            'WebFetch',
            'mcp__Playwright__browser_close',
            'mcp__Playwright__browser_resize',
            'mcp__Playwright__browser_console_messages',
            'mcp__Playwright__browser_handle_dialog',
            'mcp__Playwright__browser_evaluate',
            'mcp__Playwright__browser_file_upload',
            'mcp__Playwright__browser_fill_form',
            'mcp__Playwright__browser_install',
            'mcp__Playwright__browser_press_key',
            'mcp__Playwright__browser_type',
            'mcp__Playwright__browser_navigate',
            'mcp__Playwright__browser_navigate_back',
            'mcp__Playwright__browser_network_requests',
            'mcp__Playwright__browser_take_screenshot',
            'mcp__Playwright__browser_snapshot',
            'mcp__Playwright__browser_click',
            'mcp__Playwright__browser_drag',
            'mcp__Playwright__browser_hover',
            'mcp__Playwright__browser_select_option',
            'mcp__Playwright__browser_tabs',
            'mcp__Playwright__browser_wait_for',
        ],
        # We can also specify allowed tools for subagents, by default they inherit all tools including MCP tools.
        agents={
            "youtube-analyst": AgentDefinition(
                description="An expert at analyzing a user's Youtube channel performance. The analyst will produce a markdown report in the /docs directory.",
                prompt="You are an expert at analyzing YouTube data and helping the user understand their performance. You can use the Playwright browser tools to access the user's Youtube Studio. Generate a markdown report in the /docs directory.",
                model="sonnet",
                tools=[
                    'Read',
                    'Write',
                    'Edit',
                    'MultiEdit',
                    'Grep',
                    'Glob',
                    'TodoWrite',
                    'mcp__Playwright__browser_close',
                    'mcp__Playwright__browser_resize',
                    'mcp__Playwright__browser_console_messages',
                    'mcp__Playwright__browser_handle_dialog',
                    'mcp__Playwright__browser_evaluate',
                    'mcp__Playwright__browser_file_upload',
                    'mcp__Playwright__browser_fill_form',
                    'mcp__Playwright__browser_install',
                    'mcp__Playwright__browser_press_key',
                    'mcp__Playwright__browser_type',
                    'mcp__Playwright__browser_navigate',
                    'mcp__Playwright__browser_navigate_back',
                    'mcp__Playwright__browser_network_requests',
                    'mcp__Playwright__browser_take_screenshot',
                    'mcp__Playwright__browser_snapshot',
                    'mcp__Playwright__browser_click',
                    'mcp__Playwright__browser_drag',
                    'mcp__Playwright__browser_hover',
                    'mcp__Playwright__browser_select_option',
                    'mcp__Playwright__browser_tabs',
                    'mcp__Playwright__browser_wait_for',
                ]
            ),
            "researcher": AgentDefinition(
                description="An expert researcher and documentation writer. The agent will perform deep research of a topic and generate a report or documentation in the /docs directory.",
                prompt="You are an expert researcher and report/documentation writer. Use the WebSearch and WebFetch tools to perform research. You can research multiple subtopics/angles to get a holistic understanding of the topic. You can use filesystem tools to track findings and data in the /docs directory. For longer reports, you can break the work into multiple tasks or write sections at a time. But the final output should be a single markdown report. The final report **MUST** include a citations section with links to all sources used. Review the full report, identify any areas for improvement in readability, cohorerence, and relevancy, and make any necessary edits before declaring the task complete. Clean up any extraneous files and only leave the final report in the /docs directory when you are done. You are only permitted to use these specific tools: Read, Write, Edit, MultiEdit, Grep, Glob, TodoWrite, WebSearch, WebFetch. All other tools are prohibited.",
                model="sonnet",
                tools=[
                    'Read',
                    'Write',
                    'Edit',
                    'MultiEdit',
                    'Grep',
                    'Glob',
                    'TodoWrite',
                    'WebSearch',
                    'WebFetch',
                ]
            )
        },
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
