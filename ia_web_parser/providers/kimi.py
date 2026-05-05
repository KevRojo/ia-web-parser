"""Kimi.com web provider."""
import json
import struct
import urllib.request
from typing import Generator
from pathlib import Path

from ia_web_parser.core.types import TextChunk, AssistantTurn
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.history import format_web_tool_manifest, consolidate_web_history
from ia_web_parser.session import SessionManager


class KimiWebProvider:
    """Stream completions from kimi.com consumer web using harvested gRPC-Web tokens.

    The harvested auth file contains cookies, headers, the gRPC URL, and the
    last payload template (including ``chat_id`` and ``parent_id``).
    """

    def __init__(self, auth_file: str | None = None, session_manager: SessionManager | None = None):
        self.sm = session_manager or SessionManager()
        self.auth_path = Path(auth_file) if auth_file else self.sm.auth_path("kimi", "kimi_consumer.json")
        self._config = self.sm.load_state("kimi")

    def _load_auth(self) -> dict:
        if not self.auth_path.exists():
            raise FileNotFoundError(f"Auth file not found: {self.auth_path} -> run harvester first")
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def chat(
        self,
        messages: list[dict],
        model: str = "kimi-latest",
        system: str = "",
        tool_schemas: list[dict] | None = None,
    ) -> Generator:
        tool_schemas = tool_schemas or []
        auth_data = self._load_auth()

        cookies = []
        for c in auth_data.get("cookies", []):
            cookies.append(f"{c['name']}={c['value']}")

        headers = auth_data.get("headers", {}).copy()
        headers["Cookie"] = "; ".join(cookies)
        headers["Content-Type"] = "application/connect+json"

        last_payload = auth_data.get("last_payload", {})
        harvested_chat_id = last_payload.get("chat_id")
        chat_id = self._config.get("kimi_web_chat_id") or harvested_chat_id

        harvested_parent_id = last_payload.get("message", {}).get("parent_id")
        config_parent_id = self._config.get("kimi_web_parent_id")
        config_chat_id = self._config.get("kimi_web_chat_id")
        if config_parent_id and config_chat_id == harvested_chat_id:
            parent_id = config_parent_id
        elif harvested_parent_id:
            parent_id = harvested_parent_id
        else:
            parent_id = None

        manifest = format_web_tool_manifest(tool_schemas, messages)
        last_user_msg = consolidate_web_history(messages, manifest)

        payload = last_payload.copy()
        payload["chat_id"] = chat_id
        payload["message"] = {
            "parent_id": parent_id,
            "role": "user",
            "blocks": [{"message_id": "", "text": {"content": last_user_msg}}],
            "scenario": last_payload.get("message", {}).get("scenario", "SCENARIO_K2D5"),
        }

        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header_frame = struct.pack(">B I", 0, len(payload_bytes))
        data_to_send = header_frame + payload_bytes

        url = auth_data.get("url")
        req = urllib.request.Request(url, data=data_to_send, headers=headers, method="POST")

        text = ""
        raw_content = ""
        parser = WebToolParser(auto_wrap_json=True)

        for attempt in range(2):
            if attempt == 1:
                self._config.pop("kimi_web_chat_id", None)
                self._config.pop("kimi_web_parent_id", None)
                yield TextChunk("[kimi-web] Empty response — retrying with fresh thread...\n")
                payload["chat_id"] = None
                payload["message"]["parent_id"] = None
                payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                header_frame = struct.pack(">B I", 0, len(payload_bytes))
                data_to_send = header_frame + payload_bytes
                req = urllib.request.Request(url, data=data_to_send, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    while True:
                        h_bytes = resp.read(5)
                        if not h_bytes or len(h_bytes) < 5:
                            break
                        flags, length = struct.unpack(">B I", h_bytes)
                        body = resp.read(length)
                        if not body:
                            break

                        try:
                            data = json.loads(body.decode("utf-8", errors="ignore"))

                            if data.get("op") == "set":
                                if data.get("mask") == "chat":
                                    self._config["kimi_web_chat_id"] = data.get("chat", {}).get("id")
                                elif data.get("mask") == "message":
                                    msg_info = data.get("message", {})
                                    if msg_info.get("role") == "user":
                                        if not self._config.get("kimi_web_parent_id"):
                                            self._config["kimi_web_parent_id"] = msg_info.get("id")
                                    elif msg_info.get("role") == "assistant":
                                        self._config["kimi_web_parent_id"] = msg_info.get("id")

                            content = ""
                            if data.get("op") == "set" and data.get("mask") == "block.text":
                                content = data.get("block", {}).get("text", {}).get("content", "")
                            elif data.get("op") == "append" and data.get("mask") == "block.text.content":
                                content = data.get("block", {}).get("text", {}).get("content", "")

                            if content:
                                raw_content += content
                        except Exception:
                            continue

                if raw_content or parser.tool_calls:
                    break

            except Exception as e:
                if attempt == 0:
                    continue
                msg = f"[kimi-web] Error: {e}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                self.sm.save_state("kimi", self._config)
                return

        if raw_content:
            text = parser.parse_chunk(raw_content)
            text += parser.flush()
            if text:
                yield TextChunk(text)

        self.sm.save_state("kimi", self._config)
        yield AssistantTurn(text, parser.tool_calls, 0, 0)
