"""DeepSeek harvester using Playwright persistent profile."""
import time
import json
from datetime import datetime
from ia_web_parser.harvester.base import BaseHarvester


class DeepSeekHarvester(BaseHarvester):
    """Harvest Bearer token + cookies from chat.deepseek.com.

    The user just needs to send any message while logged in.
    """

    def harvest(self, start_url: str = "https://chat.deepseek.com/") -> dict:
        extra = ["--disable-infobars"]
        browser, page = self._launch_persistent(
            "deepseek-interceptor",
            start_url,
            extra_args=extra,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        )
        captured_token = [None]
        captured_model = [None]
        captured_session_id = [None]
        captured_headers = [{}]

        def _handle_req(request):
            url = request.url
            if "chat.deepseek.com" in url and "/chat/completion" in url and request.method == "POST":
                try:
                    hdrs = dict(request.headers)
                    auth = hdrs.get("authorization", "")
                    if auth and not captured_token[0]:
                        captured_token[0] = auth.replace("Bearer ", "").strip()
                        captured_headers[0] = hdrs
                        print(f"[harvester/deepseek] Bearer token captured ({captured_token[0][:20]}...)")
                    try:
                        body = request.post_data
                        if body:
                            body_json = json.loads(body)
                            if not captured_model[0]:
                                captured_model[0] = body_json.get("model", "deepseek_v3")
                            if not captured_session_id[0]:
                                captured_session_id[0] = body_json.get("chat_session_id")
                    except Exception:
                        pass
                except Exception:
                    pass

        page.on("request", _handle_req)

        print("[harvester/deepseek] ACTION REQUIRED:")
        print("  1. Make sure you are logged in to DeepSeek.")
        print("  2. Send ANY message in the chat.")
        print("  Waiting for token interception (timeout 3 min)...")

        timeout_limit = 180
        start_t = time.time()
        while time.time() - start_t < timeout_limit:
            if captured_token[0]:
                break
            page.wait_for_timeout(1000)

        if not captured_token[0]:
            browser.close()
            raise RuntimeError("No token intercepted.")

        cookies = browser.cookies()
        try:
            browser.close()
        except Exception:
            pass

        # Fallback session ID from URL
        if not captured_session_id[0] and "/s/" in start_url:
            captured_session_id[0] = start_url.split("/s/")[-1].split("?")[0].strip()

        data = {
            "token": captured_token[0],
            "model": captured_model[0] or "deepseek_v3",
            "chat_session_id": captured_session_id[0],
            "cookies": cookies,
            "headers": {
                k: v for k, v in captured_headers[0].items()
                if k.lower() not in ("authorization", "content-length", "accept-encoding")
            },
            "url": "https://chat.deepseek.com/api/v0/chat/completion",
            "harvested_at": datetime.now().isoformat(),
        }
        self.sm.save_auth("deepseek", data, filename="deepseek_web.json")
        print(f"[harvester/deepseek] Saved -> {self.sm.auth_path('deepseek', 'deepseek_web.json')}")
        return data
