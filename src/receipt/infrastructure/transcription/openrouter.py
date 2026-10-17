import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from receipt.application.errors import TranscriptionError
from receipt.application.ports.transcriber import Transcript
from receipt.infrastructure.audio.ffmpeg import compress_for_speech

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# OpenRouter's limit for inline audio on most providers.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

# Waiting for the next model will not help: the key or the balance is the problem.
_FATAL_STATUSES = {
    401: "OpenRouter не принял ключ: проверьте OPENROUTER_API_KEY",
    402: "на балансе OpenRouter нет кредитов: распознавание речи платное",
}

type PrepareAudio = Callable[[Path, Path], Awaitable[Path]]


class OpenRouterTranscriber:
    """Speech-to-text through OpenRouter's /audio/transcriptions.

    ``models`` are tried in order: a timeout, rate limit or provider error moves on to the
    next one. A wrong key or an empty balance stops at once.
    """

    def __init__(
        self,
        api_key: str | None,
        models: Sequence[str],
        *,
        base_url: str = OPENROUTER_URL,
        timeout_seconds: float = 90,
        prepare_audio: PrepareAudio = compress_for_speech,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._models = list(models)
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._prepare_audio = prepare_audio
        self._transport = transport

    async def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript:
        if not self._api_key:
            raise TranscriptionError("Не задан OPENROUTER_API_KEY")
        if not self._models:
            raise TranscriptionError("Не задан список моделей STT_MODELS")

        audio = await self._read_prepared(audio_path)
        if len(audio) > MAX_AUDIO_BYTES:
            raise TranscriptionError("Аудио слишком длинное: больше 25 МБ даже после сжатия")
        body: dict[str, object] = {
            "input_audio": {"data": base64.b64encode(audio).decode(), "format": "mp3"},
        }
        if language:
            body["language"] = language

        failures: list[str] = []
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}", "X-Title": "Recipe Bot"},
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            for model in self._models:
                outcome = await self._try_model(client, model, body)
                if isinstance(outcome, Transcript):
                    return outcome
                logger.warning("Transcription with %s failed: %s", model, outcome)
                failures.append(f"{model}: {outcome}")
        raise TranscriptionError("Ни одна модель не распознала речь. " + "; ".join(failures))

    async def _read_prepared(self, audio_path: Path) -> bytes:
        with TemporaryDirectory(prefix="receipt-speech-") as directory:
            prepared = await self._prepare_audio(audio_path, Path(directory) / "speech.mp3")
            return await asyncio.to_thread(prepared.read_bytes)

    async def _try_model(
        self, client: httpx.AsyncClient, model: str, body: dict[str, object]
    ) -> Transcript | str:
        """The transcript, or why this model failed (then the next one is tried)."""
        try:
            response = await client.post("/audio/transcriptions", json={"model": model, **body})
        except httpx.HTTPError as error:
            return type(error).__name__
        if response.status_code in _FATAL_STATUSES:
            raise TranscriptionError(_FATAL_STATUSES[response.status_code])
        if not response.is_success:
            return f"HTTP {response.status_code} {response.text[:200]}"
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError):
            return f"неожиданный ответ: {response.text[:200]}"
        logger.info("Transcribed with %s", model)
        # Empty text is a valid answer: a video with music and no speech.
        return Transcript(text=(text or "").strip(), model=model)
