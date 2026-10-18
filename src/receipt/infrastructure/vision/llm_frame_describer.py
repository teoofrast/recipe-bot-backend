"""What a cooking video shows, told by a vision model from contact sheets of its frames."""

import asyncio
import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.messages import HumanMessage

from receipt.application.ports.frame_describer import FramesDescription
from receipt.infrastructure.llm.provider import (
    ChatModelProvider,
    Purpose,
    once,
    translate_llm_errors,
)
from receipt.infrastructure.video.frames import COLUMNS, ROWS, contact_sheets

# The answer goes to the recipe extractor as one more source text, next to the description.
PROMPT = f"""Это раскадровка кулинарного видео: на каждой картинке сетка {COLUMNS}×{ROWS} кадров \
слева направо, сверху вниз; картинки идут по порядку.

1. «Текст на экране»: выпиши подписи с кадров (продукты, количества, температура, время) по \
порядку, без повторов. Логотипы и «Subscribe» пропусти.
2. «Что делает повар»: опиши по шагам, что куда кладёт, как режет, смешивает и готовит.

Только то, что видно на кадрах. Если не уверен, что за продукт или действие, — так и напиши \
(«что-то белое, похоже на муку»), не угадывай. Не придумывай время и температуру, если их не \
видно. Пиши по-русски."""

SheetMaker = Callable[[Path, Path], Awaitable[list[Path]]]


class LlmFrameDescriber:
    def __init__(self, provider: ChatModelProvider, sheets: SheetMaker = contact_sheets) -> None:
        self._provider = provider
        self._sheets = sheets

    async def describe(self, video_path: Path) -> FramesDescription:
        with TemporaryDirectory(prefix="receipt-frames-") as directory:
            sheets = await self._sheets(video_path, Path(directory))
            images = await asyncio.to_thread(lambda: [_data_url(sheet) for sheet in sheets])
        message = HumanMessage(
            content=[
                {"type": "text", "text": PROMPT},
                *({"type": "image_url", "image_url": {"url": url}} for url in images),
            ]
        )
        with translate_llm_errors():
            answer = await self._provider.with_fallbacks(Purpose.VISION).ainvoke([message])
        model = once(answer.response_metadata.get("model_name")) or "?"
        return FramesDescription(text=str(answer.content).strip(), model=model)


def _data_url(image: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode()
