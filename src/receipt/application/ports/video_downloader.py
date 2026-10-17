from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from receipt.domain.video import Platform


@dataclass(frozen=True)
class VideoMetadata:
    url: str
    platform: Platform
    video_id: str
    title: str
    description: str
    author: str | None
    duration_seconds: int | None


class VideoDownloader(Protocol):
    """Gets a video from its platform. Raises UnsupportedUrlError or VideoUnavailableError.

    Metadata and audio are separate calls: the recipe is often already in the description
    or subtitles, and then the audio is never downloaded.
    """

    async def fetch_metadata(self, url: str) -> VideoMetadata: ...

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        """Downloads only the audio track into ``target_dir`` and returns the file path."""
        ...
