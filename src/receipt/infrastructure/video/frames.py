"""Frames of a video as a few contact sheets: one image holds 12 frames for a vision model."""

import asyncio
import math
from pathlib import Path

from receipt.application.errors import FramesUnavailableError

COLUMNS, ROWS = 4, 3
MAX_SHEETS = 4
# Shorts and reels change the shot every 1-3 s; longer videos get a sparser look.
MIN_INTERVAL_SECONDS = 2
TILE_WIDTH = 480


async def contact_sheets(video: Path, target_dir: Path) -> list[Path]:
    """Frames at an even pace, 4x3 to a sheet, at most MAX_SHEETS sheets, in order."""
    duration = await _duration(video)
    per_sheet = COLUMNS * ROWS
    interval = max(MIN_INTERVAL_SECONDS, math.ceil(duration / (per_sheet * MAX_SHEETS)))
    await _run(
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps=1/{interval},scale={TILE_WIDTH}:-2,tile={COLUMNS}x{ROWS}",
        "-frames:v", str(MAX_SHEETS), "-q:v", "4",
        str(target_dir / "sheet%d.jpg"),
    )  # fmt: skip
    sheets = await asyncio.to_thread(_sheets_in, target_dir)
    if not sheets:
        raise FramesUnavailableError("В видео нет кадров")
    return sheets


def _sheets_in(directory: Path) -> list[Path]:
    return sorted(directory.glob("sheet*.jpg"), key=lambda path: int(path.stem[5:]))


async def _duration(video: Path) -> float:
    output = await _run(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video),
    )  # fmt: skip
    try:
        return float(output)
    except ValueError as error:
        raise FramesUnavailableError(f"Не удалось узнать длину видео: {output!r}") from error


async def _run(*command: str) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise FramesUnavailableError(f"{command[0]} не установлен") from error
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        details = stderr.decode(errors="replace").strip()[-300:]
        raise FramesUnavailableError(f"{command[0]} не смог обработать видео: {details}")
    return stdout.decode().strip()
