"""Base harvester with Playwright persistent profiles."""
import os
from abc import ABC, abstractmethod
from typing import Optional


class BaseHarvester(ABC):
    """Abstract base for all browser-based auth harvesters.

    Each harvester uses a **persistent Playwright profile** so the user only
    needs to log in once per provider.  On subsequent runs the browser opens
    already authenticated.

    Args:
        session_manager: :class:`ia_web_parser.session.SessionManager` instance.
        headless: Whether to hide the browser window (default ``False``).
    """

    def __init__(self, session_manager, headless: bool = False):
        self.sm = session_manager
        self.headless = headless

    # ── Playwright helpers ─────────────────────────────────────────────

    def _launch_persistent(self, provider: str, start_url: str, extra_args=None, user_agent: Optional[str] = None):
        """Launch Chromium with a persistent profile for *provider*.

        Returns ``(browser, page)`` tuple.  The caller is responsible for
        closing the browser.
        """
        from playwright.sync_api import sync_playwright

        profile = str(self.sm.profile_dir(provider))
        os.makedirs(profile, exist_ok=True)

        args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1400,900",
        ]
        if extra_args:
            args.extend(extra_args)

        p = sync_playwright().start()
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile,
            channel="chrome",
            headless=self.headless,
            args=args,
            viewport={"width": 1400, "height": 900},
            timeout=60000,
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        if user_agent:
            page.set_extra_http_headers({"User-Agent": user_agent})
        return browser, page

    @abstractmethod
    def harvest(self) -> dict:
        """Run the harvester and return the auth blob dict."""
        raise NotImplementedError
