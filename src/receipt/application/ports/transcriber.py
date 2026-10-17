from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    # Which model produced the text: several are tried in turn.
    model: str


class Transcriber(Protocol):
    async def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript:
        """Speech in an audio or video file as text; empty text if nobody speaks.

        ``language`` is an ISO-639-1 hint ("ru"); without it the language is detected.
        Raises TranscriptionError.
        """
        ...
