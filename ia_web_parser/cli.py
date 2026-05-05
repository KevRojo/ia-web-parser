#!/usr/bin/env python3
"""
ia-web-harvest CLI

Usage:
    ia-web-harvest claude
    ia-web-harvest kimi
    ia-web-harvest gemini
    ia-web-harvest deepseek
    ia-web-harvest qwen
"""
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: ia-web-harvest <provider>")
        print("Providers: claude, kimi, gemini, deepseek, qwen")
        sys.exit(1)

    provider = sys.argv[1].lower()
    from ia_web_parser import SessionManager

    sm = SessionManager()

    try:
        if provider == "claude":
            from ia_web_parser import ClaudeHarvester
            ClaudeHarvester(sm).harvest()
        elif provider == "kimi":
            from ia_web_parser import KimiHarvester
            KimiHarvester(sm).harvest()
        elif provider == "gemini":
            from ia_web_parser import GeminiHarvester
            GeminiHarvester(sm).harvest()
        elif provider == "deepseek":
            from ia_web_parser import DeepSeekHarvester
            DeepSeekHarvester(sm).harvest()
        elif provider == "qwen":
            from ia_web_parser import QwenHarvester
            QwenHarvester(sm).harvest()
        else:
            print(f"Unknown provider: {provider}")
            sys.exit(1)
    except Exception as e:
        print(f"Harvest failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
