import pytest

from receipt.application.errors import RecipeNotFoundError
from receipt.application.mediator import Mediator
from receipt.application.recipes.collection import (
    DeleteRecipe,
    GetRecipe,
    ListRecipes,
    SaveRecipe,
)
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.presentation.cli.app import main
from tests.conftest import FIXED_NOW
from tests.fakes import FakeVideoDownloader, InMemoryRecipeRepository

TEXT = SourceText(title="Борщ", description="Свёкла 2 шт")


def recipe(url: str = "https://youtu.be/abc123", video_id: str = "abc123") -> Recipe:
    return Recipe(
        title="Борщ",
        ingredients=(Ingredient("свёкла", 2, "шт"),),
        steps=("Сварите",),
        source=RecipeSource(url=url, platform=Platform.YOUTUBE, video_id=video_id),
    )


async def test_save_adds_a_recipe_with_an_id_and_the_source_text(mediator: Mediator) -> None:
    result = await mediator.send(SaveRecipe(recipe=recipe(), source_text=TEXT))

    assert result.created
    assert len(result.saved.id) == 10
    assert result.saved.saved_at == FIXED_NOW
    assert result.saved.source_text == TEXT
    assert await mediator.send(GetRecipe(recipe_id=result.saved.id)) == result.saved


async def test_saving_the_same_video_again_does_not_duplicate(
    mediator: Mediator, recipe_repository: InMemoryRecipeRepository
) -> None:
    first = await mediator.send(SaveRecipe(recipe=recipe(), source_text=TEXT))
    # Another spelling of the same YouTube link.
    again = await mediator.send(
        SaveRecipe(recipe=recipe(url="https://www.youtube.com/watch?v=abc123"), source_text=TEXT)
    )

    assert not again.created
    assert again.saved.id == first.saved.id
    assert len(recipe_repository.recipes) == 1


async def test_list_and_delete(mediator: Mediator) -> None:
    first = await mediator.send(SaveRecipe(recipe=recipe(video_id="v1"), source_text=TEXT))
    second = await mediator.send(SaveRecipe(recipe=recipe(video_id="v2"), source_text=TEXT))

    listed = await mediator.send(ListRecipes())
    assert {saved.id for saved in listed} == {first.saved.id, second.saved.id}

    await mediator.send(DeleteRecipe(recipe_id=first.saved.id))

    assert [saved.id for saved in await mediator.send(ListRecipes())] == [second.saved.id]


async def test_missing_recipe(mediator: Mediator) -> None:
    with pytest.raises(RecipeNotFoundError, match="ffff"):
        await mediator.send(GetRecipe(recipe_id="ffff"))
    with pytest.raises(RecipeNotFoundError):
        await mediator.send(DeleteRecipe(recipe_id="ffff"))


def test_cli_extract_save_list_show_delete(
    mediator: Mediator,
    video_downloader: FakeVideoDownloader,
    recipe_repository: InMemoryRecipeRepository,
    capsys: pytest.CaptureFixture[str],
) -> None:
    video_downloader.description = "Свёкла 2 шт, капуста 300 г, морковь 1 шт"
    url = "https://www.youtube.com/watch?v=abc123"

    main(["extract", url, "--save"], mediator)
    assert "Сохранён:" in capsys.readouterr().out
    [recipe_id] = recipe_repository.recipes

    main(["extract", url, "--save"], mediator)
    assert f"Уже был сохранён раньше: {recipe_id}" in capsys.readouterr().out

    main(["list"], mediator)
    out = capsys.readouterr().out
    assert f"{recipe_id}  2026-01-01  youtube    Борщ" in out
    assert "Всего: 1" in out

    main(["show", recipe_id], mediator)
    assert "• свёкла — 2 шт" in capsys.readouterr().out

    main(["delete", recipe_id], mediator)
    assert f"Удалён: {recipe_id}" in capsys.readouterr().out
    assert recipe_repository.recipes == {}

    with pytest.raises(SystemExit):
        main(["show", recipe_id], mediator)
    assert "не найден" in capsys.readouterr().err
