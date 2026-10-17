import pytest

from receipt.application.errors import TranscriptionError
from receipt.application.mediator import Mediator
from receipt.application.ports.transcriber import Transcript
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.presentation.cli.app import main
from tests.fakes import FakeTranscriber

URL = "https://www.instagram.com/reel/Cabc123/"


async def test_audio_is_downloaded_transcribed_and_deleted(
    mediator: Mediator, transcriber: FakeTranscriber
) -> None:
    transcript = await mediator.send(GetVideoTranscript(url=URL, language="ru"))

    assert transcript == Transcript(text="Берём свёклу и капусту", model="fake/whisper")
    [(audio_path, existed, language)] = transcriber.calls
    assert existed
    assert language == "ru"
    assert not audio_path.exists()
    assert not audio_path.parent.exists()


async def test_audio_is_deleted_when_transcription_fails(
    mediator: Mediator, transcriber: FakeTranscriber
) -> None:
    transcriber.error = TranscriptionError("нет кредитов")

    with pytest.raises(TranscriptionError):
        await mediator.send(GetVideoTranscript(url=URL))

    [(audio_path, _, _)] = transcriber.calls
    assert not audio_path.parent.exists()


def test_cli_transcribe_prints_model_and_text(
    mediator: Mediator, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["transcribe", URL, "--language", "ru"], mediator)

    out = capsys.readouterr().out
    assert "Модель: fake/whisper" in out
    assert "Берём свёклу и капусту" in out


def test_cli_transcribe_shows_when_there_is_no_speech(
    mediator: Mediator, transcriber: FakeTranscriber, capsys: pytest.CaptureFixture[str]
) -> None:
    transcriber.text = ""

    main(["transcribe", URL], mediator)

    assert "(речи нет)" in capsys.readouterr().out
