"""The real LangGraph import graph, over the app's use cases with fake adapters."""

import pytest
from langgraph.types import RetryPolicy

from receipt.application.errors import VideoUnavailableError, VideoUnavailableReason
from receipt.application.mediator import Mediator
from receipt.application.ports.import_pipeline import ImportOutcome, OutcomeKind
from receipt.application.ports.video_downloader import SubtitleTrack
from receipt.application.recipes.collection import GetRecipe
from receipt.application.recipes.import_recipe import ImportRecipe
from receipt.domain.import_job import ImportStatus
from receipt.infrastructure.imports import langgraph_pipeline
from receipt.infrastructure.imports.langgraph_pipeline import LangGraphImportPipeline
from tests.fakes import (
    FakeRecipeExtractor,
    FakeRecipeIndex,
    FakeTranscriber,
    FakeVideoDownloader,
    InMemoryRecipeRepository,
)

URL = "https://www.youtube.com/watch?v=abc123"
RU_AUTO = SubtitleTrack(language="ru", url="https://subs/ru", ext="vtt", automatic=True)


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    fast = RetryPolicy(
        max_attempts=3,
        initial_interval=0.01,
        jitter=False,
        retry_on=langgraph_pipeline.is_transient,
    )
    monkeypatch.setattr(langgraph_pipeline, "NETWORK_RETRY", fast)


@pytest.fixture
def pipeline(
    mediator: Mediator,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
) -> LangGraphImportPipeline:
    return LangGraphImportPipeline(mediator, recipe_extractor, recipe_repository)


async def run(pipeline: LangGraphImportPipeline) -> tuple[ImportOutcome, list[ImportStatus]]:
    stages: list[ImportStatus] = []

    async def on_stage(status: ImportStatus) -> None:
        stages.append(status)

    return await pipeline.run(URL, on_stage), stages


async def test_subtitles_path_saves_and_indexes_without_transcription(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_index: FakeRecipeIndex,
) -> None:
    video_downloader.description = "Подписывайтесь!"
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу и капусту"}

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert stages == [ImportStatus.READING, ImportStatus.EXTRACTING, ImportStatus.SAVING]
    assert transcriber.calls == []
    assert list(recipe_index.documents) == [outcome.recipe_id]


async def test_speech_path_transcribes_first(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
) -> None:
    video_downloader.description = "Рецепт в видео 👇"

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert stages == [
        ImportStatus.READING,
        ImportStatus.TRANSCRIBING,
        ImportStatus.EXTRACTING,
        ImportStatus.SAVING,
    ]
    [(_, _, language)] = transcriber.calls
    assert language == "ru"


async def test_a_saved_video_stops_before_the_llm(
    pipeline: LangGraphImportPipeline, recipe_extractor: FakeRecipeExtractor
) -> None:
    first, _ = await run(pipeline)
    calls = len(recipe_extractor.calls)

    again, stages = await run(pipeline)

    assert again == ImportOutcome(OutcomeKind.ALREADY_SAVED, first.recipe_id)
    assert stages == [ImportStatus.READING]
    assert len(recipe_extractor.calls) == calls


async def test_no_recipe_is_not_saved(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    video_downloader.description = "Мой день 👋"
    transcriber.text = "Гуляем в парке"

    outcome, stages = await run(pipeline)

    assert outcome == ImportOutcome(OutcomeKind.NO_RECIPE)
    assert ImportStatus.SAVING not in stages
    assert recipe_repository.recipes == {}


async def test_a_platform_hiccup_is_retried(
    pipeline: LangGraphImportPipeline, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.transient_failures = 2

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert stages[:3] == [ImportStatus.READING] * 3


async def test_a_private_video_is_not_retried(
    pipeline: LangGraphImportPipeline, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.error = VideoUnavailableError(VideoUnavailableReason.PRIVATE, "Private video")

    with pytest.raises(VideoUnavailableError):
        await run(pipeline)


def test_the_graph_has_the_designed_shape(pipeline: LangGraphImportPipeline) -> None:
    mermaid = pipeline.mermaid()

    for edge in (
        "__start__ --> read_video",
        "read_video --> check_saved",
        "check_saved -.-> transcribe",
        "check_saved -.-> extract",
        "transcribe --> extract",
        "extract -.-> save",
        "save --> __end__",
    ):
        assert edge in mermaid


async def test_import_through_the_mediator_ends_with_a_recipe_in_the_collection(
    mediator: Mediator,
) -> None:
    job = await mediator.send(ImportRecipe(url=URL))

    assert job.status is ImportStatus.DONE
    assert job.recipe_id is not None
    saved = await mediator.send(GetRecipe(recipe_id=job.recipe_id))
    assert saved.recipe.title == "Борщ"
