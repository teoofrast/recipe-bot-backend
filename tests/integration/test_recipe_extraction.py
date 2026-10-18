"""Real recipe extraction: YouTube + free models on OpenRouter. Takes a minute or two.

Run explicitly: ``uv run pytest -m integration -k extraction``.
"""

import pytest

from receipt.application.mediator import Mediator
from receipt.application.recipes.extract_recipe import ExtractRecipe
from receipt.bootstrap.container import build_container
from receipt.bootstrap.settings import Settings

SETTINGS = Settings()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(SETTINGS.openrouter_api_key is None, reason="OPENROUTER_API_KEY is not set"),
]

# Music only; the recipe is in the description: cottage cheese 1 kg, eggs, semolina, salt.
DESCRIPTION_RECIPE_URL = "https://www.youtube.com/watch?v=RghnnCK2mCw"
NOT_A_RECIPE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo"


@pytest.fixture(scope="module")
def mediator() -> Mediator:
    return build_container(SETTINGS).resolve(Mediator)


async def test_recipe_from_the_description(mediator: Mediator) -> None:
    draft = await mediator.send(ExtractRecipe(url=DESCRIPTION_RECIPE_URL))

    assert draft.recipe is not None
    names = " ".join(item.name.lower() for item in draft.recipe.ingredients)
    assert "творог" in names
    assert "манк" in names
    assert "сырник" in draft.recipe.title.lower()
    assert draft.recipe.title == draft.recipe.title.strip()
    assert "#" not in draft.recipe.title


async def test_video_without_a_recipe_gives_none(mediator: Mediator) -> None:
    draft = await mediator.send(ExtractRecipe(url=NOT_A_RECIPE_URL))

    assert draft.recipe is None
