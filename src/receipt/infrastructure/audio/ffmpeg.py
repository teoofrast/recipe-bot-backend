import asyncio
from pathlib import Path

from receipt.application.errors import TranscriptionError


async def compress_for_speech(source: Path, target: Path) -> Path:
    """Keeps only speech-quality sound: no video, mono, 16 kHz, 32 kbit/s mp3.

    Speech models work at 16 kHz anyway, and a minute becomes ~240 KB instead of megabytes
    of TikTok/Instagram video, far below upload limits.
    """
    command = (
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(source),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        str(target),
    )  # fmt: skip
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise TranscriptionError("ffmpeg не установлен") from error
    _, stderr = await process.communicate()
    if process.returncode != 0:
        details = stderr.decode(errors="replace").strip()[-300:]
        raise TranscriptionError(f"ffmpeg не смог обработать аудио: {details}")
    return target
