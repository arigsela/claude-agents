"""
Basic example of querying with the Claude Agent SDK

Use `query()` for one-off questions, independent tasks, new sessions each time.
Use `ClaudeSDKClient` for continuous conversations and stateful sessions.

For more details, see:
https://docs.claude.com/en/api/agent-sdk/python#choosing-between-query-and-claudesdkclient
"""

from claude_agent_sdk import query, ClaudeSDKClient, ClaudeAgentOptions
from rich import print
from dotenv import load_dotenv
load_dotenv()


MODEL="haiku"


async def main():
    # Use ClaudeAgentOptions to configure the agent's behavior, we'll cover this in more detail later
    # Here we just simply swap to a cheaper model
    options = ClaudeAgentOptions(
        model=MODEL,
    )

    # ----------------------------
    # 1. Example using `query()`
    # ----------------------------

    input_prompt = "Hi"
    print(f"User: {input_prompt}")

    print("Example using `query()`")
    async for message in query(prompt=input_prompt, options=options):
        print(message)

    # ----------------------------
    # 2. Example using `ClaudeSDKClient`
    # ----------------------------

    print(30*"=")
    print("Example using `ClaudeSDKClient`")
    # 2.1 Use context manager to handle connection and disconnection with proper cleanup
    async with ClaudeSDKClient(options=options) as client:

        # 2.2. Send a query
        await client.query(input_prompt)

        # 2.3 Receive messages including ResultMessage
        async for message in client.receive_response():
            # See message types: 
            # https://docs.claude.com/en/api/agent-sdk/python#message-types
            print(message) 

    # Once disconnected, rerunning the query will start a new session and conversation.

if __name__ == "__main__":
    import asyncio
    # This is needed to run asyncio in a Jupyter notebook/interactive environment
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.run(main())