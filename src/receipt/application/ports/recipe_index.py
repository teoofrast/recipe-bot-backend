from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from receipt.domain.recipe import SavedRecipe
from receipt.domain.video import Platform


@dataclass(frozen=True)
class RecipeFilters:
    """Narrowing that does not need meaning: "quick" is a number of minutes, not a similarity."""

    max_minutes: int | None = None
    cuisine: str | None = None
    platform: Platform | None = None
    # Every one of these tags must be on the recipe.
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecipeHit:
    recipe_id: str
    # Similarity to the query, 0..1: higher is closer.
    score: float


class RecipeIndex(Protocol):
    """Search by meaning over saved recipes: a read model rebuilt from the repository.

    Raises SearchUnavailableError when the index or the embeddings service is down.
    """

    async def index(self, saved: SavedRecipe) -> None:
        """Adds the recipe or replaces its previous version."""
        ...

    async def index_many(self, recipes: Sequence[SavedRecipe]) -> None:
        """Like index() for many recipes at once: far fewer calls to the embeddings service."""
        ...

    async def remove(self, recipe_id: str) -> None: ...

    async def clear(self) -> None: ...

    async def search(self, text: str, filters: RecipeFilters, limit: int) -> list[RecipeHit]:
        """Closest recipes first."""
        ...
