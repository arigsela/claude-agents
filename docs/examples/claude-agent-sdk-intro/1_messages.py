"""
Example of how to parse and print messages from the SDK.

To simplify this file I've imported some helper functions from cli_tools.py. This separates printing/logging functions from the main application logic, making it easier to see what's going on.
"""

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from rich import print
from rich.console import Console
from cli_tools import print_rich_message, parse_and_print_message
from dotenv import load_dotenv
load_dotenv()


MODEL = "haiku"


async def main():
    # Initialize the console we'll use for this session
    console = Console()

    options = ClaudeAgentOptions(
        model=MODEL
    )

    # Startup message
    print_rich_message(
        type="system", 
        message=f"Welcome to your Claude Personal Assistant!\n\nSelected model: {MODEL}",
        console=console
    )

    async with ClaudeSDKClient(options=options) as client:

        input_prompt = "Hi"
        print_rich_message("user", input_prompt, console)

        await client.query(input_prompt)

        async for message in client.receive_response():
            # Uncomment to print raw messages for debugging
            # print(message)
            parse_and_print_message(message, console)


if __name__ == "__main__":
    import asyncio
    # This is needed to run asyncio in a Jupyter notebook/interactive environment
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.run(main())
