#!/usr/bin/env python3
"""Harvest all supported providers in one shot."""
from ia_web_parser import (
    SessionManager,
    ClaudeHarvester,
    KimiHarvester,
    GeminiHarvester,
    DeepSeekHarvester,
    QwenHarvester,
)

sm = SessionManager()

harvesters = [
    ("Claude", ClaudeHarvester),
    ("Kimi", KimiHarvester),
    ("Gemini", GeminiHarvester),
    ("DeepSeek", DeepSeekHarvester),
    ("Qwen", QwenHarvester),
]

for name, cls in harvesters:
    print(f"\n{'='*40}")
    print(f"Harvesting {name}...")
    print(f"{'='*40}")
    try:
        cls(sm).harvest()
    except Exception as e:
        print(f"[ERROR] {name} harvest failed: {e}")

print("\nAll harvesters finished. Auth files saved to ~/.ia-web-parser/")
