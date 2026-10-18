from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TokenEvent:
    """A piece of the answer text, as the model writes it."""

    text: str


@dataclass(frozen=True)
class ToolEvent:
    """The assistant looks something up: shown as "ищу рецепты…" while the answer is not ready."""

    name: str
    description: str


@dataclass(frozen=True)
class SourceRecipe:
    recipe_id: str
    title: str
    url: str


@dataclass(frozen=True)
class SourcesEvent:
    """Saved recipes the answer is based on."""

    recipes: tuple[SourceRecipe, ...]


@dataclass(frozen=True)
class DoneEvent:
    model: str | None = None


@dataclass(frozen=True)
class ErrorEvent:
    message: str


type ChatEvent = TokenEvent | ToolEvent | SourcesEvent | DoneEvent | ErrorEvent


class RecipeAssistant(Protocol):
    def stream(self, chat_id: str, text: str) -> AsyncIterator[ChatEvent]:
        """Answers about the saved recipes, remembering the conversation of ``chat_id``.

        Ends with DoneEvent. Raises LlmUnavailableError / SearchUnavailableError.
        Closing the iterator early stops the work.
        """
        ...
