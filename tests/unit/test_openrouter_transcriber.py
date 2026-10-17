import base64
import json
from pathlib import Path

import httpx
import pytest

from receipt.application.errors import TranscriptionError
from receipt.application.ports.transcriber import Transcript
from receipt.infrastructure.transcription import openrouter
from receipt.infrastructure.transcription.openrouter import OpenRouterTranscriber

MODELS = ["openai/whisper-large-v3-turbo", "openai/whisper-large-v3"]


async def fake_prepare(source: Path, target: Path) -> Path:
    target.write_bytes(b"compressed:" + source.read_bytes())
    return target


class Recorder:
    """Plays OpenRouter: answers each model with the next scripted response."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def bodies(self) -> list[dict[str, object]]:
        return [json.loads(request.content) for request in self.requests]


def make(recorder: Recorder, api_key: str | None = "sk-test") -> OpenRouterTranscriber:
    return OpenRouterTranscriber(
        api_key=api_key,
        models=MODELS,
        prepare_audio=fake_prepare,
        transport=httpx.MockTransport(recorder),
    )


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    return path


async def test_first_model_answers(audio: Path) -> None:
    recorder = Recorder(httpx.Response(200, json={"text": " Берём свёклу ", "usage": {}}))

    transcript = await make(recorder).transcribe(audio, language="ru")

    assert transcript == Transcript(text="Берём свёклу", model=MODELS[0])
    request = recorder.requests[0]
    assert request.url == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = recorder.bodies()[0]
    assert body["model"] == MODELS[0]
    assert body["language"] == "ru"
    assert body["input_audio"] == {
        "data": base64.b64encode(b"compressed:video").decode(),
        "format": "mp3",
    }


async def test_language_is_omitted_when_unknown(audio: Path) -> None:
    recorder = Recorder(httpx.Response(200, json={"text": "hi"}))

    await make(recorder).transcribe(audio)

    assert "language" not in recorder.bodies()[0]


@pytest.mark.parametrize(
    "first_failure",
    [
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
        httpx.Response(502, text="bad gateway"),
        httpx.Response(404, json={"error": {"message": "model not found"}}),
        httpx.Response(200, text="not json"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("no route"),
    ],
)
async def test_falls_back_to_the_next_model(
    audio: Path, first_failure: httpx.Response | Exception
) -> None:
    recorder = Recorder(first_failure, httpx.Response(200, json={"text": "Берём свёклу"}))

    transcript = await make(recorder).transcribe(audio)

    assert transcript == Transcript(text="Берём свёклу", model=MODELS[1])
    assert [body["model"] for body in recorder.bodies()] == MODELS


@pytest.mark.parametrize(
    ("status", "message"), [(401, "OPENROUTER_API_KEY"), (402, "нет кредитов")]
)
async def test_key_and_balance_problems_stop_at_once(
    audio: Path, status: int, message: str
) -> None:
    recorder = Recorder(httpx.Response(status, json={"error": {"message": "nope"}}))

    with pytest.raises(TranscriptionError, match=message):
        await make(recorder).transcribe(audio)

    assert len(recorder.requests) == 1


async def test_all_models_failing_lists_every_failure(audio: Path) -> None:
    recorder = Recorder(httpx.Response(503, text="busy"), httpx.ReadTimeout("slow"))

    with pytest.raises(TranscriptionError) as raised:
        await make(recorder).transcribe(audio)

    message = str(raised.value)
    assert f"{MODELS[0]}: HTTP 503" in message
    assert f"{MODELS[1]}: ReadTimeout" in message


async def test_empty_text_is_a_valid_answer(audio: Path) -> None:
    recorder = Recorder(httpx.Response(200, json={"text": ""}))

    transcript = await make(recorder).transcribe(audio)

    assert transcript.text == ""
    assert len(recorder.requests) == 1


async def test_without_api_key_nothing_is_sent(audio: Path) -> None:
    recorder = Recorder()

    with pytest.raises(TranscriptionError, match="OPENROUTER_API_KEY"):
        await make(recorder, api_key=None).transcribe(audio)

    assert recorder.requests == []


async def test_too_big_audio_is_rejected_before_upload(
    audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(openrouter, "MAX_AUDIO_BYTES", 5)
    recorder = Recorder()

    with pytest.raises(TranscriptionError, match="25 МБ"):
        await make(recorder).transcribe(audio)

    assert recorder.requests == []
