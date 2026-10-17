"""Real subtitles from YouTube. Run explicitly: ``uv run pytest -m integration``."""

import pytest

from receipt.application.video.get_video_text import (
    GetVideoText,
    GetVideoTextHandler,
    SubtitleLanguages,
)
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

pytestmark = pytest.mark.integration

# Has human-made English subtitles and automatic ones ("en-orig").
RICK_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


async def test_youtube_video_with_subtitles_gives_clean_text_without_whisper() -> None:
    adapter = YtDlpVideoDownloader()
    handler = GetVideoTextHandler(adapter, adapter, SubtitleLanguages())

    result = await handler.handle(GetVideoText(url=RICK_URL))

    assert result.subtitle_track is not None
    assert not result.subtitle_track.automatic
    assert not result.text.needs_transcription
    subtitles = result.text.subtitles.lower()
    assert "never gonna give you up" in subtitles
    assert "-->" not in subtitles
    assert "<" not in subtitles


async def test_automatic_captions_are_cleaned_of_rolling_repeats() -> None:
    adapter = YtDlpVideoDownloader()
    video = await adapter.fetch_metadata(RICK_URL)
    automatic = next(track for track in video.subtitle_tracks if track.automatic)

    text = await adapter.fetch_subtitle_text(automatic)

    assert automatic.language == "en"
    assert text.startswith("We're no strangers to love")
    assert text.count("We're no strangers to love") == 1
