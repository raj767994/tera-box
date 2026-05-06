"""
downloader.py — TeraBox video extraction and downloading via yt-dlp.
Handles caching, subtitle download, and progress reporting.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from config import Config

logger = logging.getLogger("TeraBot.downloader")


class TeraboxDownloader:
    """Wraps yt-dlp for TeraBox (and generic) video downloading."""

    # ── Cache helpers ─────────────────────────────────────────────────────────
    def _cache_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _cache_info_path(self, url: str) -> Path:
        return Config.CACHE_DIR / f"{self._cache_key(url)}.json"

    def _load_cached_info(self, url: str) -> Optional[dict]:
        p = self._cache_info_path(url)
        if p.exists():
            age = time.time() - p.stat().st_mtime
            if age < 3600:  # cache valid for 1 hour
                try:
                    return json.loads(p.read_text())
                except Exception:
                    pass
        return None

    def _save_cached_info(self, url: str, info: dict) -> None:
        try:
            # Store only the fields we need (avoid huge yt-dlp dicts)
            slim = {
                k: info.get(k)
                for k in (
                    "title", "duration", "thumbnail", "uploader",
                    "filesize", "filesize_approx", "formats", "subtitles",
                    "automatic_captions", "description",
                )
            }
            self._cache_info_path(url).write_text(json.dumps(slim))
        except Exception as exc:
            logger.warning("Could not cache info: %s", exc)

    # ── Base yt-dlp options ───────────────────────────────────────────────────
    def _base_opts(self) -> dict:
        return {
            "quiet": True,
            "no_warnings": True,
            "retries": Config.YTDLP_RETRIES,
            "concurrent_fragment_downloads": Config.YTDLP_CONCURRENT_FRAGS,
            "http_headers": {
                # Mimic a browser to avoid blocks
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.terabox.com/",
            },
        }

    # ── fetch_info: get metadata without downloading ──────────────────────────
    def fetch_info(self, url: str) -> dict:
        """
        Return video metadata dict with formats and subtitles.
        Uses a 1-hour cache to avoid repeated network requests.
        """
        cached = self._load_cached_info(url)
        if cached:
            logger.info("Cache hit for %s", url)
            return cached

        opts = {
            **self._base_opts(),
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError("yt-dlp returned no info for this URL.")

        # Merge automatic captions into subtitles dict for display
        subs = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}
        for lang, tracks in auto.items():
            if lang not in subs:
                subs[f"{lang} (auto)"] = tracks
        info["subtitles"] = subs

        self._save_cached_info(url, info)
        logger.info("Fetched info for: %s", info.get("title"))
        return info

    # ── download: fetch the actual video (and optionally subtitles) ───────────
    def download(
        self,
        url: str,
        format_id: str,
        subtitle_lang: Optional[str],
        progress_hook: Optional[Callable] = None,
    ) -> tuple[str, Optional[str]]:
        """
        Download video and optionally subtitles.
        Returns (video_path, subtitle_path_or_None).
        """
        import asyncio

        # Unique output template to avoid collisions between concurrent downloads
        uid = self._cache_key(url + format_id + str(time.time()))
        out_template = str(Config.DOWNLOAD_DIR / f"{uid}.%(ext)s")

        # ── sync progress hook wrapper ─────────────────────────────────────
        # yt-dlp calls hooks synchronously; we bridge to async via a new event loop
        # trick: run the coroutine in the current thread's event loop if available.
        _loop = None
        try:
            _loop = asyncio.get_event_loop()
        except RuntimeError:
            pass

        def _hook(d: dict) -> None:
            if progress_hook and _loop and _loop.is_running():
                asyncio.run_coroutine_threadsafe(progress_hook(d), _loop)

        # ── Format selection ───────────────────────────────────────────────
        if format_id in ("best", "worst"):
            fmt_selector = (
                "bestvideo+bestaudio/best"
                if format_id == "best"
                else "worstvideo+worstaudio/worst"
            )
        else:
            # Try requested format; fall back to best
            fmt_selector = f"{format_id}+bestaudio/{format_id}/best"

        opts: dict = {
            **self._base_opts(),
            "format": fmt_selector,
            "outtmpl": out_template,
            "progress_hooks": [_hook],
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
        }

        # ── Subtitle options ───────────────────────────────────────────────
        if subtitle_lang:
            lang_code = subtitle_lang.replace(" (auto)", "")
            is_auto = "(auto)" in subtitle_lang
            opts.update(
                {
                    "writesubtitles": not is_auto,
                    "writeautomaticsub": is_auto,
                    "subtitleslangs": [lang_code],
                    "subtitlesformat": "srt",
                    # Do NOT embed — send as separate file so user can choose
                    "postprocessors": opts.get("postprocessors", []),
                }
            )

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        # ── Find output files ──────────────────────────────────────────────
        video_path = self._find_output(uid, [".mp4", ".mkv", ".webm", ".avi"])
        if not video_path:
            raise FileNotFoundError(
                f"Download completed but output file not found in {Config.DOWNLOAD_DIR}"
            )

        subtitle_path = None
        if subtitle_lang:
            subtitle_path = self._find_output(uid, [".srt", ".vtt", ".ass"])

        logger.info("Downloaded: %s", video_path)
        return str(video_path), str(subtitle_path) if subtitle_path else None

    def _find_output(self, uid: str, extensions: list[str]) -> Optional[Path]:
        """Scan DOWNLOAD_DIR for a file matching uid prefix and one of the extensions."""
        for f in Config.DOWNLOAD_DIR.iterdir():
            if f.stem == uid or f.name.startswith(uid):
                if f.suffix.lower() in extensions:
                    return f
        # Fallback: any file matching uid pattern
        matches = list(Config.DOWNLOAD_DIR.glob(f"{uid}*"))
        for ext in extensions:
            for m in matches:
                if m.suffix.lower() == ext:
                    return m
        return None
