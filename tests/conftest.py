from datetime import UTC, datetime

import punq
import pytest

from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.application.ports.video_downloader import SubtitleFetcher, VideoDownloader
from receipt.bootstrap.container import build_container
from receipt.bootstrap.settings import Settings
from tests.fakes import FakeClock, FakeVideoDownloader

FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def video_downloader() -> FakeVideoDownloader:
    return FakeVideoDownloader()


@pytest.fixture
def container(video_downloader: FakeVideoDownloader) -> punq.Container:
    """Production wiring with external adapters replaced by fakes."""
    container = build_container(Settings(_env_file=None))
    container.register(Clock, instance=FakeClock(FIXED_NOW))
    container.register(VideoDownloader, instance=video_downloader)
    container.register(SubtitleFetcher, instance=video_downloader)
    return container


@pytest.fixture
def mediator(container: punq.Container) -> Mediator:
    return container.resolve(Mediator)
