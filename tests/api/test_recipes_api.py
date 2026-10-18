import asyncio

from httpx import AsyncClient

from receipt.application.mediator import Mediator
from receipt.application.recipes.collection import SaveRecipe
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from tests.fakes import FakeVideoDownloader


async def save(mediator: Mediator, title: str, ingredient: str, video_id: str) -> str:
    recipe = Recipe(
        title=title,
        ingredients=(Ingredient(ingredient, 2, "шт"),),
        steps=("Сварите",),
        source=RecipeSource(
            url=f"https://youtu.be/{video_id}", platform=Platform.YOUTUBE, video_id=video_id
        ),
        total_minutes=30,
        tags=("ужин",),
    )
    return (await mediator.send(SaveRecipe(recipe=recipe, source_text=SourceText("", "")))).saved.id


async def test_import_runs_in_the_background_and_its_status_can_be_watched(
    client: AsyncClient,
) -> None:
    response = await client.post("/imports", json={"url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"

    for _ in range(100):
        status = (await client.get(f"/imports/{job['id']}")).json()
        if status["status"] in ("done", "no_recipe", "failed"):
            break
        await asyncio.sleep(0.01)

    assert status["status"] == "done"
    assert status["already_saved"] is False
    recipe = (await client.get(f"/recipes/{status['recipe_id']}")).json()
    assert recipe["title"] == "Борщ"
    assert recipe["ingredients"] == [{"name": "свёкла", "amount": 2.0, "unit": "шт", "note": None}]


async def test_failed_import_reports_why(
    client: AsyncClient, video_downloader: FakeVideoDownloader
) -> None:
    from receipt.application.errors import VideoUnavailableError, VideoUnavailableReason

    video_downloader.error = VideoUnavailableError(VideoUnavailableReason.PRIVATE, "Private video")
    job = (await client.post("/imports", json={"url": "https://youtu.be/abc123"})).json()

    for _ in range(100):
        status = (await client.get(f"/imports/{job['id']}")).json()
        if status["status"] == "failed":
            break
        await asyncio.sleep(0.01)

    assert status["error"] == "Не удалось получить видео: видео приватное"


async def test_unsupported_link_is_refused_at_once(client: AsyncClient) -> None:
    response = await client.post("/imports", json={"url": "https://vimeo.com/123"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "не поддерживается" in response.json()["error"]["message"]


async def test_unknown_import(client: AsyncClient) -> None:
    response = await client.get("/imports/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "import_not_found"


async def test_list_get_delete(client: AsyncClient, mediator: Mediator) -> None:
    borsch = await save(mediator, "Борщ", "свёкла", "v1")
    await save(mediator, "Сырники", "творог", "v2")

    listed = (await client.get("/recipes")).json()
    assert {item["title"] for item in listed} == {"Борщ", "Сырники"}
    assert set(listed[0]) == {"id", "title", "platform", "url", "total_minutes", "tags", "saved_at"}

    recipe = (await client.get(f"/recipes/{borsch}")).json()
    assert recipe["source"] == {
        "url": "https://youtu.be/v1",
        "platform": "youtube",
        "video_id": "v1",
        "author": None,
    }

    assert (await client.delete(f"/recipes/{borsch}")).status_code == 204
    missing = await client.get(f"/recipes/{borsch}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "recipe_not_found"
    assert (await client.delete(f"/recipes/{borsch}")).status_code == 404


async def test_search(client: AsyncClient, mediator: Mediator) -> None:
    await save(mediator, "Борщ", "свёкла", "v1")
    await save(mediator, "Сырники", "творог", "v2")

    found = (
        await client.get(
            "/recipes/search", params={"q": "свёкла", "max_minutes": 45, "tags": ["ужин"]}
        )
    ).json()

    assert [hit["recipe"]["title"] for hit in found] == ["Борщ"]
    assert 0 < found[0]["score"] <= 1


async def test_search_needs_a_query(client: AsyncClient) -> None:
    response = await client.get("/recipes/search")

    assert response.status_code == 422


async def test_reindex(client: AsyncClient, mediator: Mediator) -> None:
    await save(mediator, "Борщ", "свёкла", "v1")

    response = await client.post("/admin/reindex")

    assert response.json() == {"indexed": 1}
