from dataclasses import dataclass

from receipt.application.cqrs import Query
from receipt.application.ports.video_downloader import VideoDownloader, VideoMetadata


@dataclass(frozen=True)
class GetVideoInfo(Query[VideoMetadata]):
    """Metadata of a video by its link, without downloading it. Used to check links by hand."""

    url: str


class GetVideoInfoHandler:
    def __init__(self, downloader: VideoDownloader) -> None:
        self._downloader = downloader

    async def handle(self, request: GetVideoInfo) -> VideoMetadata:
        return await self._downloader.fetch_metadata(request.url)
