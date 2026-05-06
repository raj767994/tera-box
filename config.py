"""
config.py — All bot settings loaded from environment variables.
"""

import os
from pathlib import Path


def _parse_allowed_users() -> set[int]:
    """Parse ALLOWED_USERS env var: comma-separated list of Telegram user IDs."""
    raw = os.getenv("ALLOWED_USERS", "")
    owner = os.getenv("OWNER_ID", "")
    ids: set[int] = set()
    for part in (raw + "," + owner).split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


class Config:
    # ── Core ─────────────────────────────────────────────────────────────────
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OWNER_ID: int = int(os.getenv("OWNER_ID", "0"))
    ALLOWED_USERS: set[int] = _parse_allowed_users()

    # ── Rate limiting ─────────────────────────────────────────────────────────
    # Max RATE_LIMIT_REQUESTS requests in RATE_LIMIT_WINDOW seconds per user
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "5"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds

    # ── Download dirs & cache ─────────────────────────────────────────────────
    DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
    CACHE_DIR: Path = Path(os.getenv("CACHE_DIR", "cache"))

    # ── Telegram limits ───────────────────────────────────────────────────────
    # Default Telegram Bot API upload limit is 50 MB; local API allows up to 2 GB.
    # Set to 50*1024*1024 for cloud API, or higher if you run a local Bot API server.
    TELEGRAM_FILE_LIMIT: int = int(os.getenv("TELEGRAM_FILE_LIMIT", str(50 * 1024 * 1024)))

    # ── yt-dlp options ────────────────────────────────────────────────────────
    YTDLP_RETRIES: int = int(os.getenv("YTDLP_RETRIES", "5"))
    YTDLP_CONCURRENT_FRAGS: int = int(os.getenv("YTDLP_CONCURRENT_FRAGS", "4"))

    @classmethod
    def validate(cls) -> None:
        if not cls.BOT_TOKEN:
            raise EnvironmentError("BOT_TOKEN environment variable is not set!")
        if not cls.ALLOWED_USERS:
            raise EnvironmentError(
                "No authorized users defined. Set OWNER_ID or ALLOWED_USERS."
            )
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
