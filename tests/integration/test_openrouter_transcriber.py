"""Real speech-to-text through OpenRouter. Costs fractions of a cent.

Run explicitly: ``uv run pytest -m integration``. The key and STT_MODELS come from the
environment or .env, like in the app. Each model is checked separately, to compare them.
"""

import asyncio
import time
from pathlib import Path

import pytest

from receipt.bootstrap.settings import Settings
from receipt.infrastructure.transcription.openrouter import OpenRouterTranscriber
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

SETTINGS = Settings()
API_KEY = SETTINGS.openrouter_api_key.get_secret_value() if SETTINGS.openrouter_api_key else None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(API_KEY is None, reason="OPENROUTER_API_KEY is not set"),
]

# 19 s: "...the cool thing about these guys is that they have really, really, really long trunks"
ZOO_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.fixture(scope="module")
def zoo_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("zoo")
    return asyncio.run(YtDlpVideoDownloader().download_audio(ZOO_URL, target))


@pytest.mark.parametrize("model", SETTINGS.stt_models)
async def test_transcribes_speech(model: str, zoo_audio: Path) -> None:
    transcriber = OpenRouterTranscriber(api_key=API_KEY, models=[model])

    started = time.perf_counter()
    transcript = await transcriber.transcribe(zoo_audio, language="en")
    elapsed = time.perf_counter() - started

    print(f"\n{model}: {elapsed:.1f} s: {transcript.text}")
    assert transcript.model == model
    # Smaller models mishear single words on this 2005 recording ("long fronts" instead of
    # "long trunks"), so only the gist is checked; the printed text is for comparing models.
    text = transcript.text.lower()
    assert "elephant" in text
    assert "really, really" in text
