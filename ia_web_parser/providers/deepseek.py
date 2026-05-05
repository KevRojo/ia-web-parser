"""DeepSeek web provider."""
import json
import base64
import requests
from typing import Generator
from pathlib import Path

from ia_web_parser.core.types import TextChunk, AssistantTurn
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.history import format_web_tool_manifest, consolidate_web_history
from ia_web_parser.session import SessionManager


class _DeepSeekPoWSolver:
    """Lazy-initialized WASM PoW solver for DeepSeek web (sha3_wasm_bg)."""
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        import os
        import wasmtime
        import ctypes
        wasm_path = os.path.join(os.path.dirname(__file__), "sha3_wasm_bg.7b9ca65ddd.wasm")
        if not os.path.exists(wasm_path):
            raise FileNotFoundError(f"WASM not found: {wasm_path}")
        self._engine = wasmtime.Engine()
        self._store = wasmtime.Store(self._engine)
        self._module = wasmtime.Module.from_file(self._engine, wasm_path)
        self._instance = wasmtime.Instance(self._store, self._module, [])
        self._mem = self._instance.exports(self._store)["memory"]
        self._sp = self._instance.exports(self._store)["__wbindgen_add_to_stack_pointer"]
        self._malloc = self._instance.exports(self._store)["__wbindgen_export_0"]
        self._solve = self._instance.exports(self._store)["wasm_solve"]

    def _get_mem_array(self):
        import ctypes
        ptr = self._mem.data_ptr(self._store)
        return ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte * self._mem.data_len(self._store))).contents

    def _alloc_string(self, s: str):
        data = s.encode("utf-8")
        ptr = self._malloc(self._store, len(data), 1)
        arr = self._get_mem_array()
        for i, b in enumerate(data):
            arr[ptr + i] = b
        return ptr, len(data)

    def solve(self, challenge: str, salt: str, expire_at: int, difficulty: int):
        import struct
        prefix = f"{salt}_{expire_at}_"
        retptr = self._sp(self._store, -16)
        try:
            ch_ptr, ch_len = self._alloc_string(challenge)
            prefix_ptr, prefix_len = self._alloc_string(prefix)
            self._solve(self._store, retptr, ch_ptr, ch_len, prefix_ptr, prefix_len, float(difficulty))
            arr = self._get_mem_array()
            status = struct.unpack("<i", bytes(arr[retptr : retptr + 4]))[0]
            value = struct.unpack("<d", bytes(arr[retptr + 8 : retptr + 16]))[0]
            if status == 0:
                return None
            return int(value)
        finally:
            self._sp(self._store, 16)


