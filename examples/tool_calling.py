#!/usr/bin/env python3
"""Tool calling example — ask the model to use a fake "Read" tool."""
from ia_web_parser import ClaudeWebProvider, SessionManager

sm = SessionManager()
provider = ClaudeWebProvider(session_manager=sm)

tools = [
    {
        "name": "Read",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                }
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Bash",
        "description": "Execute a shell command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run",
                }
            },
            "required": ["command"],
        },
    },
]

messages = [
    {"role": "user", "content": "Read /etc/hostname and then run uname -a"},
]

for chunk in provider.chat(messages=messages, tool_schemas=tools):
    if hasattr(chunk, "text") and not hasattr(chunk, "tool_calls"):
        print(chunk.text, end="", flush=True)
    elif hasattr(chunk, "tool_calls"):
        print("\n\n=== TOOL CALLS ===")
        for call in chunk.tool_calls:
            print(f"  {call['name']}({call['input']})")

        # In a real agent you would execute the tools here and append results
        # to messages, then call provider.chat() again.
