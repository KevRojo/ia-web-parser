"""Qwen web provider."""
import json
import time
import uuid
import requests
from typing import Generator
from pathlib import Path

from ia_web_parser.core.types import TextChunk, AssistantTurn
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.history import format_web_tool_manifest, consolidate_web_history
from ia_web_parser.session import SessionManager


class QwenWebProvider:
    """Stream completions from chat.qwen.ai using harvested browser session."""

    def __init__(self, auth_file: str | None = None, session_manager: SessionManager | None = None):
        self.sm = session_manager or SessionManager()
        self.auth_path = Path(auth_file) if auth_file else self.sm.auth_path("qwen", "qwen_web.json")
        self._config = self.sm.load_state("qwen")

    def _load_auth(self) -> dict:
        if not self.auth_path.exists():
            raise FileNotFoundError(f"Auth file not found: {self.auth_path} -> run harvester first")
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def chat(
        self,
        messages: list[dict],
        model: str = "qwen-latest",
        system: str = "",
        tool_schemas: list[dict] | None = None,
    ) -> Generator:
        tool_schemas = tool_schemas or []
        auth_data = self._load_auth()

        cookies = {c["name"]: c["value"] for c in auth_data.get("cookies", [])}
        if auth_data.get("token") and "token" not in cookies:
            cookies["token"] = auth_data["token"]

        chat_id = (
            self._config.get("chat_id")
            or self._config.get("qwen_web_chat_id")
            or auth_data.get("chat_id")
            or str(uuid.uuid4())
        )
        parent_id = (
            self._config.get("parent_id")
            or self._config.get("qwen_web_parent_id")
            or auth_data.get("parent_id")
        )

        is_first_turn = not parent_id
        if is_first_turn:
            manifest = format_web_tool_manifest(tool_schemas, messages)
            last_user_msg = consolidate_web_history(messages, manifest)
            if system:
                last_user_msg = f"[System]: {system}\n\n{last_user_msg}"
        else:
            last_user_msg = consolidate_web_history(messages, "")

        fid = str(uuid.uuid4())
        next_child_id = str(uuid.uuid4())
        ts = int(time.time())

        internal_model = model
        if "/" in internal_model:
            internal_model = internal_model.split("/", 1)[1]
        if not internal_model or internal_model == "qwen-latest":
            internal_model = auth_data.get("model") or "qwen3.6-plus"

        headers = auth_data.get("headers", {}).copy()
        for h in ["Content-Length", "Accept-Encoding", "Content-Type", "content-length", "Cookie", "cookie"]:
            headers.pop(h, None)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        headers.setdefault("Origin", "https://chat.qwen.ai")
        headers.setdefault("Referer", f"https://chat.qwen.ai/c/{chat_id}")
        headers.setdefault("source", "web")
        headers.setdefault("Version", "0.2.45")
        headers["X-Request-Id"] = str(uuid.uuid4())

        user_message = {
            "fid": fid,
            "parentId": parent_id,
            "childrenIds": [next_child_id],
            "role": "user",
            "content": last_user_msg,
            "user_action": "chat",
            "files": [],
            "timestamp": ts,
            "models": [internal_model],
            "chat_type": "t2t",
            "feature_config": {
                "thinking_enabled": False,
                "output_schema": "phase",
                "research_mode": "normal",
                "auto_thinking": False,
                "thinking_mode": "Auto",
                "thinking_format": "summary",
                "auto_search": False,
            },
            "extra": {"meta": {"subChatType": "t2t"}},
            "sub_chat_type": "t2t",
            "parent_id": parent_id,
        }

        payload = {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": internal_model,
            "parent_id": parent_id,
            "messages": [user_message],
            "timestamp": ts,
        }

        url = "https://chat.qwen.ai/api/v2/chat/completions"
        params = {"chat_id": chat_id}

        raw_content = ""
        text = ""
        parser = WebToolParser(auto_wrap_json=True)

        for attempt in range(2):
            if attempt == 1:
                self._config.pop("qwen_web_chat_id", None)
                self._config.pop("qwen_web_parent_id", None)
                self._config.pop("chat_id", None)
                self._config.pop("parent_id", None)
                chat_id = str(uuid.uuid4())
                parent_id = None
                params["chat_id"] = chat_id
                payload["chat_id"] = chat_id
                payload["parent_id"] = None
                user_message["parentId"] = None
                user_message["parent_id"] = None
                payload["messages"] = [user_message]
                yield TextChunk("[qwen-web] Chat unavailable — retrying with fresh thread...\n")
                raw_content = ""

            try:
                response = requests.post(
                    url, params=params, json=payload,
                    headers=headers, cookies=cookies,
                    stream=True, timeout=120,
                )
            except Exception as e:
                msg = f"[qwen-web] Error: {e}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                self.sm.save_state("qwen", self._config)
                return

            if response.status_code == 401:
                msg = "[qwen-web] Auth error (401) — token expired. Run harvester."
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                return

            if response.status_code in (400, 404) and attempt == 0:
                continue

            if response.status_code != 200:
                msg = f"[qwen-web] HTTP {response.status_code}: {response.text[:300]}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                return

            try:
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except Exception:
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                    else:
                        data_str = line
                    if not data_str or data_str == "[DONE]":
                        if data_str == "[DONE]":
                            break
                        continue

                    try:
                        data = json.loads(data_str)
                    except Exception:
                        continue

                    if not isinstance(data, dict):
                        continue

                    content_chunk = ""
                    captured_id = (
                        data.get("response.message_id")
                        or data.get("response_message_id")
                        or data.get("message_id")
                        or (data.get("message", {}) or {}).get("id")
                        or data.get("response_id")
                    )
                    if not captured_id:
                        for ch in data.get("choices", []) or []:
                            msg_obj = ch.get("message") if isinstance(ch, dict) else None
                            if isinstance(msg_obj, dict) and msg_obj.get("id"):
                                captured_id = msg_obj["id"]
                                break
                    if not captured_id:
                        resp_obj = data.get("response", {})
                        if isinstance(resp_obj, dict):
                            captured_id = resp_obj.get("id") or resp_obj.get("message_id")
                    if not captured_id and data.get("id") and data.get("id") != chat_id:
                        captured_id = data["id"]
                    if captured_id:
                        self._config["qwen_web_parent_id"] = captured_id
                        self._config["parent_id"] = captured_id
                        self._config["chat_id"] = self._config.get("qwen_web_chat_id") or chat_id

                    if data.get("chat_id") and not self._config.get("qwen_web_chat_id"):
                        self._config["qwen_web_chat_id"] = data["chat_id"]
                        self._config["chat_id"] = data["chat_id"]

                    choices = data.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                        if isinstance(delta, dict):
                            c = delta.get("content")
                            if isinstance(c, str):
                                content_chunk += c
                            rc = delta.get("reasoning_content") or delta.get("thinking_content")
                            if isinstance(rc, str) and rc:
                                yield TextChunk(rc)

                    if not content_chunk:
                        output = data.get("output", {})
                        if isinstance(output, dict):
                            t = output.get("text") or output.get("content")
                            if isinstance(t, str):
                                content_chunk = t

                    if not content_chunk and isinstance(data.get("content"), str):
                        content_chunk = data["content"]

                    if content_chunk:
                        raw_content += content_chunk
            except Exception as e:
                msg = f"[qwen-web] Error: {e}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                self.sm.save_state("qwen", self._config)
                return

            if not raw_content and attempt == 0:
                continue
            break

        if raw_content:
            text = parser.parse_chunk(raw_content)
            text += parser.flush()
            if text:
                yield TextChunk(text)

        self.sm.save_state("qwen", self._config)
        yield AssistantTurn(text or "[qwen-web: no response]", parser.tool_calls, 0, 0)
