"""The saved recipe collection: commands change it, queries only read it."""

from dataclasses import dataclass

from receipt.application.cqrs import Command, Query
from receipt.application.errors import DuplicateRecipeError, RecipeNotFoundError
from receipt.application.ports.clock import Clock
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.domain.recipe import Recipe, SavedRecipe, new_recipe_id
from receipt.domain.source_text import SourceText


@dataclass(frozen=True)
class SaveResult:
    saved: SavedRecipe
    # False when this video's recipe was already in the collection: nothing new was added.
    created: bool


@dataclass(frozen=True)
class SaveRecipe(Command[SaveResult]):
    recipe: Recipe
    source_text: SourceText


class SaveRecipeHandler:
    def __init__(self, repository: RecipeRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def handle(self, request: SaveRecipe) -> SaveResult:
        key = request.recipe.source.key
        if existing := await self._repository.get_by_source(key):
            return SaveResult(saved=existing, created=False)
        saved = SavedRecipe(
            id=new_recipe_id(),
            recipe=request.recipe,
            saved_at=self._clock.now(),
            source_text=request.source_text,
        )
        try:
            await self._repository.add(saved)
        except DuplicateRecipeError:
            # The same video was saved concurrently between the check and the add.
            existing = await self._repository.get_by_source(key)
            assert existing is not None
            return SaveResult(saved=existing, created=False)
        return SaveResult(saved=saved, created=True)


@dataclass(frozen=True)
class GetRecipe(Query[SavedRecipe]):
    recipe_id: str


class GetRecipeHandler:
    def __init__(self, repository: RecipeRepository) -> None:
        self._repository = repository

    async def handle(self, request: GetRecipe) -> SavedRecipe:
        saved = await self._repository.get(request.recipe_id)
        if saved is None:
            raise RecipeNotFoundError(request.recipe_id)
        return saved


@dataclass(frozen=True)
class ListRecipes(Query[list[SavedRecipe]]):
    """All saved recipes, newest first."""


class ListRecipesHandler:
    def __init__(self, repository: RecipeRepository) -> None:
        self._repository = repository

    async def handle(self, request: ListRecipes) -> list[SavedRecipe]:
        return await self._repository.list_all()


@dataclass(frozen=True)
class DeleteRecipe(Command[None]):
    recipe_id: str


class DeleteRecipeHandler:
    def __init__(self, repository: RecipeRepository) -> None:
        self._repository = repository

    async def handle(self, request: DeleteRecipe) -> None:
        if not await self._repository.delete(request.recipe_id):
            raise RecipeNotFoundError(request.recipe_id)
