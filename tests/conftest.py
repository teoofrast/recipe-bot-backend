from datetime import UTC, datetime

import punq
import pytest

from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.application.ports.recipe_extractor import RecipeExtractor
from receipt.application.ports.recipe_index import RecipeIndex
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.application.ports.transcriber import Transcriber
from receipt.application.ports.video_downloader import SubtitleFetcher, VideoDownloader
from receipt.bootstrap.container import build_container
from receipt.bootstrap.settings import Settings
from tests.fakes import (
    FakeClock,
    FakeRecipeExtractor,
    FakeRecipeIndex,
    FakeTranscriber,
    FakeVideoDownloader,
    InMemoryRecipeRepository,
)

FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def video_downloader() -> FakeVideoDownloader:
    return FakeVideoDownloader()


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def recipe_extractor() -> FakeRecipeExtractor:
    return FakeRecipeExtractor()


@pytest.fixture
def recipe_repository() -> InMemoryRecipeRepository:
    return InMemoryRecipeRepository()


@pytest.fixture
def recipe_index() -> FakeRecipeIndex:
    return FakeRecipeIndex()


@pytest.fixture
def container(
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
    recipe_index: FakeRecipeIndex,
) -> punq.Container:
    """Production wiring with external adapters replaced by fakes."""
    container = build_container(Settings(_env_file=None))
    container.register(Clock, instance=FakeClock(FIXED_NOW))
    container.register(VideoDownloader, instance=video_downloader)
    container.register(SubtitleFetcher, instance=video_downloader)
    container.register(Transcriber, instance=transcriber)
    container.register(RecipeExtractor, instance=recipe_extractor)
    container.register(RecipeRepository, instance=recipe_repository)
    container.register(RecipeIndex, instance=recipe_index)
    return container


@pytest.fixture
def mediator(container: punq.Container) -> Mediator:
    return container.resolve(Mediator)
