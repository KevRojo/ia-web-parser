"""Session and cookie management."""
import os
import json
from pathlib import Path
from typing import Optional


class SessionManager:
    """Manages cookies, auth files, and Playwright persistent profiles.

    Default base directory: ``~/.ia-web-parser``
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or Path.home() / ".ia-web-parser")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Auth / cookie files ──────────────────────────────────────────────

    def auth_path(self, provider: str, filename: Optional[str] = None) -> Path:
        """Return the path to a provider's auth JSON file."""
        name = filename or f"{provider}.json"
        return self.base_dir / name

    def load_auth(self, provider: str, filename: Optional[str] = None) -> dict:
        """Load auth JSON for a provider. Returns empty dict if missing."""
        path = self.auth_path(provider, filename)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_auth(self, provider: str, data: dict, filename: Optional[str] = None):
        """Save auth JSON for a provider."""
        path = self.auth_path(provider, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ── Playwright persistent profiles ───────────────────────────────────

    def profile_dir(self, provider: str) -> Path:
        """Return the directory for a provider's persistent browser profile."""
        p = self.base_dir / "profiles" / provider
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Provider state files ─────────────────────────────────────────────

    def state_path(self, provider: str) -> Path:
        """Return the path to a provider's lightweight state JSON (chat ids, parent ids, etc)."""
        return self.base_dir / f"{provider}_state.json"

    def load_state(self, provider: str) -> dict:
        path = self.state_path(provider)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_state(self, provider: str, data: dict):
        path = self.state_path(provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def clear_state(self, provider: str):
        path = self.state_path(provider)
        if path.exists():
            path.unlink()
