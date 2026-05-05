"""Qwen harvester using Playwright persistent profile."""
import time
import json
from datetime import datetime
from ia_web_parser.harvester.base import BaseHarvester


class QwenHarvester(BaseHarvester):
    """Harvest JWT token + metadata from chat.qwen.ai.

    The user just needs to send any message while logged in.
    """

    def harvest(self, start_url: str = "https://chat.qwen.ai/") -> dict:
        extra = ["--disable-infobars"]
        browser, page = self._launch_persistent(
            "qwen-interceptor",
            start_url,
            extra_args=extra,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        )
        captured_token = [None]
        captured_model = [None]
        captured_chat_id = [None]
        captured_parent_id = [None]
        captured_headers = [{}]

        def _handle_req(request):
            url = request.url
            if "chat.qwen.ai" in url and "/chat/completions" in url and request.method == "POST":
                try:
                    hdrs = dict(request.headers)
                    if not captured_headers[0]:
                        captured_headers[0] = hdrs
                    try:
                        body = request.post_data
                        if body:
                            body_json = json.loads(body)
                            if not captured_model[0]:
                                captured_model[0] = body_json.get("model", "qwen3.6-plus")
                            if not captured_chat_id[0]:
                                captured_chat_id[0] = body_json.get("chat_id")
                            if not captured_parent_id[0]:
                                captured_parent_id[0] = body_json.get("parent_id")
                    except Exception:
                        pass
                except Exception:
                    pass

        page.on("request", _handle_req)

        print("[harvester/qwen] Navigating to chat.qwen.ai ...")
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        print("[harvester/qwen] ACTION REQUIRED:")
        print("  1. Make sure you are logged in to Qwen.")
        print("  2. Send ANY message in the chat.")
        print("  Waiting for token interception (timeout 3 min)...")

        timeout_limit = 180
        start_t = time.time()
        while time.time() - start_t < timeout_limit:
            if not captured_token[0]:
                for c in browser.cookies():
                    if c.get("name") == "token" and c.get("value"):
                        captured_token[0] = c["value"]
                        print(f"[harvester/qwen] JWT token captured ({captured_token[0][:20]}...)")
                        break
            if captured_token[0] and captured_chat_id[0]:
                break
            page.wait_for_timeout(1000)

        if not captured_token[0]:
            browser.close()
            raise RuntimeError("No token cookie found.")

        cookies = browser.cookies()
        try:
            browser.close()
        except Exception:
            pass

        if not captured_chat_id[0] and "/c/" in start_url:
            captured_chat_id[0] = start_url.split("/c/")[-1].split("?")[0].strip()

        data = {
            "token": captured_token[0],
            "model": captured_model[0] or "qwen3.6-plus",
            "chat_id": captured_chat_id[0],
            "parent_id": captured_parent_id[0],
            "cookies": cookies,
            "headers": {
                k: v for k, v in captured_headers[0].items()
                if k.lower() not in ("content-length", "accept-encoding", "cookie")
            },
            "url": "https://chat.qwen.ai/api/v2/chat/completions",
            "harvested_at": datetime.now().isoformat(),
        }
        self.sm.save_auth("qwen", data, filename="qwen_web.json")
        print(f"[harvester/qwen] Saved -> {self.sm.auth_path('qwen', 'qwen_web.json')}")
        return data
