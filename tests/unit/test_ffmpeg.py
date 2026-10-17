import shutil
import subprocess
from pathlib import Path

import pytest

from receipt.application.errors import TranscriptionError
from receipt.infrastructure.audio.ffmpeg import compress_for_speech

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture
def stereo_wav(tmp_path: Path) -> Path:
    path = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3:sample_rate=44100", "-ac", "2", str(path)],
        check=True,
    )  # fmt: skip
    return path


async def test_compresses_to_small_mono_16khz_mp3(stereo_wav: Path, tmp_path: Path) -> None:
    target = await compress_for_speech(stereo_wav, tmp_path / "speech.mp3")

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels,sample_rate",
         "-of", "default=noprint_wrappers=1", str(target)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert "codec_name=mp3" in probe
    assert "channels=1" in probe
    assert "sample_rate=16000" in probe
    assert target.stat().st_size < stereo_wav.stat().st_size / 10


async def test_broken_input_raises_transcription_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a media file")

    with pytest.raises(TranscriptionError, match="ffmpeg"):
        await compress_for_speech(broken, tmp_path / "speech.mp3")
