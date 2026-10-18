from dataclasses import dataclass, field

from receipt.application.cqrs import Command, Query
from receipt.application.ports.recipe_index import RecipeFilters, RecipeIndex
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.domain.recipe import SavedRecipe


@dataclass(frozen=True)
class FoundRecipe:
    saved: SavedRecipe
    score: float


@dataclass(frozen=True)
class SearchRecipes(Query[list[FoundRecipe]]):
    """Saved recipes closest in meaning to the text: "что приготовить из курицы"."""

    text: str
    filters: RecipeFilters = field(default_factory=RecipeFilters)
    limit: int = 5


class SearchRecipesHandler:
    def __init__(self, index: RecipeIndex, repository: RecipeRepository) -> None:
        self._index = index
        self._repository = repository

    async def handle(self, request: SearchRecipes) -> list[FoundRecipe]:
        if not request.text.strip():
            return []
        hits = await self._index.search(request.text, request.filters, request.limit)
        found = []
        for hit in hits:
            # The index may lag behind the files (a delete while it was down): skip the gone.
            if saved := await self._repository.get(hit.recipe_id):
                found.append(FoundRecipe(saved=saved, score=hit.score))
        return found


@dataclass(frozen=True)
class ReindexRecipes(Command[int]):
    """Rebuilds the search index from the saved recipes; returns how many were indexed."""


class ReindexRecipesHandler:
    def __init__(self, index: RecipeIndex, repository: RecipeRepository) -> None:
        self._index = index
        self._repository = repository

    async def handle(self, request: ReindexRecipes) -> int:
        await self._index.clear()
        recipes = await self._repository.list_all()
        await self._index.index_many(recipes)
        return len(recipes)
