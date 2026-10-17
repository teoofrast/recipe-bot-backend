from datetime import datetime
from pathlib import Path

from receipt.application.ports.video_downloader import VideoMetadata
from receipt.domain.video import detect_platform


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeVideoDownloader:
    """Answers every link with the same video; raises ``error`` instead, if set."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def fetch_metadata(self, url: str) -> VideoMetadata:
        platform = detect_platform(url)
        if self.error is not None:
            raise self.error
        return VideoMetadata(
            url=url,
            platform=platform,
            video_id="abc123",
            title="Борщ за 30 минут",
            description="Свёкла 2 шт, капуста 300 г",
            author="chef",
            duration_seconds=59,
        )

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        if self.error is not None:
            raise self.error
        path = target_dir / "abc123.m4a"
        path.write_bytes(b"fake audio")
        return path
