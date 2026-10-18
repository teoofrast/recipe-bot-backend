"""The assistant's tools: thin wrappers over the app's queries, answering in plain text."""

from langchain_core.tools import BaseTool, tool

from receipt.application.errors import ApplicationError
from receipt.application.mediator import Mediator
from receipt.application.ports.assistant import SourceRecipe
from receipt.application.ports.recipe_index import RecipeFilters
from receipt.application.recipes.collection import GetRecipe, ListRecipes
from receipt.application.recipes.search import SearchRecipes
from receipt.domain.recipe import Recipe

MAX_LISTED = 50


def recipe_text(recipe_id: str, recipe: Recipe) -> str:
    lines = [f"Рецепт {recipe_id}: {recipe.title}"]
    facts = [
        f"порций: {recipe.servings}" if recipe.servings else "порций: не указано",
        f"время: {recipe.total_minutes} мин" if recipe.total_minutes else "время: не указано",
    ]
    if recipe.cuisine:
        facts.append(f"кухня: {recipe.cuisine}")
    lines.append(", ".join(facts))
    lines.append("Ингредиенты:")
    for item in recipe.ingredients:
        amount = f"{item.amount:g}" if item.amount is not None else ""
        quantity = " ".join(part for part in (amount, item.unit or "") if part)
        details = ", ".join(part for part in (quantity, item.note or "") if part)
        lines.append(f"- {item.name}" + (f": {details}" if details else ""))
    if recipe.steps:
        lines.append("Шаги:")
        lines.extend(f"{number}. {step}" for number, step in enumerate(recipe.steps, 1))
    else:
        lines.append("Шагов в исходном видео нет.")
    lines.append(f"Источник: {recipe.source.url}")
    return "\n".join(lines)


def make_tools(mediator: Mediator) -> list[BaseTool]:
    @tool
    async def search_recipes(query: str, max_minutes: int | None = None) -> str:
        """Найти сохранённые рецепты по смыслу: блюдо, продукты, повод («из курицы», «на завтрак»).

        Возвращает до 5 ближайших — даже если ни один не подходит, проверь сам.
        max_minutes — только рецепты, про которые известно, что они готовятся не дольше.
        """
        try:
            found = await mediator.send(
                SearchRecipes(text=query, filters=RecipeFilters(max_minutes=max_minutes))
            )
        except ApplicationError as error:
            return f"Поиск сейчас недоступен: {error}"
        if not found:
            return "Ничего похожего среди сохранённых рецептов нет."
        lines = []
        for item in found:
            recipe = item.saved.recipe
            ingredients = ", ".join(i.name for i in recipe.ingredients[:8])
            time = f", {recipe.total_minutes} мин" if recipe.total_minutes else ""
            lines.append(f"id={item.saved.id} | {recipe.title}{time} | ингредиенты: {ingredients}")
        return "\n".join(lines)

    @tool(response_format="content_and_artifact")
    async def get_recipe(recipe_id: str) -> tuple[str, list[SourceRecipe]]:
        """Открыть сохранённый рецепт по id: ингредиенты с количествами, шаги, порции, время.

        Открывай рецепт, прежде чем отвечать про его состав, шаги или пересчёт.
        """
        try:
            saved = await mediator.send(GetRecipe(recipe_id=recipe_id.strip()))
        except ApplicationError as error:
            return str(error), []
        source = SourceRecipe(saved.id, saved.recipe.title, saved.recipe.source.url)
        return recipe_text(saved.id, saved.recipe), [source]

    @tool
    async def list_recipes() -> str:
        """Список всех сохранённых рецептов: id и названия. Для вопросов «что у меня есть»."""
        recipes = await mediator.send(ListRecipes())
        if not recipes:
            return "Сохранённых рецептов пока нет."
        lines = [f"id={saved.id} | {saved.recipe.title}" for saved in recipes[:MAX_LISTED]]
        if len(recipes) > MAX_LISTED:
            lines.append(f"…и ещё {len(recipes) - MAX_LISTED}")
        return f"Всего рецептов: {len(recipes)}\n" + "\n".join(lines)

    return [search_recipes, get_recipe, list_recipes]


def describe_tool_call(name: str, args: dict[str, object]) -> str:
    match name:
        case "search_recipes":
            return f"Ищу рецепты: «{args.get('query', '')}»"
        case "get_recipe":
            return "Открываю рецепт"
        case "list_recipes":
            return "Смотрю список рецептов"
    return name
