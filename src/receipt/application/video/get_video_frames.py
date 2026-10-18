from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from receipt.application.cqrs import Query
from receipt.application.ports.frame_describer import FrameDescriber, FramesDescription
from receipt.application.ports.video_downloader import VideoDownloader


@dataclass(frozen=True)
class GetVideoFrames(Query[FramesDescription]):
    """What a video shows without words: downloads it, looks at the frames, deletes it."""

    url: str


class GetVideoFramesHandler:
    def __init__(self, downloader: VideoDownloader, describer: FrameDescriber) -> None:
        self._downloader = downloader
        self._describer = describer

    async def handle(self, request: GetVideoFrames) -> FramesDescription:
        with TemporaryDirectory(prefix="receipt-video-") as directory:
            video = await self._downloader.download_video(request.url, Path(directory))
            return await self._describer.describe(video)
