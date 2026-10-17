from pathlib import Path
from typing import Any

import pytest
import yt_dlp

from receipt.application.errors import VideoUnavailableError, VideoUnavailableReason
from receipt.domain.video import Platform, UnsupportedUrlError
from receipt.infrastructure.video.yt_dlp_downloader import (
    YtDlpVideoDownloader,
    classify_download_error,
)

YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123"

INFO: dict[str, Any] = {
    "id": "abc123",
    "title": "Борщ",
    "description": "Свёкла, капуста",
    "uploader": "chef",
    "duration": 59.4,
    "webpage_url": YOUTUBE_URL,
}


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL: records options, returns ``result`` or raises it."""

    calls: list[dict[str, Any]]
    result: dict[str, Any] | Exception

    def __init__(self, options: dict[str, Any]) -> None:
        FakeYoutubeDL.calls.append(options)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        if isinstance(FakeYoutubeDL.result, Exception):
            raise FakeYoutubeDL.result
        return FakeYoutubeDL.result


@pytest.fixture
def fake_ytdl(monkeypatch: pytest.MonkeyPatch) -> type[FakeYoutubeDL]:
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.result = INFO
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


async def test_fetch_metadata_maps_yt_dlp_info(fake_ytdl: type[FakeYoutubeDL]) -> None:
    metadata = await YtDlpVideoDownloader().fetch_metadata(YOUTUBE_URL)

    assert metadata.platform is Platform.YOUTUBE
    assert metadata.video_id == "abc123"
    assert metadata.title == "Борщ"
    assert metadata.description == "Свёкла, капуста"
    assert metadata.author == "chef"
    assert metadata.duration_seconds == 59
    assert fake_ytdl.calls[0]["skip_download"] is True
    assert fake_ytdl.calls[0]["noplaylist"] is True


async def test_fetch_metadata_tolerates_missing_fields(fake_ytdl: type[FakeYoutubeDL]) -> None:
    fake_ytdl.result = {"id": 42, "channel": "chef-channel"}

    metadata = await YtDlpVideoDownloader().fetch_metadata(YOUTUBE_URL)

    assert metadata.video_id == "42"
    assert metadata.title == ""
    assert metadata.description == ""
    assert metadata.author == "chef-channel"
    assert metadata.duration_seconds is None
    assert metadata.url == YOUTUBE_URL


async def test_cookies_file_is_passed_to_yt_dlp(fake_ytdl: type[FakeYoutubeDL]) -> None:
    await YtDlpVideoDownloader(cookies_file=Path("/cookies/instagram.txt")).fetch_metadata(
        YOUTUBE_URL
    )

    assert fake_ytdl.calls[0]["cookiefile"] == "/cookies/instagram.txt"


async def test_download_audio_returns_downloaded_file(
    fake_ytdl: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    target = tmp_path / "audio"
    fake_ytdl.result = {**INFO, "requested_downloads": [{"filepath": str(target / "abc.webm")}]}

    path = await YtDlpVideoDownloader().download_audio(YOUTUBE_URL, target)

    assert path == target / "abc.webm"
    assert target.is_dir()
    assert fake_ytdl.calls[0]["format"] == "bestaudio/best"
    assert fake_ytdl.calls[0]["outtmpl"] == str(target / "%(id)s.%(ext)s")


async def test_unsupported_link_fails_before_calling_yt_dlp(
    fake_ytdl: type[FakeYoutubeDL],
) -> None:
    with pytest.raises(UnsupportedUrlError):
        await YtDlpVideoDownloader().fetch_metadata("https://vimeo.com/123")

    assert fake_ytdl.calls == []


async def test_playlist_is_rejected(fake_ytdl: type[FakeYoutubeDL]) -> None:
    fake_ytdl.result = {"_type": "playlist", "id": "PL1", "entries": []}

    with pytest.raises(UnsupportedUrlError, match="плейлист"):
        await YtDlpVideoDownloader().fetch_metadata("https://www.youtube.com/playlist?list=PL1")


async def test_download_error_becomes_video_unavailable(fake_ytdl: type[FakeYoutubeDL]) -> None:
    fake_ytdl.result = yt_dlp.utils.DownloadError("ERROR: [youtube] abc123: Private video")

    with pytest.raises(VideoUnavailableError) as raised:
        await YtDlpVideoDownloader().fetch_metadata(YOUTUBE_URL)

    assert raised.value.reason is VideoUnavailableReason.PRIVATE
    assert "Private video" in raised.value.detail


async def test_yt_dlp_unsupported_url_becomes_unsupported_url_error(
    fake_ytdl: type[FakeYoutubeDL],
) -> None:
    fake_ytdl.result = yt_dlp.utils.DownloadError("ERROR: Unsupported URL: https://youtube.com/")

    with pytest.raises(UnsupportedUrlError):
        await YtDlpVideoDownloader().fetch_metadata("https://youtube.com/")


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (
            "ERROR: [youtube] x: Private video. Sign in if you've been granted access",
            VideoUnavailableReason.PRIVATE,
        ),
        (
            "ERROR: [Instagram] x: Requested content is not available, rate-limit reached "
            "or login required. Use --cookies",
            VideoUnavailableReason.LOGIN_REQUIRED,
        ),
        (
            "ERROR: [youtube] x: Sign in to confirm you're not a bot",
            VideoUnavailableReason.LOGIN_REQUIRED,
        ),
        (
            "ERROR: [youtube] x: The uploader has not made this video available in your country",
            VideoUnavailableReason.GEO_BLOCKED,
        ),
        ("ERROR: [youtube] x: Video unavailable", VideoUnavailableReason.NOT_FOUND),
        ("ERROR: [TikTok] x: HTTP Error 404: Not Found", VideoUnavailableReason.NOT_FOUND),
        ("ERROR: [youtube] x: Connection reset by peer", VideoUnavailableReason.UNKNOWN),
    ],
)
def test_classify_download_error(message: str, reason: VideoUnavailableReason) -> None:
    assert classify_download_error(message) is reason
