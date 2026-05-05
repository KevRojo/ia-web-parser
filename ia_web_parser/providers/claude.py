"""Claude.ai web provider."""
import json
import time
import random
import requests
from typing import Generator
from pathlib import Path

from ia_web_parser.core.types import TextChunk, AssistantTurn
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.history import format_web_tool_manifest, consolidate_web_history
from ia_web_parser.session import SessionManager


class ClaudeWebProvider:
    """Stream completions from claude.ai using harvested browser cookies.

    Tool calling is prompt-based: the tool manifest is injected into the user
    message; ``<tool_call>...</tool_call>`` tags are parsed from the response.
    Conversation context is maintained server-side via *conversation_id*.
    """

    def __init__(self, auth_file: str | None = None, session_manager: SessionManager | None = None):
        self.sm = session_manager or SessionManager()
        self.auth_path = Path(auth_file) if auth_file else self.sm.auth_path("claude")
        self._config = self.sm.load_state("claude")

    # ── Internal helpers ───────────────────────────────────────────────

    def _load_auth(self) -> dict:
        if not self.auth_path.exists():
            raise FileNotFoundError(f"Cookie file not found: {self.auth_path} -> run harvester first")
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _org_id(self, cookies_data: dict) -> str:
        # 1. Cached state
        if self._config.get("claude_web_org_id"):
            return self._config["claude_web_org_id"]
        # 2. Scan cookies
        for c in cookies_data.get("cookies", []):
            if c.get("name") == "lastActiveOrg" and c.get("value"):
                self._config["claude_web_org_id"] = c["value"]
                return c["value"]
        # 3. Try API
        org_id = self._fetch_org_id(cookies_data)
        if org_id:
            self._config["claude_web_org_id"] = org_id
            return org_id
        # 4. Fallback
        return self._config.get("claude_web_org_id", "")

    def _fetch_org_id(self, cookies_data: dict) -> str | None:
        try:
            s = requests.Session()
            for c in cookies_data.get("cookies", []):
                s.cookies.set(c["name"], c["value"], domain=c.get("domain", "claude.ai"), path=c.get("path", "/"))
            ua = cookies_data.get("user_agent", "Mozilla/5.0")
            s.headers.update({
                "User-Agent": ua,
                "Accept": "application/json",
                "anthropic-client-platform": "web_claude_ai",
                "Origin": "https://claude.ai",
                "Referer": "https://claude.ai/new",
            })
            resp = s.get("https://claude.ai/api/organizations", timeout=10)
            if resp.status_code == 200:
                orgs = resp.json()
                if isinstance(orgs, list) and orgs:
                    return orgs[0].get("uuid") or orgs[0].get("id")
                if isinstance(orgs, dict):
                    return orgs.get("uuid") or orgs.get("id")
        except Exception:
            pass
        return None

    def _create_conversation(self, cookies_data: dict, org_id: str) -> str | None:
        from datetime import datetime as _dt
        try:
            s = requests.Session()
            for c in cookies_data.get("cookies", []):
                s.cookies.set(c["name"], c["value"], domain=c.get("domain", "claude.ai"), path=c.get("path", "/"))
            ua = cookies_data.get("user_agent", "Mozilla/5.0")
            s.headers.update({
                "User-Agent": ua,
                "Accept": "application/json",
                "anthropic-client-platform": "web_claude_ai",
                "Origin": "https://claude.ai",
                "Referer": "https://claude.ai/new",
            })
            url = f"https://claude.ai/api/organizations/{org_id}/chat_conversations"
            resp = s.post(url, json={"name": f"ia-web-parser — {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}"}, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("uuid")
        except Exception:
            pass
        return None

    # ── Public API ─────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        model: str = "claude-sonnet-4-6",
        system: str = "",
        tool_schemas: list[dict] | None = None,
    ) -> Generator:
        """Stream an assistant turn from claude.ai.

        Yields:
            :class:`TextChunk` for each piece of display text.
            Final yield is :class:`AssistantTurn` with ``.tool_calls`` list.
        """
        tool_schemas = tool_schemas or []
        cookies_data = self._load_auth()

        org_id = self._org_id(cookies_data)
        if not org_id:
            msg = "[claude-web] Could not get org ID — cookies may be expired. Run harvester."
            yield TextChunk(msg)
            yield AssistantTurn(msg, [], 0, 0, error=True)
            return

        conv_id = self._config.get("claude_web_conv_id")
        if not conv_id:
            conv_ids = cookies_data.get("conversation_ids", [])
            if conv_ids:
                conv_id = conv_ids[0]
            else:
                conv_id = self._create_conversation(cookies_data, org_id)
            if conv_id:
                self._config["claude_web_conv_id"] = conv_id
            else:
                msg = "[claude-web] Could not get conversation ID. Run harvester."
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                return

        # Build prompt
        manifest = format_web_tool_manifest(tool_schemas, messages)
        prompt = consolidate_web_history(messages, manifest)

        url = f"https://claude.ai/api/organizations/{org_id}/chat_conversations/{conv_id}/completion"
        payload = {
            "prompt": prompt,
            "timezone": "America/Santo_Domingo",
            "model": model,
            "attachments": [],
            "files": [],
            "rendering_mode": "messages",
        }

        session = requests.Session()
        for c in cookies_data.get("cookies", []):
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", "claude.ai"), path=c.get("path", "/"))
        ua = cookies_data.get("user_agent", "Mozilla/5.0")
        session.headers.update({
            "User-Agent": ua,
            "Accept": "text/event-stream",
            "Accept-Language": "en-US,en;q=0.9",
            "anthropic-client-platform": "web_claude_ai",
            "Origin": "https://claude.ai",
            "Referer": f"https://claude.ai/chat/{conv_id}",
        })
        for k, v in cookies_data.get("headers", {}).items():
            if k.lower() not in ("cookie", "host", "content-length", "content-type"):
                session.headers[k] = v

        parser = WebToolParser()
        text = ""

        try:
            resp = session.post(url, json=payload, stream=True, timeout=120)
            if resp.status_code != 200:
                if resp.status_code in (401, 403):
                    msg = f"[claude-web] Auth error {resp.status_code} — cookies expired. Run harvester."
                elif resp.status_code == 404:
                    self._config.pop("claude_web_conv_id", None)
                    msg = "[claude-web] Conversation not found (404). New one will be created next message."
                else:
                    msg = f"[claude-web] HTTP {resp.status_code}: {resp.text[:300]}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                self.sm.save_state("claude", self._config)
                return
        except Exception as e:
            msg = f"[claude-web] Connection error: {e}"
            yield TextChunk(msg)
            yield AssistantTurn(msg, [], 0, 0, error=True)
            self.sm.save_state("claude", self._config)
            return

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line_str = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            line_str = line_str.strip()
            if not line_str or not line_str.startswith("data: "):
                continue
            data_str = line_str[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            completion = data.get("completion", "")
            if not completion:
                evt_type = data.get("type", "")
                if evt_type == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        completion = delta.get("text", "")

            if completion:
                display = parser.parse_chunk(completion)
                if display:
                    text += display
                    yield TextChunk(display)

            stop_reason = data.get("stop_reason")
            if stop_reason and stop_reason != "null":
                break

        remaining = parser.flush()
        if remaining:
            text += remaining
            yield TextChunk(remaining)

        self.sm.save_state("claude", self._config)
        yield AssistantTurn(text, parser.tool_calls, 0, 0)
