from datetime import datetime
from pathlib import Path

from receipt.application.ports.transcriber import Transcript
from receipt.application.ports.video_downloader import SubtitleTrack, VideoMetadata
from receipt.domain.video import detect_platform


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeVideoDownloader:
    """Answers every link with the same video; raises ``error`` instead, if set.

    Also plays SubtitleFetcher: ``subtitles`` maps a track language to its text, and
    ``subtitles_error`` is raised for every track if set.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.description = "Свёкла 2 шт, капуста 300 г"
        self.subtitle_tracks: tuple[SubtitleTrack, ...] = ()
        self.subtitles: dict[str, str] = {}
        self.subtitles_error: Exception | None = None

    async def fetch_metadata(self, url: str) -> VideoMetadata:
        platform = detect_platform(url)
        if self.error is not None:
            raise self.error
        return VideoMetadata(
            url=url,
            platform=platform,
            video_id="abc123",
            title="Борщ за 30 минут",
            description=self.description,
            author="chef",
            duration_seconds=59,
            language="ru",
            subtitle_tracks=self.subtitle_tracks,
        )

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        if self.error is not None:
            raise self.error
        path = target_dir / "abc123.m4a"
        path.write_bytes(b"fake audio")
        return path

    async def fetch_subtitle_text(self, track: SubtitleTrack) -> str:
        if self.subtitles_error is not None:
            raise self.subtitles_error
        return self.subtitles[track.language]


class FakeTranscriber:
    """Remembers what it was given; answers with ``text`` or raises ``error``."""

    def __init__(self) -> None:
        self.text = "Берём свёклу и капусту"
        self.error: Exception | None = None
        self.calls: list[tuple[Path, bool, str | None]] = []

    async def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript:
        # Whether the file still exists at the moment of transcription.
        self.calls.append((audio_path, audio_path.exists(), language))
        if self.error is not None:
            raise self.error
        return Transcript(text=self.text, model="fake/whisper")
