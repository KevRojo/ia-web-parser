"""
ia-web-parser

Turn any AI web-chat provider into a tool-capable streaming API.

Example:
    from ia_web_parser import WebProvider, WebToolParser
    
    provider = WebProvider.from_harvest_file("claude", "~/.ia-web-parser/claude.json")
    for chunk in provider.chat("Say hello"):
        print(chunk.text, end="")
"""
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.types import TextChunk, ToolCall, AssistantTurn, ProviderError
from ia_web_parser.session import SessionManager
from ia_web_parser.providers.claude import ClaudeWebProvider
from ia_web_parser.providers.kimi import KimiWebProvider
from ia_web_parser.providers.gemini import GeminiWebProvider
from ia_web_parser.providers.deepseek import DeepSeekWebProvider
from ia_web_parser.providers.qwen import QwenWebProvider
from ia_web_parser.harvester.claude import ClaudeHarvester
from ia_web_parser.harvester.kimi import KimiHarvester
from ia_web_parser.harvester.gemini import GeminiHarvester
from ia_web_parser.harvester.deepseek import DeepSeekHarvester
from ia_web_parser.harvester.qwen import QwenHarvester

__version__ = "0.1.0"
__all__ = [
    "WebToolParser",
    "TextChunk",
    "ToolCall",
    "AssistantTurn",
    "ProviderError",
    "SessionManager",
    "ClaudeWebProvider",
    "KimiWebProvider",
    "GeminiWebProvider",
    "DeepSeekWebProvider",
    "QwenWebProvider",
    "ClaudeHarvester",
    "KimiHarvester",
    "GeminiHarvester",
    "DeepSeekHarvester",
    "QwenHarvester",
]
