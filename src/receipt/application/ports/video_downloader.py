from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from receipt.domain.video import Platform


@dataclass(frozen=True)
class SubtitleTrack:
    language: str
    url: str
    ext: str
    automatic: bool


@dataclass(frozen=True)
class VideoMetadata:
    url: str
    platform: Platform
    video_id: str
    title: str
    description: str
    author: str | None
    duration_seconds: int | None
    language: str | None = None
    # Human-made subtitles and the platform's own speech recognition in the original
    # language. Machine translations are not included.
    subtitle_tracks: tuple[SubtitleTrack, ...] = ()


class VideoDownloader(Protocol):
    """Gets a video from its platform. Raises UnsupportedUrlError or VideoUnavailableError.

    Metadata and audio are separate calls: the recipe is often already in the description
    or subtitles, and then the audio is never downloaded.
    """

    async def fetch_metadata(self, url: str) -> VideoMetadata: ...

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        """Downloads only the audio track into ``target_dir`` and returns the file path."""
        ...


class SubtitleFetcher(Protocol):
    async def fetch_subtitle_text(self, track: SubtitleTrack) -> str:
        """Plain text of the track, without timings or repeats. Raises SubtitlesUnavailableError."""
        ...
