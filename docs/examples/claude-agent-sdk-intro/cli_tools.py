"""
CLI tools and convenience functions for working with the Claude Agent SDK in the terminal.
"""

from claude_agent_sdk import (
    AssistantMessage, 
    TextBlock, 
    ResultMessage, 
    ToolUseBlock, 
    ToolResultBlock, 
    ThinkingBlock, 
    UserMessage, 
    Message, 
    SystemMessage
)
from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.console import Console
from rich.prompt import Prompt
from rich.syntax import Syntax
from dotenv import load_dotenv
from typing import Literal
import argparse
import json
load_dotenv()


# --------------------------------
# Parse runtime args from CLI
# --------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--stats", "-s", default="False", help="Print session stats")
parser.add_argument("--model", "-m", default="sonnet", help="Model to use")
parser.add_argument("--output-style", "-os", default="Personal Assistant", help="Output style to use")
parser.add_argument("--print-raw", "-pr", default="False", help="Print raw messages")


# --------------------------------
# Convenience functions for printing messages
# --------------------------------

def print_rich_message(
        type: Literal["user", "assistant", "tool_use", "tool_result", "system"],
        message: str,
        console: Console
        ):
    """
    Prints a message in a panel with a title and border color based on the message type.
    """
    styles = {
        "user": {
            "message_style": "bold yellow",
            "panel_title": "User Prompt",
            "border_style": "yellow"
            },
        "assistant": {
            "message_style": "bold green",
            "panel_title": "Assistant",
            "border_style": "green"
            },
        "tool_use": {
            "message_style": "bold blue",
            "panel_title": "Tool Use",
            "border_style": "blue"
            },
        "tool_result": {
            "message_style": "bold magenta",
            "panel_title": "Tool Result",
            "border_style": "magenta"
            },
        "system": {
            "message_style": "bold cyan",
            "panel_title": "System Message",
            "border_style": "cyan"}
    }

    # For tool results, try to apply JSON syntax highlighting
    if type == "tool_result" and is_json_string(message):
        panel_content = Syntax(message, "json", theme="monokai", line_numbers=False)
    else:
        panel_content = Text(message, style=styles[type]["message_style"])

    if type == "system":
        panel=Panel.fit(
            panel_content,
            title=styles[type]["panel_title"],
            border_style=styles[type]["border_style"]
            )
    else:
        panel=Panel(
            panel_content,
            title=styles[type]["panel_title"],
            border_style=styles[type]["border_style"]
            )
    console.print(panel, end="\n\n")


def is_json_string(text: str) -> bool:
    """Check if a string is valid JSON"""
    try:
        json.loads(text)
        return True
    except json.JSONDecodeError:
        return False


def format_tool_result(content) -> str:
    """
    Format tool result content nicely, handling nested JSON strings.
    """
    if isinstance(content, str):
        # Try to parse as JSON and format it
        try:
            parsed = json.loads(content)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            return content
    elif isinstance(content, list):
        # Handle list of content blocks (common format)
        formatted_parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                # Try to parse the text field as JSON
                text_content = item["text"]
                try:
                    parsed_json = json.loads(text_content)
                    formatted_json = json.dumps(parsed_json, indent=2)
                    formatted_parts.append(formatted_json)
                except json.JSONDecodeError:
                    # If not JSON, just use the text as-is
                    formatted_parts.append(text_content)
            else:
                # For other dict structures, format as JSON
                formatted_parts.append(json.dumps(item, indent=2))
        return "\n\n".join(formatted_parts)
    else:
        # For other types, convert to JSON
        return json.dumps(content, indent=2)


def get_user_input(console: Console) -> str:
    """
    Get user input and display it in a rich panel in one step.
    Returns the user input string.
    """
    user_input = Prompt.ask("\n[bold yellow]You[/bold yellow]", console=console)
    print()
    return user_input


def parse_and_print_message(
        message: Message, 
        console: Console,
        print_stats: bool = False
        ):
    """
    Parse and print a message based on its type and content.
    """
    # Assistant messages include TextBlock, ToolUseBlock, ThinkingBlock, and ToolResultBlock
    # https://docs.claude.com/en/api/agent-sdk/python#content-block-types
    if isinstance(message, SystemMessage):
        if message.subtype == "compact_boundary":
            print_rich_message(
                "system", 
                f"Compaction completed \nPre-compaction tokens: {message.data["compact_metadata"]["pre_tokens"]} \nTrigger: {message.data["compact_metadata"]["trigger"]}",
                console
                )
        else:
            print_rich_message("system", json.dumps(message.data, indent=2), console)
    elif isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print_rich_message("assistant", block.text, console)
            elif isinstance(block, ToolUseBlock):
                print_rich_message("tool_use", f"Tool: <{block.name}> \n\n {block.input}", console)
            elif isinstance(block, ThinkingBlock):
                print_rich_message("assistant", "Thinking...", console)
    elif isinstance(message, UserMessage):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                formatted_content = format_tool_result(block.content)
                print_rich_message("tool_result", formatted_content, console)
    elif isinstance(message, ResultMessage):
        
        if print_stats:
            result = message.subtype
            session_id = message.session_id
            duration_s = message.duration_ms/1000
            cost_usd = message.total_cost_usd
            input_tokens = message.usage["input_tokens"]
            output_tokens = message.usage["output_tokens"]

            session_stats = {
                "Session ID": session_id,
                "Result": result,
                "Duration (s)": f"{duration_s:.2f}",
                "Cost (USD)": f"${cost_usd:.2f}" if cost_usd else "N/A",
                "Input Tokens": input_tokens,
                "Output Tokens": output_tokens
            }

            if session_stats:
                stats_table = Table(
                    title="Session Stats",
                    show_header=False,
                    title_style="bold blue"
                )
                stats_table.add_column(style="cyan", no_wrap=True)
                stats_table.add_column(style="yellow")

                for stat_name, stat_value in session_stats.items():
                    stats_table.add_row(stat_name, str(stat_value))

                console.print(stats_table, end="\n")
