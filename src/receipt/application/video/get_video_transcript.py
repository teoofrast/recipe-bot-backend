from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from receipt.application.cqrs import Query
from receipt.application.ports.transcriber import Transcriber, Transcript
from receipt.application.ports.video_downloader import VideoDownloader


@dataclass(frozen=True)
class GetVideoTranscript(Query[Transcript]):
    """Speech of a video as text: downloads the audio, transcribes it, deletes the audio."""

    url: str
    language: str | None = None


class GetVideoTranscriptHandler:
    def __init__(self, downloader: VideoDownloader, transcriber: Transcriber) -> None:
        self._downloader = downloader
        self._transcriber = transcriber

    async def handle(self, request: GetVideoTranscript) -> Transcript:
        with TemporaryDirectory(prefix="receipt-audio-") as directory:
            audio = await self._downloader.download_audio(request.url, Path(directory))
            return await self._transcriber.transcribe(audio, request.language)
