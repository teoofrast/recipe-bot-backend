"""Real speech-to-text through OpenRouter. Costs fractions of a cent.

Run explicitly: ``OPENROUTER_API_KEY=... uv run pytest -m integration``.
Each model from STT_MODELS (or the defaults) is checked separately, to compare them.
"""

import asyncio
import os
import time
from pathlib import Path

import pytest

from receipt.bootstrap.settings import Settings
from receipt.infrastructure.transcription.openrouter import OpenRouterTranscriber
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY is not set"
    ),
]

# 19 s: "...the cool thing about these guys is that they have really, really, really long trunks"
ZOO_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.fixture(scope="module")
def zoo_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("zoo")
    return asyncio.run(YtDlpVideoDownloader().download_audio(ZOO_URL, target))


@pytest.mark.parametrize("model", Settings(_env_file=None).stt_models)
async def test_transcribes_speech(model: str, zoo_audio: Path) -> None:
    transcriber = OpenRouterTranscriber(api_key=os.environ["OPENROUTER_API_KEY"], models=[model])

    started = time.perf_counter()
    transcript = await transcriber.transcribe(zoo_audio, language="en")
    elapsed = time.perf_counter() - started

    print(f"\n{model}: {elapsed:.1f} s: {transcript.text}")
    assert transcript.model == model
    assert "elephant" in transcript.text.lower()
    assert "trunk" in transcript.text.lower()
