import pytest

from receipt.application.errors import SubtitlesUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.ports.video_downloader import SubtitleTrack
from receipt.application.video.get_video_text import GetVideoText
from receipt.presentation.cli.app import main
from tests.fakes import FakeVideoDownloader

URL = "https://www.youtube.com/watch?v=abc123"
RU_AUTO = SubtitleTrack(language="ru", url="https://subs/ru", ext="vtt", automatic=True)
EN_MANUAL = SubtitleTrack(language="en", url="https://subs/en", ext="vtt", automatic=False)


async def test_text_with_subtitles_does_not_need_transcription(
    mediator: Mediator, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.description = "Подписывайтесь!"
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу, капусту и варим борщ"}

    result = await mediator.send(GetVideoText(url=URL))

    assert result.subtitle_track == RU_AUTO
    assert result.text.subtitles == "Берём свёклу, капусту и варим борщ"
    assert result.text.title == "Борщ за 30 минут"
    assert not result.text.needs_transcription


async def test_preferred_track_is_chosen(
    mediator: Mediator, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.subtitle_tracks = (RU_AUTO, EN_MANUAL)
    video_downloader.subtitles = {"ru": "по-русски", "en": "in English"}

    result = await mediator.send(GetVideoText(url=URL))

    # The video is in Russian, but human-made subtitles beat automatic ones.
    assert result.subtitle_track == EN_MANUAL


async def test_without_subtitles_and_ingredients_transcription_is_needed(
    mediator: Mediator, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.description = "Рецепт в видео 👇"

    result = await mediator.send(GetVideoText(url=URL))

    assert result.subtitle_track is None
    assert result.text.needs_transcription


async def test_failed_subtitle_download_falls_back_to_transcription(
    mediator: Mediator, video_downloader: FakeVideoDownloader
) -> None:
    video_downloader.description = "Рецепт в видео 👇"
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles_error = SubtitlesUnavailableError("HTTP 429")

    result = await mediator.send(GetVideoText(url=URL))

    assert result.subtitle_track is None
    assert result.text.subtitles == ""
    assert result.text.needs_transcription


def test_cli_video_text_prints_source_and_text(
    mediator: Mediator,
    video_downloader: FakeVideoDownloader,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video_downloader.subtitle_tracks = (RU_AUTO,)
    video_downloader.subtitles = {"ru": "Берём свёклу, капусту и варим борщ"}

    main(["video-text", URL], mediator)

    out = capsys.readouterr().out
    assert "Субтитры:              ru (автоматические)" in out
    assert "Нужна транскрибация:   нет" in out
    assert "Субтитры:\nБерём свёклу" in out
