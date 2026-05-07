# ia-web-parser

> **Turn any AI web-chat into a tool-capable streaming API.**
> Harvest your existing browser session once. Chat, call tools, parse responses — without an API key.

[![PyPI](https://img.shields.io/pypi/v/ia-web-parser.svg?color=ff6b1f&labelColor=07070a&label=pypi)](https://pypi.org/project/ia-web-parser/)
[![Python](https://img.shields.io/pypi/pyversions/ia-web-parser.svg?color=ff6b1f&labelColor=07070a)](https://pypi.org/project/ia-web-parser/)
[![License](https://img.shields.io/badge/license-MIT-ff6b1f?labelColor=07070a)](LICENSE)

---

## What it does

Most AI providers charge for API access while their **web UIs are free with a subscription you already have**.
`ia-web-parser` bridges that gap. It:

1. **Harvests** your authenticated session via Playwright (you log in once in a real Chrome window).
2. **Streams** chat responses back to your code with the same Bearer/cookie auth the browser uses.
3. **Injects tool manifests** into the prompt and **parses `<tool_call>` blocks** out of the model output, giving you the same tool-calling loop a native API would — but for providers that don't expose one publicly.

Built originally for [**dulus**](https://github.com/KevRojo/dulus) (`pip install dulus`) — the multi-provider AI CLI that pioneered tool-capable web providers — and now extracted as a standalone library so any Python project can use it.

## Supported providers

| Provider | Module | Endpoint |
|---|---|---|
| **Claude** | `claude-web` | claude.ai |
| **Kimi** | `kimi-web` | kimi.com |
| **Gemini** | `gemini-web` | gemini.google.com |
| **DeepSeek** | `deepseek-web` | chat.deepseek.com |
| **Qwen** | `qwen-web` | chat.qwen.ai |

## Install

```bash
pip install ia-web-parser[harvester]
playwright install chromium
```

The `[harvester]` extra pulls Playwright (only needed for the one-time login step).
For pure chat usage after harvesting, `pip install ia-web-parser` is enough.

## Quick start

### 1. Harvest auth (run once per provider)

```python
from ia_web_parser import SessionManager, ClaudeHarvester

sm = SessionManager()
ClaudeHarvester(sm).harvest()
# → opens a real Chrome window. Log in. Cookies + Bearer get stashed
#   to ~/.ia-web-parser/claude.json
```

### 2. Chat with tools

```python
from ia_web_parser import ClaudeWebProvider, SessionManager

sm = SessionManager()
provider = ClaudeWebProvider(session_manager=sm)

tools = [{
    "name": "Read",
    "description": "Read a file from disk",
    "parameters": {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    },
}]

for chunk in provider.chat(
    messages=[{"role": "user", "content": "Read /etc/hosts and summarize"}],
    tool_schemas=tools,
):
    if hasattr(chunk, "text"):
        print(chunk.text, end="", flush=True)
    elif hasattr(chunk, "tool_calls"):
        for call in chunk.tool_calls:
            print(f"\n→ tool call: {call.name}({call.arguments})")
```

That's it. Same shape works for all five providers — swap `ClaudeWebProvider` for `KimiWebProvider`, `GeminiWebProvider`, etc.

## Architecture

```
ia_web_parser/
├── core/        # WebToolParser, history consolidation, manifest formatting
├── harvester/   # Playwright auth harvesters (one persistent profile per provider)
├── providers/   # Streaming chat clients
└── session.py   # Cookie + auth file + state management
```

Auth lives in `~/.ia-web-parser/`.
Persistent Chrome profiles live in `~/.ia-web-parser/profiles/<provider>/`.
Log in once. Re-runs reuse the same profile — never re-authenticate.

## Want the full agent experience?

`ia-web-parser` is the **library**. If you want the **whole CLI** — REPL, slash commands, sub-agents, MemPalace, voice, TTS, Mesa Redonda, 27 built-in tools, MCP, plugins — that's [dulus](https://github.com/KevRojo/dulus):

```bash
pip install dulus-agent
dulus
```

dulus ships `ia-web-parser` integrated, plus 11 cloud APIs (Anthropic, OpenAI, Gemini, NVIDIA's free 14-model tier, Ollama, custom endpoints) and the full agentic loop.

## Why this exists

Web subscriptions you already pay for ($20/mo Claude Pro, $20/mo Gemini Advanced, etc.) give you flagship-model access. APIs charge again per token. `ia-web-parser` lets your scripts use what you've already paid for — programmatically, with tool calls, streaming, and persistent sessions.

It's the same trick `youtube-dl` pulled with video sites: meet the user where their auth already is.

## License

MIT. Fork it, ship it, build whatever.
