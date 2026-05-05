"""History consolidation and tool manifest formatting for web providers.

Web providers (claude.ai, kimi.com, chat.qwen.ai, etc.) take a single prompt
string instead of a structured ``messages`` array.  These helpers flatten an
OpenAI-style conversation into a single prompt and inject the tool manifest.
"""
import json


def format_web_tool_manifest(tool_schemas: list[dict], messages: list[dict]) -> str:
    """Format tools as a prompt hint for web models.

    First turn → full manifest with strong instructions + tool list.
    Continuation turns → empty (the web provider keeps conversation server-side).

    Args:
        tool_schemas: List of JSON Schema dicts with at least ``name`` and
            optionally ``description`` / ``parameters``.
        messages: Full message history (used to detect if this is the first
            user turn).

    Returns:
        Manifest string or empty string when there are no tools or it is a
        continuation turn.
    """
    if not tool_schemas:
        return ""

    is_first_turn = len([m for m in messages if m.get("role") == "user"]) <= 1
    if not is_first_turn:
        return ""

    manifest = [
        "\n\n[TOOL USE — READ CAREFULLY]",
        "You are running inside an agent harness that can EXECUTE tools for you.",
        "When you need information, file contents, or to run an action — DO NOT describe what you would do; CALL the tool.",
        "",
        "EXACT format (any deviation = the call is ignored):",
        '  <tool_call>{"name": "ToolName", "input": {"key": "value"}}</tool_call>',
        "",
        "Rules:",
        "1. The <tool_call> tag MUST be on its own line, with valid JSON inside.",
        "2. Use ONLY tool names from the list below. Do NOT invent tools.",
        "3. To call multiple tools, emit multiple <tool_call> blocks in the SAME response — do not wait for results between them.",
        "4. After tool results come back, you may call more tools or give a final answer.",
        "5. If no tool is needed, just answer normally — no tool_call tag.",
        "",
        "Example (correct):",
        '  <tool_call>{"name": "Read", "input": {"file_path": "/tmp/foo.txt"}}</tool_call>',
        "",
        "Available Tools:",
    ]
    for s in tool_schemas:
        manifest.append(f"- {s['name']}: {s.get('description', '')}")
        props = s.get("parameters", {}).get("properties", {})
        manifest.append(f"  Inputs: {json.dumps(props, separators=(',', ':'))}")

    return "\n".join(manifest)


def consolidate_web_history(messages: list[dict], manifest: str = "") -> str:
    """Consolidate history since last assistant turn into one prompt string.

    This ensures tool results and system notifications are correctly perceived
    by web-based models that take a single prompt string.

    Args:
        messages: OpenAI-style message list (``role``, ``content``).
        manifest: Tool manifest string ( prepended to the prompt when present).

    Returns:
        A single prompt string ready to send to a web provider.
    """
    if not messages:
        return manifest

    # Find last assistant message
    last_ast = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_ast = i
            break

    parts = []
    relevant = messages[last_ast + 1 :] if last_ast != -1 else messages

    for m in relevant:
        role = m.get("role", "user")
        content = m.get("content", "")

        # We only skip empty content if it's NOT a tool result.
        # Tool results must be sent even if empty so the model knows they ran.
        if role != "tool" and not content:
            continue

        header = f"--- [{role.upper()}] ---"
        if role == "tool":
            header = f"--- [Tool Result: {m.get('name', 'Unknown')}] ---"
            if not content:
                content = "(No output / Empty result)"

        parts.append(f"{header}\n{content}")

    prompt = "\n\n".join(parts).strip()
    if manifest:
        prompt = manifest + "\n\n" + prompt

    return prompt.strip()
