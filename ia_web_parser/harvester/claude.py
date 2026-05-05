"""Claude.ai harvester using Playwright persistent profile."""
import time
import json
from datetime import datetime
from ia_web_parser.harvester.base import BaseHarvester


class ClaudeHarvester(BaseHarvester):
    """Harvest auth cookies + headers from claude.ai.

    Usage::

        from ia_web_parser import SessionManager, ClaudeHarvester

        sm = SessionManager()
        harvester = ClaudeHarvester(sm)
        auth = harvester.harvest()          # opens visible Chrome
        # auth saved automatically to ~/.ia-web-parser/claude.json
    """

    def harvest(self) -> dict:
        import requests

        browser, page = self._launch_persistent("claude", "https://claude.ai")
        cookies = []
        headers_data = {}
        conversation_ids = []
        user_agent = ""

        try:
            info = lambda msg: print(f"[harvester/claude] {msg}")
            info("Navigating to claude.ai ...")
            page.goto("https://claude.ai", wait_until="networkidle")
            time.sleep(3)

            if "login" in page.url.lower() or "signin" in page.url.lower():
                info("Login page detected. Please log in manually, then press ENTER here...")
                input()

            page.goto("https://claude.ai/new", wait_until="networkidle")
            time.sleep(2)
            user_agent = page.evaluate("navigator.userAgent") if browser.pages else ""

            def _handle_req(req):
                if "claude.ai/api" in req.url:
                    headers_data["url"] = req.url
                    headers_data["headers"] = dict(req.headers)
                    if "chat_conversations" in req.url:
                        parts = req.url.split("/")
                        for i, part in enumerate(parts):
                            if part == "chat_conversations" and i + 1 < len(parts):
                                cid = parts[i + 1].split("?")[0]
                                if cid and len(cid) > 10:
                                    conversation_ids.append(cid)

            page.on("request", _handle_req)
            try:
                page.click('div[contenteditable="true"]', timeout=4000)
                time.sleep(1)
            except Exception:
                pass

            cookies = browser.cookies()
        except KeyboardInterrupt:
            print("[harvester/claude] Interrupted — saving partial cookies...")
        finally:
            try:
                browser.close()
            except Exception:
                pass

        if not cookies:
            raise RuntimeError("No cookies collected. Try again.")

        # ── Validate cookies before saving ───────────────────────────────
        print("[harvester/claude] Testing cookies...")
        s = requests.Session()
        for c in cookies:
            s.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", "claude.ai"),
                path=c.get("path", "/"),
            )
        s.headers["User-Agent"] = user_agent or "Mozilla/5.0"
        s.headers["anthropic-client-platform"] = "web_claude_ai"
        s.headers["Origin"] = "https://claude.ai"
        r = s.get("https://claude.ai/api/organizations", timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"Cookie test failed ({r.status_code}) — keeping old cookies intact.")
        print(f"[harvester/claude] Cookies valid (org check: {r.status_code})")

        data = {
            "cookies": cookies,
            "headers": headers_data.get("headers", {}),
            "conversation_ids": list(set(conversation_ids)),
            "harvested_at": datetime.now().isoformat(),
            "user_agent": user_agent,
        }
        self.sm.save_auth("claude", data)
        print(f"[harvester/claude] Saved {len(cookies)} cookies -> {self.sm.auth_path('claude')}")
        return data
