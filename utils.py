"""
utils.py — Shared helper functions.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

logger = logging.getLogger("TeraBot.utils")

# ── TeraBox URL patterns ───────────────────────────────────────────────────────
_TERABOX_DOMAINS = re.compile(
    r"https?://(www\.)?"
    r"(terabox\.com|teraboxapp\.com|1024terabox\.com|"
    r"4funbox\.co|momerybox\.com|tibibox\.com|"
    r"nephobox\.com|freeterabox\.com|mirrobox\.com)",
    re.IGNORECASE,
)


def is_terabox_url(text: str) -> bool:
    """Return True if the text contains a recognizable TeraBox URL."""
    return bool(_TERABOX_DOMAINS.search(text))


# ── Human-readable file size ───────────────────────────────────────────────────
def bytes_to_human(size: int) -> str:
    if size <= 0:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# ── Duration formatter ─────────────────────────────────────────────────────────
def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "unknown"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Safe message edit (silently ignore "message not modified") ─────────────────
async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    try:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            pass  # no-op — content identical
        else:
            logger.warning("edit_message BadRequest: %s", exc)
    except TelegramError as exc:
        logger.warning("edit_message TelegramError: %s", exc)


# ── Temp file cleanup ──────────────────────────────────────────────────────────
def cleanup_file(path: str) -> None:
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            logger.debug("Cleaned up: %s", path)
    except Exception as exc:
        logger.warning("Could not delete temp file %s: %s", path, exc)
