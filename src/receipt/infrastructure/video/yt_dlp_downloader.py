import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import yt_dlp

from receipt.application.errors import (
    SubtitlesUnavailableError,
    VideoUnavailableError,
    VideoUnavailableReason,
)
from receipt.application.ports.video_downloader import SubtitleTrack, VideoMetadata
from receipt.domain.video import Platform, UnsupportedUrlError, detect_platform
from receipt.infrastructure.video.subtitles import subtitles_to_text

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


# Instagram's audio-only track is xHE-AAC (mp4a.40.42), which ffmpeg cannot decode yet, so
# such tracks are skipped for a small video file with ordinary AAC ("?" also lets through
# formats whose codec is unknown). TikTok and Instagram may have no audio-only track at all.
AUDIO_FORMAT = "bestaudio[acodec!=?mp4a.40.42]/worst[acodec!=?mp4a.40.42]/best"

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
    """Implements both VideoDownloader and SubtitleFetcher.

    yt-dlp is blocking, so every call runs in a worker thread.
    """

    def __init__(self, cookies_file: Path | None = None) -> None:
        if cookies_file is not None and not cookies_file.is_file():
            # A wrong path must not break YouTube and TikTok, which work without cookies.
            _log.warning("Cookies file %s not found, continuing without cookies", cookies_file)
            cookies_file = None
        self._cookies_file = cookies_file

    async def fetch_metadata(self, url: str) -> VideoMetadata:
        platform = detect_platform(url)
        info = await asyncio.to_thread(self._extract, url, {"skip_download": True}, False)
        return _to_metadata(info, url, platform)

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        detect_platform(url)
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        options = {
            "format": AUDIO_FORMAT,
            "outtmpl": str(target_dir / "%(id)s.%(ext)s"),
        }
        info = await asyncio.to_thread(self._extract, url, options, True)
        return Path(info["requested_downloads"][0]["filepath"])

    async def fetch_subtitle_text(self, track: SubtitleTrack) -> str:
        raw = await asyncio.to_thread(self._download_text, track.url)
        return subtitles_to_text(raw)

    def _options(self, extra: dict[str, Any]) -> dict[str, Any]:
        options = {**_BASE_OPTIONS, **extra}
        if self._cookies_file is not None:
            options["cookiefile"] = str(self._cookies_file)
        return options

    def _download_text(self, url: str) -> str:
        # Through yt-dlp, not a bare HTTP client: same cookies, headers and impersonation.
        try:
            with yt_dlp.YoutubeDL(self._options({})) as ydl:
                return ydl.urlopen(url).read().decode("utf-8", errors="replace")
        except (yt_dlp.networking.exceptions.RequestError, OSError) as error:
            raise SubtitlesUnavailableError(str(error)) from error

    def _extract(self, url: str, options: dict[str, Any], download: bool) -> dict[str, Any]:
        try:
            with yt_dlp.YoutubeDL(self._options(options)) as ydl:
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
        title=_real_title(info.get("title") or ""),
        description=info.get("description") or "",
        author=info.get("uploader") or info.get("channel") or info.get("creator"),
        duration_seconds=round(duration) if duration is not None else None,
        language=info.get("language"),
        subtitle_tracks=_subtitle_tracks(info),
    )


# Instagram posts have no titles: yt-dlp makes up "Video by <account>", which is not the dish
# and which the model would copy as the recipe title.
_MADE_UP_TITLE = re.compile(r"(?:video|reel|post) by \S+", re.IGNORECASE)


def _real_title(title: str) -> str:
    return "" if _MADE_UP_TITLE.fullmatch(title.strip()) else title


_TEXT_FORMATS = ("vtt", "srt")


def _text_format(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_ext = {item.get("ext"): item for item in formats if item.get("url")}
    return next((by_ext[ext] for ext in _TEXT_FORMATS if ext in by_ext), None)


def _subtitle_tracks(info: dict[str, Any]) -> tuple[SubtitleTrack, ...]:
    tracks: list[SubtitleTrack] = []
    for language, formats in (info.get("subtitles") or {}).items():
        if language == "live_chat":
            continue
        if chosen := _text_format(formats):
            tracks.append(SubtitleTrack(language, chosen["url"], chosen["ext"], automatic=False))

    # YouTube lists ~160 automatic tracks: the recognized speech ("en-orig") plus machine
    # translations of it. Only the original is worth reading.
    automatic = info.get("automatic_captions") or {}
    originals = [key for key in automatic if key.endswith("-orig")]
    if not originals and info.get("language") in automatic:
        originals = [info["language"]]
    for key in originals:
        if chosen := _text_format(automatic[key]):
            language = key.removesuffix("-orig")
            tracks.append(SubtitleTrack(language, chosen["url"], chosen["ext"], automatic=True))
    return tuple(tracks)
