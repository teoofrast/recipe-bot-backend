"""The real LangGraph import graph, over the app's use cases with fake adapters."""

import pytest
from langgraph.types import RetryPolicy

from receipt.application.errors import (
    LlmUnavailableError,
    VideoUnavailableError,
    VideoUnavailableReason,
)
from receipt.application.mediator import Mediator
from receipt.application.ports.import_pipeline import ImportOutcome, OutcomeKind
from receipt.application.ports.video_downloader import SubtitleTrack
from receipt.application.recipes.collection import GetRecipe
from receipt.application.recipes.import_recipe import ImportRecipe
from receipt.domain.import_job import ImportStatus
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource, fuller
from receipt.domain.video import Platform
from receipt.infrastructure.imports import langgraph_pipeline
from receipt.infrastructure.imports.langgraph_pipeline import LangGraphImportPipeline
from tests.fakes import (
    FakeFrameDescriber,
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
    video_downloader.subtitles = {"ru": "Берём свёклу, капусту и варим борщ"}

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


CAPTION = "Ингредиенты: свёкла 500 г, капуста 300 г, картофель 400 г"


async def test_a_caption_without_the_method_is_completed_from_the_speech(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    video_downloader.description = CAPTION
    recipe_extractor.method_in = "speech"

    outcome, stages = await run(pipeline)

    assert stages == [
        ImportStatus.READING,
        ImportStatus.EXTRACTING,
        ImportStatus.TRANSCRIBING,
        ImportStatus.EXTRACTING,
        ImportStatus.SAVING,
    ]
    assert len(transcriber.calls) == 1
    saved = recipe_repository.recipes[outcome.recipe_id]
    assert saved.recipe.steps == ("Нарежьте свёклу", "Сварите")
    assert saved.source_text.transcript == "Берём свёклу и капусту"


async def test_a_silent_video_keeps_the_caption_recipe(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    video_downloader.description = CAPTION
    recipe_extractor.method_in = "speech"
    transcriber.text = ""

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert len(transcriber.calls) == 1  # listened once, not in a loop
    assert stages.count(ImportStatus.WATCHING) == 1  # the frames did not help either
    assert recipe_repository.recipes[outcome.recipe_id].recipe.steps == ("Сварите",)


async def test_a_method_only_shown_is_taken_from_the_frames(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    frame_describer: FakeFrameDescriber,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    video_downloader.description = CAPTION
    recipe_extractor.method_in = "frames"
    frame_describer.text = "Повар режет свёклу и варит её"

    outcome, stages = await run(pipeline)

    assert stages == [
        ImportStatus.READING,
        ImportStatus.EXTRACTING,
        ImportStatus.TRANSCRIBING,  # music only: nothing told
        ImportStatus.EXTRACTING,
        ImportStatus.WATCHING,
        ImportStatus.EXTRACTING,
        ImportStatus.SAVING,
    ]
    saved = recipe_repository.recipes[outcome.recipe_id]
    assert saved.recipe.steps == ("Нарежьте свёклу", "Сварите")
    assert saved.source_text.frames == "Повар режет свёклу и варит её"
    [(video_path, existed)] = frame_describer.calls
    assert existed
    assert not video_path.parent.exists()  # the downloaded video is deleted


async def test_with_subtitles_the_frames_are_next(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
) -> None:
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу, капусту и варим борщ"}
    recipe_extractor.method_in = "frames"

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert transcriber.calls == []
    assert ImportStatus.WATCHING in stages


async def test_frames_that_cannot_be_described_do_not_fail_the_import(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    frame_describer: FakeFrameDescriber,
    recipe_extractor: FakeRecipeExtractor,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    video_downloader.description = CAPTION
    recipe_extractor.method_in = "frames"
    frame_describer.error = LlmUnavailableError("Ни одна языковая модель не ответила")

    outcome, _ = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert recipe_repository.recipes[outcome.recipe_id].recipe.steps == ("Сварите",)


def test_the_fuller_recipe_wins() -> None:
    def with_steps(*steps: str) -> Recipe:
        return Recipe(
            "Борщ", (Ingredient("свёкла"),), steps, RecipeSource("u", Platform.YOUTUBE, "v")
        )

    one, two, none = with_steps("Сварите"), with_steps("Нарежьте", "Сварите"), with_steps()
    assert fuller(one, two) is two
    assert fuller(one, none) is one  # the model lost the method this time
    assert fuller(one, None) is one
    assert fuller(None, two) is two
    assert fuller(None, None) is None


async def test_subtitles_are_not_listened_to_again(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
) -> None:
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу, капусту и варим борщ"}
    recipe_extractor.method_in = "speech"

    outcome, _ = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert transcriber.calls == []


async def test_a_full_caption_needs_no_speech(
    pipeline: LangGraphImportPipeline,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
) -> None:
    video_downloader.description = CAPTION

    outcome, stages = await run(pipeline)

    assert outcome.kind is OutcomeKind.SAVED
    assert ImportStatus.TRANSCRIBING not in stages
    assert transcriber.calls == []


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
    assert len(transcriber.calls) == 1  # the speech was heard once, before the extraction
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
        "extract -.-> transcribe",
        "extract -.-> no_recipe",
        "extract -.-> watch",
        "watch --> extract",
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
