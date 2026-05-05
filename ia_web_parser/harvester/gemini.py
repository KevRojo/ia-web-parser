"""Gemini harvester using Playwright persistent profile."""
import time
import json
import re
import urllib.parse
from datetime import datetime
from ia_web_parser.harvester.base import BaseHarvester


class GeminiHarvester(BaseHarvester):
    """Harvest session data from gemini.google.com.

    The user must type and send **FALCON** in the chat so the interceptor
    can locate the request payload.
    """

    def harvest(self) -> dict:
        extra = ["--disable-infobars"]
        browser, page = self._launch_persistent(
            "gemini-interceptor",
            "https://gemini.google.com/app",
            extra_args=extra,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        )
        intercepted = []

        def _handle_req(request):
            if "gemini.google.com" in request.url and request.method == "POST":
                try:
                    pd = request.post_data or ""
                except Exception:
                    pd = ""
                if "f.req" in pd and "falcon" in pd.lower():
                    if not intercepted:
                        intercepted.append({
                            "url": request.url,
                            "headers": dict(request.headers),
                            "method": request.method,
                            "post_data": pd[:15000],
                        })
                        print("[harvester/gemini] Payload intercepted!")

        page.on("request", _handle_req)

        print("[harvester/gemini] Navigating to gemini.google.com ...")
        try:
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        print("[harvester/gemini] ACTION REQUIRED:")
        print("  1. Make sure you are logged in to Google.")
        print("  2. Type and SEND the exact word  FALCON  in the Gemini chat.")
        print("  Waiting for interception (timeout 3 min)...")

        timeout_limit = 180
        start_t = time.time()
        while time.time() - start_t < timeout_limit:
            if intercepted:
                break
            page.wait_for_timeout(1000)

        if not intercepted:
            browser.close()
            raise RuntimeError("No requests intercepted. Make sure you sent 'FALCON'.")

        # Extract SNlM0e token
        snlm0e = None
        try:
            snlm0e = page.evaluate("window.WIZ_global_data?.SNlM0e")
            if not snlm0e:
                match = re.search(r'"SNlM0e":"(.*?)"', page.content())
                if match:
                    snlm0e = match.group(1)
            if snlm0e:
                print(f"[harvester/gemini] SNlM0e captured ({snlm0e[:10]}...)")
        except Exception as e:
            print(f"[harvester/gemini] SNlM0e capture failed: {e}")

        cookies = browser.cookies()
        try:
            browser.close()
        except Exception:
            pass

        data = {
            "cookies": cookies,
            "snlm0e": snlm0e,
            "intercepted_requests": intercepted[-5:],
            "harvested_at": datetime.now().isoformat(),
        }
        self.sm.save_auth("gemini", data, filename="gemini_web.json")
        print(f"[harvester/gemini] Saved -> {self.sm.auth_path('gemini', 'gemini_web.json')}")
        return data
