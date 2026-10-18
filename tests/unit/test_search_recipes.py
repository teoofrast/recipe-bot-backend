import pytest

from receipt.application.errors import SearchUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.ports.recipe_index import RecipeFilters
from receipt.application.recipes.collection import DeleteRecipe, SaveRecipe
from receipt.application.recipes.search import ReindexRecipes, SearchRecipes
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.presentation.cli.app import main
from tests.fakes import FakeRecipeIndex, InMemoryRecipeRepository

TEXT = SourceText(title="", description="")


def recipe(title: str, *ingredients: str, video_id: str, minutes: int | None = None) -> Recipe:
    return Recipe(
        title=title,
        ingredients=tuple(Ingredient(name) for name in ingredients),
        steps=(),
        source=RecipeSource(
            url=f"https://youtu.be/{video_id}", platform=Platform.YOUTUBE, video_id=video_id
        ),
        total_minutes=minutes,
        tags=("ужин",) if minutes else (),
    )


async def save(mediator: Mediator, item: Recipe) -> str:
    return (await mediator.send(SaveRecipe(recipe=item, source_text=TEXT))).saved.id


async def test_saved_recipes_are_indexed_and_found(mediator: Mediator) -> None:
    curry = await save(mediator, recipe("Карри", "курица", "рис", video_id="v1"))
    await save(mediator, recipe("Сырники", "творог", video_id="v2"))

    found = await mediator.send(SearchRecipes(text="курица"))

    assert [item.saved.id for item in found] == [curry]
    assert found[0].saved.recipe.title == "Карри"


async def test_filters_reach_the_index(mediator: Mediator) -> None:
    await save(mediator, recipe("Быстрая курица", "курица", video_id="v1", minutes=20))
    await save(mediator, recipe("Долгая курица", "курица", video_id="v2", minutes=90))
    await save(mediator, recipe("Курица без времени", "курица", video_id="v3"))

    found = await mediator.send(
        SearchRecipes(text="курица", filters=RecipeFilters(max_minutes=30, tags=("ужин",)))
    )

    assert [item.saved.recipe.title for item in found] == ["Быстрая курица"]


async def test_empty_query_finds_nothing(mediator: Mediator) -> None:
    await save(mediator, recipe("Карри", "курица", video_id="v1"))

    assert await mediator.send(SearchRecipes(text="  ")) == []


async def test_deleted_recipe_leaves_the_index(
    mediator: Mediator, recipe_index: FakeRecipeIndex
) -> None:
    recipe_id = await save(mediator, recipe("Карри", "курица", video_id="v1"))

    await mediator.send(DeleteRecipe(recipe_id=recipe_id))

    assert recipe_index.documents == {}


async def test_save_and_delete_work_while_search_is_down(
    mediator: Mediator,
    recipe_index: FakeRecipeIndex,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    recipe_index.error = SearchUnavailableError("Chroma недоступна")

    recipe_id = await save(mediator, recipe("Карри", "курица", video_id="v1"))
    assert recipe_id in recipe_repository.recipes

    await mediator.send(DeleteRecipe(recipe_id=recipe_id))
    assert recipe_repository.recipes == {}


async def test_hits_of_recipes_gone_from_the_files_are_skipped(
    mediator: Mediator,
    recipe_index: FakeRecipeIndex,
    recipe_repository: InMemoryRecipeRepository,
) -> None:
    recipe_id = await save(mediator, recipe("Карри", "курица", video_id="v1"))
    del recipe_repository.recipes[recipe_id]  # deleted while the index was down

    assert await mediator.send(SearchRecipes(text="курица")) == []
    assert recipe_id in recipe_index.documents


async def test_reindex_rebuilds_the_index_from_the_files(
    mediator: Mediator, recipe_index: FakeRecipeIndex
) -> None:
    first = await save(mediator, recipe("Карри", "курица", video_id="v1"))
    second = await save(mediator, recipe("Сырники", "творог", video_id="v2"))
    # The index drifted: one recipe missing, one that is no longer in the files.
    stale = recipe_index.documents.pop(first)
    recipe_index.documents["gone"] = stale

    count = await mediator.send(ReindexRecipes())

    assert count == 2
    assert recipe_index.cleared == 1
    assert set(recipe_index.documents) == {first, second}


def test_cli_search_and_reindex(mediator: Mediator, capsys: pytest.CaptureFixture[str]) -> None:
    main(["search", "курица"], mediator)
    assert "Ничего не найдено." in capsys.readouterr().out

    main(["reindex"], mediator)
    assert "Проиндексировано рецептов: 0" in capsys.readouterr().out
