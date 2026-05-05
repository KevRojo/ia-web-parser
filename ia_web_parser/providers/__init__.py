"""Provider streamers for ia-web-parser."""
from ia_web_parser.providers.claude import ClaudeWebProvider
from ia_web_parser.providers.kimi import KimiWebProvider
from ia_web_parser.providers.gemini import GeminiWebProvider
from ia_web_parser.providers.deepseek import DeepSeekWebProvider
from ia_web_parser.providers.qwen import QwenWebProvider

__all__ = [
    "ClaudeWebProvider",
    "KimiWebProvider",
    "GeminiWebProvider",
    "DeepSeekWebProvider",
    "QwenWebProvider",
]
