from typing import Annotated

from fastapi import APIRouter, Query, status

from receipt.application.ports.recipe_index import RecipeFilters
from receipt.application.recipes.collection import DeleteRecipe, GetRecipe, ListRecipes
from receipt.application.recipes.search import SearchRecipes
from receipt.presentation.api.dependencies import MediatorDep
from receipt.presentation.api.schemas import ErrorResponse, RecipeResponse, RecipeSummary, SearchHit

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("")
async def list_recipes(mediator: MediatorDep) -> list[RecipeSummary]:
    """Все сохранённые рецепты, новые первыми."""
    return [RecipeSummary.of(saved) for saved in await mediator.send(ListRecipes())]


@router.get("/search", responses={503: {"model": ErrorResponse}})
async def search_recipes(
    mediator: MediatorDep,
    q: Annotated[str, Query(min_length=1, max_length=500, description="Что ищем, своими словами")],
    max_minutes: Annotated[int | None, Query(ge=1)] = None,
    tags: Annotated[list[str] | None, Query(description="Все теги должны быть у рецепта")] = None,
    cuisine: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[SearchHit]:
    """Поиск по смыслу: «что приготовить из курицы»."""
    filters = RecipeFilters(max_minutes=max_minutes, cuisine=cuisine, tags=tuple(tags or ()))
    found = await mediator.send(SearchRecipes(text=q, filters=filters, limit=limit))
    return [SearchHit(score=item.score, recipe=RecipeSummary.of(item.saved)) for item in found]


@router.get("/{recipe_id}", responses={404: {"model": ErrorResponse}})
async def get_recipe(recipe_id: str, mediator: MediatorDep) -> RecipeResponse:
    return RecipeResponse.of(await mediator.send(GetRecipe(recipe_id=recipe_id)))


@router.delete(
    "/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
async def delete_recipe(recipe_id: str, mediator: MediatorDep) -> None:
    await mediator.send(DeleteRecipe(recipe_id=recipe_id))
