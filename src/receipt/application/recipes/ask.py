from collections.abc import AsyncIterator
from dataclasses import dataclass

from receipt.application.cqrs import StreamQuery
from receipt.application.errors import ApplicationError
from receipt.application.ports.assistant import ChatEvent, ErrorEvent, RecipeAssistant
from receipt.domain.errors import DomainError


@dataclass(frozen=True)
class AskQuestion(StreamQuery[ChatEvent]):
    """A question about the saved recipes; the answer comes as a stream of events."""

    chat_id: str
    text: str


class AskQuestionHandler:
    def __init__(self, assistant: RecipeAssistant) -> None:
        self._assistant = assistant

    async def handle(self, request: AskQuestion) -> AsyncIterator[ChatEvent]:
        if not request.text.strip():
            yield ErrorEvent("Пустой вопрос")
            return
        try:
            async for event in self._assistant.stream(request.chat_id, request.text):
                yield event
        except (DomainError, ApplicationError) as error:
            # The stream itself must not break: the client gets an error event and can retry.
            yield ErrorEvent(str(error))
