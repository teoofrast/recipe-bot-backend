import shutil
import subprocess
from pathlib import Path

import pytest

from receipt.application.errors import FramesUnavailableError
from receipt.infrastructure.video.frames import MAX_SHEETS, contact_sheets

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def make_video(path: Path, seconds: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=320x240:rate=5", str(path)],
        check=True,
    )  # fmt: skip
    return path


def size_of(image: Path) -> tuple[int, int]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(image)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    width, height = probe.stdout.strip().split(",")
    return int(width), int(height)


async def test_a_short_video_fits_on_few_sheets(tmp_path: Path) -> None:
    video = make_video(tmp_path / "short.mp4", 30)  # a frame each 2 s: 15 frames

    sheets = await contact_sheets(video, tmp_path)

    assert [sheet.name for sheet in sheets] == ["sheet1.jpg", "sheet2.jpg"]
    assert size_of(sheets[0]) == (4 * 480, 3 * 360)  # 4x3 tiles of 480 px


async def test_a_long_video_is_looked_at_sparser_not_on_more_sheets(tmp_path: Path) -> None:
    video = make_video(tmp_path / "long.mp4", 300)

    sheets = await contact_sheets(video, tmp_path)

    assert len(sheets) == MAX_SHEETS


async def test_not_a_video(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")

    with pytest.raises(FramesUnavailableError):
        await contact_sheets(broken, tmp_path)
