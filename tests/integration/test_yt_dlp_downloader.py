"""Real downloads from the platforms. Run explicitly: ``uv run pytest -m integration``.

YouTube uses a fixed public video. TikTok and Instagram links come from environment variables
(their links expire and Instagram often needs cookies): TEST_TIKTOK_URL, TEST_INSTAGRAM_URL,
and YTDLP_COOKIES_FILE for Instagram cookies.
"""

import os
from pathlib import Path

import pytest

from receipt.domain.video import Platform
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

pytestmark = pytest.mark.integration

YOUTUBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", 19 s


def _cases() -> list[pytest.param]:
    cases = [pytest.param(YOUTUBE_URL, Platform.YOUTUBE, id="youtube")]
    for platform, variable in (
        (Platform.TIKTOK, "TEST_TIKTOK_URL"),
        (Platform.INSTAGRAM, "TEST_INSTAGRAM_URL"),
    ):
        url = os.environ.get(variable)
        marks = [] if url else [pytest.mark.skip(reason=f"{variable} is not set")]
        cases.append(pytest.param(url, platform, id=platform.value, marks=marks))
    return cases


@pytest.fixture
def downloader() -> YtDlpVideoDownloader:
    cookies = os.environ.get("YTDLP_COOKIES_FILE")
    return YtDlpVideoDownloader(cookies_file=Path(cookies) if cookies else None)


@pytest.mark.parametrize(("url", "platform"), _cases())
async def test_fetches_metadata_and_audio(
    downloader: YtDlpVideoDownloader, url: str, platform: Platform, tmp_path: Path
) -> None:
    metadata = await downloader.fetch_metadata(url)

    assert metadata.platform is platform
    assert metadata.video_id
    assert metadata.title or metadata.description

    audio = await downloader.download_audio(url, tmp_path)

    assert audio.parent == tmp_path
    assert audio.stat().st_size > 10_000
