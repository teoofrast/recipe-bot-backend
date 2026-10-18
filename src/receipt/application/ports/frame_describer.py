from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FramesDescription:
    text: str
    # Which model looked at the frames: several are tried in turn.
    model: str


class FrameDescriber(Protocol):
    async def describe(self, video_path: Path) -> FramesDescription:
        """What the video shows: on-screen text and what the cook does, in order.

        Raises FramesUnavailableError (no frames) or LlmUnavailableError (no model answered).
        """
        ...
