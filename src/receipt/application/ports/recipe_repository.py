from typing import Protocol

from receipt.domain.recipe import SavedRecipe


class RecipeRepository(Protocol):
    """The collection of saved recipes: the source of truth, the search index is built from it."""

    async def add(self, saved: SavedRecipe) -> None:
        """Raises DuplicateRecipeError if a recipe from the same video is already there."""
        ...

    async def get(self, recipe_id: str) -> SavedRecipe | None: ...

    async def get_by_source(self, source_key: str) -> SavedRecipe | None:
        """The recipe saved from this video (RecipeSource.key), if any."""
        ...

    async def list_all(self) -> list[SavedRecipe]:
        """All recipes, newest first."""
        ...

    async def delete(self, recipe_id: str) -> bool:
        """True if there was such a recipe."""
        ...
