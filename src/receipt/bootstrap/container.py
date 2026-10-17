"""Composition root: the only place that knows which adapter implements which port."""

from typing import Any

import punq

from receipt.application.behaviors import ErrorBehavior, LoggingBehavior
from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.application.ports.transcriber import Transcriber
from receipt.application.ports.video_downloader import SubtitleFetcher, VideoDownloader
from receipt.application.system.ping import Ping, PingHandler, PingStream, PingStreamHandler
from receipt.application.video.get_video_info import GetVideoInfo, GetVideoInfoHandler
from receipt.application.video.get_video_text import (
    GetVideoText,
    GetVideoTextHandler,
    SubtitleLanguages,
)
from receipt.application.video.get_video_transcript import (
    GetVideoTranscript,
    GetVideoTranscriptHandler,
)
from receipt.bootstrap.settings import Settings
from receipt.infrastructure.clock import SystemClock
from receipt.infrastructure.transcription.openrouter import OpenRouterTranscriber
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

HANDLERS: dict[type[Any], type[Any]] = {
    Ping: PingHandler,
    PingStream: PingStreamHandler,
    GetVideoInfo: GetVideoInfoHandler,
    GetVideoText: GetVideoTextHandler,
    GetVideoTranscript: GetVideoTranscriptHandler,
}


def build_container(settings: Settings | None = None) -> punq.Container:
    """Builds the container. Re-registering a service afterwards overrides it (used by tests)."""
    settings = settings or Settings()
    container = punq.Container()
    container.register(Settings, instance=settings)

    # Ports -> adapters. Clients holding connections (LLM, Chroma) will be singletons too.
    container.register(Clock, SystemClock, scope=punq.Scope.singleton)
    yt_dlp_adapter = YtDlpVideoDownloader(cookies_file=settings.ytdlp_cookies_file)
    container.register(VideoDownloader, instance=yt_dlp_adapter)
    container.register(SubtitleFetcher, instance=yt_dlp_adapter)
    container.register(
        SubtitleLanguages, instance=SubtitleLanguages(tuple(settings.subtitle_languages))
    )
    api_key = settings.openrouter_api_key
    container.register(
        Transcriber,
        instance=OpenRouterTranscriber(
            api_key=api_key.get_secret_value() if api_key else None,
            models=settings.stt_models,
        ),
    )

    # Handlers are transient: a fresh instance per request.
    for handler_type in HANDLERS.values():
        container.register(handler_type)

    container.register(
        Mediator,
        factory=lambda: Mediator(
            container.resolve,
            HANDLERS,
            behaviors=[LoggingBehavior(), ErrorBehavior()],
        ),
        scope=punq.Scope.singleton,
    )
    return container
