import asyncio
import logging
from pathlib import Path
from typing import Any

import yt_dlp

from receipt.application.errors import VideoUnavailableError, VideoUnavailableReason
from receipt.application.ports.video_downloader import VideoMetadata
from receipt.domain.video import Platform, UnsupportedUrlError, detect_platform

_log = logging.getLogger("yt_dlp")


class _YtDlpLogger:
    """Sends yt-dlp output to logging instead of stderr. Errors are raised as exceptions anyway."""

    def debug(self, message: str) -> None:
        _log.debug(message)

    def info(self, message: str) -> None:
        _log.debug(message)

    def warning(self, message: str) -> None:
        _log.warning(message)

    def error(self, message: str) -> None:
        _log.debug(message)


_BASE_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "logger": _YtDlpLogger(),
    # A link like watch?v=...&list=... means the video, not the whole playlist.
    "noplaylist": True,
}

# Checked in order: "Private video. Sign in if you've been granted access" is PRIVATE, not LOGIN.
_REASON_MARKERS: tuple[tuple[VideoUnavailableReason, tuple[str, ...]], ...] = (
    (VideoUnavailableReason.PRIVATE, ("private",)),
    (VideoUnavailableReason.LOGIN_REQUIRED, ("login", "log in", "sign in", "cookies")),
    (VideoUnavailableReason.GEO_BLOCKED, ("your country", "geo restrict", "geo-restrict")),
    (
        VideoUnavailableReason.NOT_FOUND,
        ("video unavailable", "removed", "does not exist", "not found", "404"),
    ),
)


def classify_download_error(message: str) -> VideoUnavailableReason:
    lowered = message.lower()
    for reason, markers in _REASON_MARKERS:
        if any(marker in lowered for marker in markers):
            return reason
    return VideoUnavailableReason.UNKNOWN


class YtDlpVideoDownloader:
    """yt-dlp is blocking, so every call runs in a worker thread."""

    def __init__(self, cookies_file: Path | None = None) -> None:
        self._cookies_file = cookies_file

    async def fetch_metadata(self, url: str) -> VideoMetadata:
        platform = detect_platform(url)
        info = await asyncio.to_thread(self._extract, url, {"skip_download": True}, False)
        return _to_metadata(info, url, platform)

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        detect_platform(url)
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        options = {
            # TikTok and Instagram often have no separate audio track: then take the whole file.
            "format": "bestaudio/best",
            "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
        }
        info = await asyncio.to_thread(self._extract, url, options, True)
        return Path(info["requested_downloads"][0]["filepath"])

    def _extract(self, url: str, options: dict[str, Any], download: bool) -> dict[str, Any]:
        all_options = {**_BASE_OPTIONS, **options}
        if self._cookies_file is not None:
            all_options["cookiefile"] = str(self._cookies_file)
        try:
            with yt_dlp.YoutubeDL(all_options) as ydl:
                info = ydl.extract_info(url, download=download)
        except yt_dlp.utils.DownloadError as error:
            message = str(error)
            if "unsupported url" in message.lower():
                raise UnsupportedUrlError(f"Ссылка не ведёт на видео: {url}") from error
            raise VideoUnavailableError(classify_download_error(message), message) from error
        if info.get("_type") == "playlist":
            raise UnsupportedUrlError(f"Это плейлист или канал, а не одно видео: {url}")
        return info


def _to_metadata(info: dict[str, Any], url: str, platform: Platform) -> VideoMetadata:
    duration = info.get("duration")
    return VideoMetadata(
        url=info.get("webpage_url") or url,
        platform=platform,
        video_id=str(info["id"]),
        title=info.get("title") or "",
        description=info.get("description") or "",
        author=info.get("uploader") or info.get("channel") or info.get("creator"),
        duration_seconds=round(duration) if duration is not None else None,
    )
