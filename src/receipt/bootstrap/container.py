"""Composition root: the only place that knows which adapter implements which port."""

from typing import Any

import punq

from receipt.application.behaviors import ErrorBehavior, LoggingBehavior
from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.application.ports.video_downloader import VideoDownloader
from receipt.application.system.ping import Ping, PingHandler, PingStream, PingStreamHandler
from receipt.application.video.get_video_info import GetVideoInfo, GetVideoInfoHandler
from receipt.bootstrap.settings import Settings
from receipt.infrastructure.clock import SystemClock
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

HANDLERS: dict[type[Any], type[Any]] = {
    Ping: PingHandler,
    PingStream: PingStreamHandler,
    GetVideoInfo: GetVideoInfoHandler,
}


def build_container(settings: Settings | None = None) -> punq.Container:
    """Builds the container. Re-registering a service afterwards overrides it (used by tests)."""
    settings = settings or Settings()
    container = punq.Container()
    container.register(Settings, instance=settings)

    # Ports -> adapters. Clients holding connections (LLM, Chroma) will be singletons too.
    container.register(Clock, SystemClock, scope=punq.Scope.singleton)
    container.register(
        VideoDownloader,
        instance=YtDlpVideoDownloader(cookies_file=settings.ytdlp_cookies_file),
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
