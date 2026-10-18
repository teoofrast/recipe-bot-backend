from typing import Protocol

from receipt.domain.recipe import Recipe, RecipeSource
from receipt.domain.source_text import SourceText


class RecipeExtractor(Protocol):
    async def extract(self, text: SourceText, source: RecipeSource) -> Recipe | None:
        """The recipe told in the text, or None if there is none. Raises LlmUnavailableError."""
        ...
