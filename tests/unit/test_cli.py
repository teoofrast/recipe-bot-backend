import pytest

from receipt.application.mediator import Mediator
from receipt.presentation.cli.app import main


def test_ping_prints_pong(mediator: Mediator, capsys: pytest.CaptureFixture[str]) -> None:
    main(["ping"], mediator)

    assert capsys.readouterr().out == "pong at 2026-01-01T12:00:00+00:00\n"


def test_ping_stream_prints_each_chunk(
    mediator: Mediator, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["ping-stream", "--count", "2"], mediator)

    assert capsys.readouterr().out.splitlines() == [
        "pong 1 at 2026-01-01T12:00:00+00:00",
        "pong 2 at 2026-01-01T12:00:00+00:00",
    ]