class DeepSeekWebProvider:
    """Stream completions from chat.deepseek.com using harvested session data."""

    def __init__(self, auth_file: str | None = None, session_manager: SessionManager | None = None):
        self.sm = session_manager or SessionManager()
        self.auth_path = Path(auth_file) if auth_file else self.sm.auth_path("deepseek", "deepseek_web.json")
        self._config = self.sm.load_state("deepseek")

    def _load_auth(self) -> dict:
        if not self.auth_path.exists():
            raise FileNotFoundError(f"Auth file not found: {self.auth_path} -> run harvester first")
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def chat(
        self,
        messages: list[dict],
        model: str = "deepseek-v3",
        system: str = "",
        tool_schemas: list[dict] | None = None,
    ) -> Generator:
        tool_schemas = tool_schemas or []
        auth_data = self._load_auth()

        token = auth_data.get("token") or auth_data.get("authorization", "")
        if token and not token.startswith("Bearer "):
            token = f"Bearer {token}"

        cookies = {c["name"]: c["value"] for c in auth_data.get("cookies", [])}

        manifest = format_web_tool_manifest(tool_schemas, messages)
        last_user_msg = consolidate_web_history(messages, manifest)

        ds_messages = []
        if system:
            ds_messages.append({"role": "system", "content": system})
        for m in messages[:-1][-20:]:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            if role in ("user", "assistant") and content:
                ds_messages.append({"role": role, "content": content})
        ds_messages.append({"role": "user", "content": last_user_msg})

        internal_model = auth_data.get("model", "deepseek_v3")
        if "r1" in model.lower():
            internal_model = "deepseek_r1"
        elif "v3" in model.lower() or "chat" in model.lower():
            internal_model = "deepseek_v3"

        chat_session_id = (
            self._config.get("chat_session_id")
            or self._config.get("deepseek_web_session_id")
            or auth_data.get("chat_session_id")
        )
        parent_message_id = (
            self._config.get("parent_message_id")
            or self._config.get("deepseek_web_parent_id")
        )

        headers = auth_data.get("headers", {}).copy()
        for h in ["Content-Length", "Accept-Encoding", "Content-Type", "content-length"]:
            headers.pop(h, None)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream"
        if token:
            headers["Authorization"] = token

        url = auth_data.get("url") or "https://chat.deepseek.com/api/v0/chat/completion"

        if chat_session_id:
            prompt_text = last_user_msg
        else:
            parts = []
            if system:
                parts.append(f"[System]: {system}")
            for m in ds_messages[:-1]:
                role = m.get("role", "user").capitalize()
                parts.append(f"[{role}]: {m.get('content', '')}")
            parts.append(last_user_msg)
            prompt_text = "\n\n".join(parts)

        payload = {
            "model": internal_model,
            "prompt": prompt_text,
            "ref_file_ids": [],
            "thinking_enabled": internal_model == "deepseek_r1",
            "search_enabled": False,
            "stream": True,
        }
        if chat_session_id:
            payload["chat_session_id"] = chat_session_id
        if parent_message_id is not None:
            payload["parent_message_id"] = parent_message_id

        text = ""
        thinking = ""
        raw_content = ""
        parser = WebToolParser(auto_wrap_json=True)
        in_thinking = False

        try:
            # Fetch and solve PoW challenge
            try:
                pow_resp = requests.post(
                    "https://chat.deepseek.com/api/v0/chat/create_pow_challenge",
                    cookies=cookies,
                    headers={k: v for k, v in headers.items() if k.lower() != "x-ds-pow-response"},
                    json={"target_path": "/api/v0/chat/completion"},
                    timeout=10,
                )
                if pow_resp.status_code == 200:
                    ch = pow_resp.json()["data"]["biz_data"]["challenge"]
                    solver = _DeepSeekPoWSolver.get()
                    ans = solver.solve(ch["challenge"], ch["salt"], ch["expire_at"], ch["difficulty"])
                    if ans is not None:
                        pow_obj = {
                            "algorithm": ch["algorithm"],
                            "challenge": ch["challenge"],
                            "salt": ch["salt"],
                            "answer": ans,
                            "signature": ch["signature"],
                            "target_path": ch["target_path"],
                        }
                        headers["x-ds-pow-response"] = base64.b64encode(
                            json.dumps(pow_obj, separators=(",", ":")).encode()
                        ).decode()
            except Exception:
                pass

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                cookies=cookies,
                stream=True,
                timeout=120,
            )

            if response.status_code == 401:
                msg = "[deepseek-web] Auth error (401) — token expired. Run harvester."
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                return

            if response.status_code != 200:
                msg = f"[deepseek-web] HTTP {response.status_code}: {response.text[:200]}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                return

            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8").strip()
                except Exception:
                    continue

                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                content_chunk = ""
                thinking_chunk = ""

                if isinstance(data, dict):
                    if "response_message_id" in data:
                        self._config["deepseek_web_parent_id"] = data["response_message_id"]
                        self._config["chat_session_id"] = chat_session_id or data.get("id")
                        self._config["parent_message_id"] = data["response_message_id"]
                    if data.get("id"):
                        self._config["deepseek_web_session_id"] = data["id"]

                    p, o, v = data.get("p", ""), data.get("o", ""), data.get("v")
                    if p == "response/fragments/-1/content" and o == "APPEND" and isinstance(v, str):
                        content_chunk = v
                    elif "p" not in data and "o" not in data and isinstance(v, str):
                        content_chunk = v
                    elif isinstance(v, dict):
                        response_obj = v.get("response", {})
                        if isinstance(response_obj, dict):
                            fragments = response_obj.get("fragments", [])
                            for frag in fragments:
                                if isinstance(frag, dict) and frag.get("type") == "RESPONSE":
                                    content_chunk += frag.get("content", "")

                if not content_chunk and not thinking_chunk:
                    choices = data.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        thinking_chunk = delta.get("reasoning_content") or delta.get("thinking_content", "")
                        content_chunk = delta.get("content", "")

                if thinking_chunk:
                    thinking += thinking_chunk
                    if not in_thinking:
                        in_thinking = True
                    yield TextChunk(thinking_chunk)

                if content_chunk:
                    in_thinking = False
                    raw_content += content_chunk

        except Exception as e:
            msg = f"[deepseek-web] Error: {e}"
            yield TextChunk(msg)
            yield AssistantTurn(msg, [], 0, 0, error=True)
            self.sm.save_state("deepseek", self._config)
            return

        if raw_content:
            text = parser.parse_chunk(raw_content)
            text += parser.flush()
            if text:
                yield TextChunk(text)

        self.sm.save_state("deepseek", self._config)
        yield AssistantTurn(text or "[deepseek-web: no response]", parser.tool_calls, 0, 0)
