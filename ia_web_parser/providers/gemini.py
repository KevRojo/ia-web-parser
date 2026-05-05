"""Gemini web provider."""
import json
import re
import urllib.parse
import requests
from typing import Generator
from pathlib import Path

from ia_web_parser.core.types import TextChunk, AssistantTurn
from ia_web_parser.core.parser import WebToolParser
from ia_web_parser.core.history import format_web_tool_manifest, consolidate_web_history
from ia_web_parser.session import SessionManager


class GeminiWebProvider:
    """Stream completions from gemini.google.com using harvested session data.

    Uses the internal ``f.req`` POST format captured by the harvester.  The
    user's prompt replaces the ``FALCON`` sentinel string inside the payload.
    """

    def __init__(self, auth_file: str | None = None, session_manager: SessionManager | None = None):
        self.sm = session_manager or SessionManager()
        self.auth_path = Path(auth_file) if auth_file else self.sm.auth_path("gemini", "gemini_web.json")
        self._config = self.sm.load_state("gemini")

    def _load_auth(self) -> dict:
        if not self.auth_path.exists():
            raise FileNotFoundError(f"Auth file not found: {self.auth_path} -> run harvester first")
        with open(self.auth_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _find_and_replace(obj, target, replacement):
        """Recursively replace *target* string inside nested lists/dicts."""
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str) and target in v:
                    if v == target:
                        obj[i] = replacement
                    else:
                        try:
                            inner = json.loads(v)
                            GeminiWebProvider._find_and_replace(inner, target, replacement)
                            obj[i] = json.dumps(inner, separators=(",", ":"))
                        except Exception:
                            pass
                elif isinstance(v, (list, dict)):
                    GeminiWebProvider._find_and_replace(v, target, replacement)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and target in v:
                    if v == target:
                        obj[k] = replacement
                elif isinstance(v, (list, dict)):
                    GeminiWebProvider._find_and_replace(v, target, replacement)

    def chat(
        self,
        messages: list[dict],
        model: str = "gemini-latest",
        system: str = "",
        tool_schemas: list[dict] | None = None,
    ) -> Generator:
        tool_schemas = tool_schemas or []
        auth_data = self._load_auth()

        manifest = format_web_tool_manifest(tool_schemas, messages)
        last_user_msg = consolidate_web_history(messages, manifest)

        last_req = auth_data.get("intercepted_requests", [{}])[-1]
        url = last_req.get("url")
        if not url:
            msg = "[gemini-web] Intercepted URL not found. Re-harvest."
            yield TextChunk(msg)
            yield AssistantTurn(msg, [], 0, 0, error=True)
            return

        pd_raw = last_req.get("post_data", "")
        pd_parsed = urllib.parse.parse_qs(pd_raw)
        parsed_url = urllib.parse.urlparse(url)
        params_qs = urllib.parse.parse_qs(parsed_url.query)
        requests_params = {k: v[0] for k, v in params_qs.items()}

        cookies = {c["name"]: c["value"] for c in auth_data.get("cookies", [])}

        headers = last_req.get("headers", {}).copy()
        for h in ["Content-Length", "Accept-Encoding", "Content-Type"]:
            headers.pop(h, None)
            headers.pop(h.lower(), None)
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"

        raw_content = ""
        text = ""
        parser = WebToolParser(auto_wrap_json=True)

        for attempt in range(3):
            raw_content = ""
            if attempt == 1:
                yield TextChunk("[gemini-web] Empty response — retrying same thread...\n")
            elif attempt == 2:
                self._config.pop("gemini_web_c_id", None)
                self._config.pop("gemini_web_r_id", None)
                self._config.pop("gemini_web_rc_id", None)
                yield TextChunk("[gemini-web] Empty response — IDs cleared, retrying with new thread...\n")

            curr_f_req = []
            f_req_source = None
            if "f.req" in pd_parsed:
                curr_f_req = json.loads(pd_parsed["f.req"][0])
                f_req_source = "post_data"
            elif "f.req" in requests_params:
                curr_f_req = json.loads(requests_params["f.req"])
                f_req_source = "params"

            if f_req_source:
                self._find_and_replace(curr_f_req, "FALCON", last_user_msg)
                if attempt < 2:
                    try:
                        c_id = self._config.get("gemini_web_c_id")
                        r_id = self._config.get("gemini_web_r_id")
                        if c_id and r_id:
                            for i, val in enumerate(curr_f_req):
                                if isinstance(val, str) and val.startswith("["):
                                    try:
                                        inner_req = json.loads(val)
                                        if len(inner_req) > 2:
                                            if not inner_req[2] or (isinstance(inner_req[2], list) and not inner_req[2][0]):
                                                inner_req[2] = [c_id, r_id]
                                                curr_f_req[i] = json.dumps(inner_req, separators=(",", ":"))
                                    except Exception:
                                        pass
                    except Exception:
                        pass

            pd_curr_dict = {}
            curr_requests_params = requests_params.copy()
            for k, v in pd_parsed.items():
                if k == "f.req" and f_req_source == "post_data":
                    pd_curr_dict[k] = json.dumps(curr_f_req, separators=(",", ":"))
                else:
                    pd_curr_dict[k] = v[0] if isinstance(v, list) else v

            if f_req_source == "params":
                curr_requests_params["f.req"] = json.dumps(curr_f_req, separators=(",", ":"))
            if "at" not in pd_curr_dict and auth_data.get("snlm0e"):
                pd_curr_dict["at"] = auth_data["snlm0e"]

            raw_text_len = 0
            try:
                response = requests.post(
                    url.split("?")[0],
                    params=curr_requests_params,
                    cookies=cookies,
                    headers=headers,
                    data=pd_curr_dict,
                    stream=True,
                    timeout=120,
                )

                if response.status_code != 200:
                    if attempt < 2:
                        continue
                    msg = f"[gemini-web] HTTP {response.status_code}: {response.text[:200]}"
                    yield TextChunk(msg)
                    yield AssistantTurn(msg, [], 0, 0, error=True)
                    self.sm.save_state("gemini", self._config)
                    return

                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        line = raw_line.decode("utf-8").strip()
                    except Exception:
                        continue
                    if not line.startswith('[["wrb.fr"'):
                        continue

                    try:
                        envelope = json.loads(line)
                        for item in envelope:
                            if len(item) > 2 and item[0] == "wrb.fr" and isinstance(item[2], str) and item[2].startswith("["):
                                try:
                                    inner = json.loads(item[2])
                                    if isinstance(inner, list) and len(inner) > 1:
                                        ids = inner[1]
                                        if isinstance(ids, list) and len(ids) >= 2:
                                            if ids[0]:
                                                self._config["gemini_web_c_id"] = ids[0]
                                            if ids[1]:
                                                self._config["gemini_web_r_id"] = ids[1]

                                    candidate = None
                                    try:
                                        if (isinstance(inner, list) and len(inner) > 4
                                                and isinstance(inner[4], list) and inner[4]
                                                and isinstance(inner[4][0], list) and len(inner[4][0]) > 1
                                                and isinstance(inner[4][0][1], list) and inner[4][0][1]):
                                            candidate = inner[4][0][1][0]
                                    except Exception:
                                        pass
                                    if not candidate:
                                        try:
                                            if (isinstance(inner, list) and len(inner) > 0
                                                    and isinstance(inner[0], list) and len(inner[0]) > 0
                                                    and isinstance(inner[0][0], str) and inner[0][0]):
                                                candidate = inner[0][0]
                                        except Exception:
                                            pass

                                    if candidate and isinstance(candidate, str) and len(candidate) > raw_text_len:
                                        diff = candidate[raw_text_len:]
                                        raw_text_len = len(candidate)
                                        raw_content += diff
                                        try:
                                            if len(inner) > 4 and inner[4][0][0]:
                                                self._config["gemini_web_rc_id"] = inner[4][0][0]
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                    except Exception:
                        continue
            except Exception as e:
                if attempt < 2:
                    continue
                msg = f"[gemini-web] Protocol Error: {e}"
                yield TextChunk(msg)
                yield AssistantTurn(msg, [], 0, 0, error=True)
                self.sm.save_state("gemini", self._config)
                return

            if raw_content:
                break

        if raw_content:
            text = parser.parse_chunk(raw_content)
            text += parser.flush()
            if text:
                yield TextChunk(text)

        self.sm.save_state("gemini", self._config)
        if not text and not parser.tool_calls:
            yield AssistantTurn("[gemini-web: no response after retries]", [], 0, 0)
        else:
            yield AssistantTurn(text, parser.tool_calls, 0, 0)
