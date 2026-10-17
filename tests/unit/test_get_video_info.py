import pytest

from receipt.application.errors import VideoUnavailableError, VideoUnavailableReason
from receipt.application.mediator import Mediator
from receipt.application.video.get_video_info import GetVideoInfo
from receipt.domain.video import Platform, UnsupportedUrlError
from receipt.presentation.cli.app import main
from tests.fakes import FakeVideoDownloader

URL = "https://www.instagram.com/reel/Cabc123/"


async def test_get_video_info_returns_metadata(mediator: Mediator) -> None:
    video = await mediator.send(GetVideoInfo(url=URL))

    assert video.platform is Platform.INSTAGRAM
    assert video.title == "Борщ за 30 минут"


async def test_unsupported_link_error_reaches_the_caller_as_is(mediator: Mediator) -> None:
    with pytest.raises(UnsupportedUrlError):
        await mediator.send(GetVideoInfo(url="https://vimeo.com/1"))


def test_cli_video_info_prints_metadata(
    mediator: Mediator, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["video-info", URL], mediator)

    out = capsys.readouterr().out
    assert "Платформа:    instagram" in out
    assert "Название:     Борщ за 30 минут" in out
    assert "Свёкла 2 шт, капуста 300 г" in out


def test_cli_video_info_explains_errors_and_exits_with_1(
    mediator: Mediator,
    video_downloader: FakeVideoDownloader,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video_downloader.error = VideoUnavailableError(
        VideoUnavailableReason.LOGIN_REQUIRED, "login required. Use --cookies"
    )

    with pytest.raises(SystemExit) as exited:
        main(["video-info", URL], mediator)

    assert exited.value.code == 1
    err = capsys.readouterr().err
    assert "требует входа в аккаунт" in err
    assert "login required" in err
