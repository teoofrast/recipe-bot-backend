"""One contract for both repositories: the JSON files and the in-memory one used in tests."""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from receipt.application.errors import DuplicateRecipeError
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource, SavedRecipe
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.infrastructure.recipes.json_repository import (
    JsonFileRecipeRepository,
    from_document,
    to_document,
)
from tests.fakes import InMemoryRecipeRepository

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def saved_recipe(recipe_id: str = "a1", video_id: str = "v1", minutes_ago: int = 0) -> SavedRecipe:
    return SavedRecipe(
        id=recipe_id,
        saved_at=NOW - timedelta(minutes=minutes_ago),
        recipe=Recipe(
            title="Сырники",
            ingredients=(
                Ingredient("творог", 400, "г"),
                Ingredient("соль", note="по вкусу"),
            ),
            steps=("Смешайте", "Обжарьте"),
            source=RecipeSource(
                url=f"https://youtu.be/{video_id}",
                platform=Platform.YOUTUBE,
                video_id=video_id,
                author="chef",
            ),
            servings=2,
            total_minutes=30,
            cuisine="русская",
            tags=("завтрак",),
        ),
        source_text=SourceText(
            title="Сырники", description="творог 400 г", subtitles="Берём творог", transcript=""
        ),
    )


@pytest.fixture(params=["json", "memory"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> RecipeRepository:
    factories: dict[str, Callable[[], RecipeRepository]] = {
        "json": lambda: JsonFileRecipeRepository(tmp_path / "recipes"),
        "memory": InMemoryRecipeRepository,
    }
    return factories[request.param]()


async def test_added_recipe_can_be_read_back(repository: RecipeRepository) -> None:
    saved = saved_recipe()

    await repository.add(saved)

    assert await repository.get("a1") == saved
    assert await repository.get_by_source("youtube:v1") == saved


async def test_missing_recipes(repository: RecipeRepository) -> None:
    assert await repository.get("ffff") is None
    assert await repository.get_by_source("youtube:nope") is None
    assert await repository.list_all() == []
    assert await repository.delete("ffff") is False


async def test_the_same_video_cannot_be_added_twice(repository: RecipeRepository) -> None:
    await repository.add(saved_recipe("a1", video_id="v1"))

    with pytest.raises(DuplicateRecipeError):
        await repository.add(saved_recipe("b2", video_id="v1"))

    assert [saved.id for saved in await repository.list_all()] == ["a1"]


async def test_list_is_newest_first(repository: RecipeRepository) -> None:
    await repository.add(saved_recipe("a1", video_id="v1", minutes_ago=10))
    await repository.add(saved_recipe("b2", video_id="v2", minutes_ago=0))
    await repository.add(saved_recipe("c3", video_id="v3", minutes_ago=5))

    assert [saved.id for saved in await repository.list_all()] == ["b2", "c3", "a1"]


async def test_delete(repository: RecipeRepository) -> None:
    await repository.add(saved_recipe("a1"))

    assert await repository.delete("a1") is True
    assert await repository.get("a1") is None
    assert await repository.delete("a1") is False


# JSON files only


async def test_one_readable_file_per_recipe(tmp_path: Path) -> None:
    repository = JsonFileRecipeRepository(tmp_path / "recipes")

    await repository.add(saved_recipe("a1"))

    assert [path.name for path in (tmp_path / "recipes").iterdir()] == ["a1.json"]
    document = json.loads((tmp_path / "recipes" / "a1.json").read_text(encoding="utf-8"))
    assert document["recipe"]["title"] == "Сырники"
    assert document["source_text"]["subtitles"] == "Берём творог"


def test_document_round_trip() -> None:
    saved = saved_recipe()

    assert from_document(json.loads(json.dumps(to_document(saved)))) == saved


def test_files_saved_before_frames_still_load() -> None:
    document = to_document(saved_recipe())
    del document["source_text"]["frames"]

    assert from_document(document).source_text.frames == ""


@pytest.mark.parametrize("recipe_id", ["../../etc/passwd", "a1/../b2", "A1", "", "a1.json"])
async def test_ids_that_are_not_ids_never_become_paths(tmp_path: Path, recipe_id: str) -> None:
    repository = JsonFileRecipeRepository(tmp_path / "recipes")

    assert await repository.get(recipe_id) is None
    assert await repository.delete(recipe_id) is False


async def test_unreadable_files_are_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    repository = JsonFileRecipeRepository(tmp_path / "recipes")
    await repository.add(saved_recipe("a1"))
    (tmp_path / "recipes" / "b2.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "recipes" / "c3.json").write_text('{"format": 99}', encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        recipes = await repository.list_all()

    assert [saved.id for saved in recipes] == ["a1"]
    assert len(caplog.records) == 2


async def test_concurrent_saves_of_one_video_keep_one_recipe(tmp_path: Path) -> None:
    repository = JsonFileRecipeRepository(tmp_path / "recipes")

    results = await asyncio.gather(
        *(repository.add(saved_recipe(f"a{n}", video_id="v1")) for n in range(5)),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    assert all(isinstance(r, DuplicateRecipeError) for r in results if r is not None)
    assert len(list((tmp_path / "recipes").glob("*.json"))) == 1
