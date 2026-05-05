"""Kimi.com harvester using Playwright persistent profile."""
import time
import json
import struct
import re
from datetime import datetime
from ia_web_parser.harvester.base import BaseHarvester


class KimiHarvester(BaseHarvester):
    """Harvest gRPC-Web tokens + payload template from kimi.com.

    Usage::

        from ia_web_parser import SessionManager, KimiHarvester

        sm = SessionManager()
        auth = KimiHarvester(sm).harvest()
    """

    def harvest(self) -> dict:
        browser, page = self._launch_persistent("kimi-consumer", "https://www.kimi.com")
        intercepted_auth = {}
        last_payload = {}

        def _handle_req(request):
            if "ChatService/Chat" in request.url:
                try:
                    raw = request.post_data_buffer
                    if raw:
                        text = raw.decode("utf-8", errors="ignore")
                        match = re.search(r"(\{.*\"chat_id\".*\})", text)
                        if match:
                            nonlocal last_payload
                            last_payload = json.loads(match.group(0))
                            intercepted_auth["headers"] = dict(request.headers)
                            intercepted_auth["url"] = request.url
                            print("[harvester/kimi] Payload intercepted!")
                except Exception:
                    pass

        page.on("request", _handle_req)

        print("[harvester/kimi] Navigating to www.kimi.com ...")
        page.goto("https://www.kimi.com", wait_until="networkidle")

        print("[harvester/kimi] ACTION REQUIRED:")
        print("  1. Make sure you are logged in.")
        print("  2. Type and SEND a single message in the Kimi chat.")
        print("  Waiting for interception (timeout 3 min)...")

        timeout_limit = 180
        start_t = time.time()
        while time.time() - start_t < timeout_limit:
            if "url" in intercepted_auth:
                break
            page.wait_for_timeout(1000)

        if "url" not in intercepted_auth:
            browser.close()
            raise RuntimeError("Harvest timeout — no request intercepted.")

        cookies = browser.cookies()
        browser.close()

        data = {
            "cookies": cookies,
            "headers": intercepted_auth.get("headers", {}),
            "url": intercepted_auth.get("url"),
            "last_payload": last_payload,
            "harvested_at": datetime.now().isoformat(),
        }
        self.sm.save_auth("kimi", data, filename="kimi_consumer.json")
        print(f"[harvester/kimi] Saved -> {self.sm.auth_path('kimi', 'kimi_consumer.json')}")
        return data
