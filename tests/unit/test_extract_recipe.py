import pytest

from receipt.application.mediator import Mediator
from receipt.application.ports.video_downloader import SubtitleTrack
from receipt.application.recipes.extract_recipe import ExtractRecipe
from receipt.domain.recipe import RecipeSource
from receipt.domain.video import Platform
from receipt.presentation.cli.app import main
from tests.fakes import FakeRecipeExtractor, FakeTranscriber, FakeVideoDownloader

URL = "https://www.youtube.com/watch?v=abc123"
RU_AUTO = SubtitleTrack(language="ru", url="https://subs/ru", ext="vtt", automatic=True)


async def test_recipe_from_subtitles_without_transcription(
    mediator: Mediator,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    recipe_extractor: FakeRecipeExtractor,
) -> None:
    video_downloader.description = "Подписывайтесь!"
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу и капусту"}

    draft = await mediator.send(ExtractRecipe(url=URL))

    assert draft.recipe is not None
    assert draft.recipe.title == "Борщ"
    assert draft.text.subtitles == "Берём свёклу и капусту"
    assert transcriber.calls == []
    [(_, source)] = recipe_extractor.calls
    assert source == RecipeSource(
        url=URL, platform=Platform.YOUTUBE, video_id="abc123", author="chef"
    )


async def test_speech_is_transcribed_when_text_is_not_enough(
    mediator: Mediator, video_downloader: FakeVideoDownloader, transcriber: FakeTranscriber
) -> None:
    video_downloader.description = "Рецепт в видео 👇"

    draft = await mediator.send(ExtractRecipe(url=URL))

    assert draft.text.transcript == "Берём свёклу и капусту"
    assert draft.recipe is not None
    [(_, _, language)] = transcriber.calls
    assert language == "ru"  # the video's language is passed as a hint


async def test_no_recipe(
    mediator: Mediator, video_downloader: FakeVideoDownloader, transcriber: FakeTranscriber
) -> None:
    video_downloader.description = "Мой день 👋"
    transcriber.text = "Привет, сегодня гуляем в парке"

    draft = await mediator.send(ExtractRecipe(url=URL))

    assert draft.recipe is None


def test_cli_extract_prints_the_recipe(
    mediator: Mediator, video_downloader: FakeVideoDownloader, capsys: pytest.CaptureFixture[str]
) -> None:
    video_downloader.description = "Свёкла 2 шт, капуста 300 г, морковь 1 шт"

    main(["extract", URL], mediator)

    out = capsys.readouterr().out
    assert "Текст из: описание" in out
    assert "Борщ" in out
    assert "• свёкла — 2 шт" in out
    assert "1. Сварите" in out
    assert f"Источник: {URL} (youtube, chef)" in out


def test_cli_extract_says_when_there_is_no_recipe(
    mediator: Mediator,
    video_downloader: FakeVideoDownloader,
    transcriber: FakeTranscriber,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video_downloader.description = "Мой день"
    transcriber.text = ""

    main(["extract", URL], mediator)

    assert "Рецепта в видео нет." in capsys.readouterr().out
