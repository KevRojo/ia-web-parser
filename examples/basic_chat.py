#!/usr/bin/env python3
"""Basic chat example — no tools, just text streaming."""
from ia_web_parser import ClaudeWebProvider, SessionManager

sm = SessionManager()
provider = ClaudeWebProvider(session_manager=sm)

for chunk in provider.chat(
    messages=[{"role": "user", "content": "Explain quantum computing in 3 sentences"}],
):
    if hasattr(chunk, "text") and not hasattr(chunk, "tool_calls"):
        print(chunk.text, end="", flush=True)
    elif hasattr(chunk, "tool_calls"):
        print("\n[Turn finished] Tool calls:", chunk.tool_calls)
