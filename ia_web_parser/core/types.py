"""Core types for ia-web-parser."""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class TextChunk:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict = field(default_factory=dict)


@dataclass
class AssistantTurn:
    text: str
    tool_calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: bool = False


class ProviderError(Exception):
    """Raised when a web provider request fails."""
    pass
