import logging
from dataclasses import dataclass

from receipt.application.cqrs import Query
from receipt.application.errors import SubtitlesUnavailableError
from receipt.application.ports.video_downloader import (
    SubtitleFetcher,
    SubtitleTrack,
    VideoDownloader,
    VideoMetadata,
)
from receipt.application.video.subtitles import choose_subtitle_track
from receipt.domain.source_text import SourceText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubtitleLanguages:
    """Languages to look for when the video's own language has no subtitles, in order."""

    preferred: tuple[str, ...] = ("ru", "en")


@dataclass(frozen=True)
class VideoText:
    video: VideoMetadata
    text: SourceText
    subtitle_track: SubtitleTrack | None


@dataclass(frozen=True)
class GetVideoText(Query[VideoText]):
    """Text of a video without downloading it: title, description and subtitles."""

    url: str


class GetVideoTextHandler:
    def __init__(
        self,
        downloader: VideoDownloader,
        subtitles: SubtitleFetcher,
        languages: SubtitleLanguages,
    ) -> None:
        self._downloader = downloader
        self._subtitles = subtitles
        self._languages = languages

    async def handle(self, request: GetVideoText) -> VideoText:
        video = await self._downloader.fetch_metadata(request.url)
        track = choose_subtitle_track(
            video.subtitle_tracks, self._languages.preferred, video.language
        )
        subtitles = ""
        if track is not None:
            try:
                subtitles = await self._subtitles.fetch_subtitle_text(track)
            except SubtitlesUnavailableError:
                # Not fatal: the audio can still be transcribed.
                logger.warning(
                    "Subtitles %s of %s could not be downloaded", track.language, video.url
                )
        return VideoText(
            video=video,
            text=SourceText(title=video.title, description=video.description, subtitles=subtitles),
            subtitle_track=track if subtitles else None,
        )
