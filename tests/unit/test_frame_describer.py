"""The vision adapter with a recording chat model and ready-made sheets."""

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose
from receipt.infrastructure.vision.llm_frame_describer import PROMPT, LlmFrameDescriber


class RecordingVisionModel(BaseChatModel):
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.received.append(list(messages))
        answer = AIMessage(
            content="  Текст на экране: 2 eggs\nЧто делает повар: взбивает яйца  ",
            response_metadata={"model_name": "vendor/vl:freevendor/vl:free"},
        )
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def test_sends_every_sheet_in_order_and_returns_the_text(tmp_path: Path) -> None:
    model = RecordingVisionModel()
    provider = ChatModelProvider(
        api_key="sk-test",
        models={Purpose.VISION: ["vl"]},
        model_factory=lambda model_id, timeout: model,
    )

    async def two_sheets(video: Path, target_dir: Path) -> list[Path]:
        sheets = [target_dir / "sheet1.jpg", target_dir / "sheet2.jpg"]
        for number, sheet in enumerate(sheets):
            sheet.write_bytes(bytes([number]))
        return sheets

    described = await LlmFrameDescriber(provider, sheets=two_sheets).describe(tmp_path / "v.mp4")

    assert described.text == "Текст на экране: 2 eggs\nЧто делает повар: взбивает яйца"
    assert described.model == "vendor/vl:free"
    [[message]] = model.received
    text, *images = message.content
    assert text == {"type": "text", "text": PROMPT}
    assert [image["image_url"]["url"] for image in images] == [
        "data:image/jpeg;base64,AA==",
        "data:image/jpeg;base64,AQ==",
    ]
