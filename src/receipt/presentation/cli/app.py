import argparse
import asyncio
import sys
from collections.abc import Sequence

from receipt.application.errors import ApplicationError, VideoUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.recipes.collection import (
    DeleteRecipe,
    GetRecipe,
    ListRecipes,
    SaveRecipe,
)
from receipt.application.recipes.extract_recipe import ExtractRecipe
from receipt.application.system.ping import Ping, PingStream
from receipt.application.video.get_video_info import GetVideoInfo
from receipt.application.video.get_video_text import GetVideoText
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.domain.errors import DomainError
from receipt.domain.recipe import Recipe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipt", description="Recipe bot CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ping", help="send Ping through the mediator")
    ping_stream = commands.add_parser("ping-stream", help="stream PingStream chunks")
    ping_stream.add_argument("--count", type=int, default=3)
    video_info = commands.add_parser("video-info", help="show video metadata by link")
    video_info.add_argument("url")
    video_text = commands.add_parser(
        "video-text", help="show the video's text: title, description and subtitles"
    )
    video_text.add_argument("url")
    transcribe = commands.add_parser("transcribe", help="download the audio and transcribe speech")
    transcribe.add_argument("url")
    transcribe.add_argument("--language", help="ISO-639-1 hint, e.g. ru; detected if omitted")
    extract = commands.add_parser("extract", help="extract the recipe from a video (not saved)")
    extract.add_argument("url")
    extract.add_argument("--show-text", action="store_true", help="also print the source text")
    extract.add_argument("--save", action="store_true", help="save it to the collection")
    commands.add_parser("list", help="list saved recipes, newest first")
    show = commands.add_parser("show", help="show a saved recipe")
    show.add_argument("recipe_id")
    delete = commands.add_parser("delete", help="delete a saved recipe")
    delete.add_argument("recipe_id")
    return parser


def format_recipe(recipe: Recipe) -> str:
    lines = [recipe.title]
    facts = [
        f"порций: {recipe.servings}" if recipe.servings else "",
        f"время: {recipe.total_minutes} мин" if recipe.total_minutes else "",
        f"кухня: {recipe.cuisine}" if recipe.cuisine else "",
        f"теги: {', '.join(recipe.tags)}" if recipe.tags else "",
    ]
    if any(facts):
        lines.append(" · ".join(fact for fact in facts if fact))
    lines.append("")
    lines.append("Ингредиенты:")
    for item in recipe.ingredients:
        amount = f"{item.amount:g}" if item.amount is not None else ""
        quantity = " ".join(part for part in (amount, item.unit or "") if part)
        details = ", ".join(part for part in (quantity, item.note or "") if part)
        lines.append(f"  • {item.name}" + (f" — {details}" if details else ""))
    if recipe.steps:
        lines.append("")
        lines.append("Шаги:")
        lines.extend(f"  {number}. {step}" for number, step in enumerate(recipe.steps, 1))
    lines.append("")
    author = f", {recipe.source.author}" if recipe.source.author else ""
    lines.append(f"Источник: {recipe.source.url} ({recipe.source.platform}{author})")
    return "\n".join(lines)


async def run(args: argparse.Namespace, mediator: Mediator) -> None:
    match args.command:
        case "ping":
            pong = await mediator.send(Ping())
            print(f"{pong.message} at {pong.at.isoformat()}")
        case "ping-stream":
            async for pong in mediator.stream(PingStream(count=args.count)):
                print(f"{pong.message} at {pong.at.isoformat()}")
        case "video-info":
            video = await mediator.send(GetVideoInfo(url=args.url))
            print(f"Платформа:    {video.platform}")
            print(f"ID:           {video.video_id}")
            print(f"Ссылка:       {video.url}")
            print(f"Название:     {video.title}")
            print(f"Автор:        {video.author or '-'}")
            duration = "-" if video.duration_seconds is None else f"{video.duration_seconds} с"
            print(f"Длительность: {duration}")
            print(f"Описание:\n{video.description or '-'}")
        case "video-text":
            result = await mediator.send(GetVideoText(url=args.url))
            track = result.subtitle_track
            if track is None:
                source = "нет"
            else:
                source = f"{track.language} ({'автоматические' if track.automatic else 'ручные'})"
            print(f"Субтитры:              {source}")
            print(f"Нужна транскрибация:   {'да' if result.text.needs_transcription else 'нет'}")
            print()
            print(result.text.combined())
        case "transcribe":
            transcript = await mediator.send(
                GetVideoTranscript(url=args.url, language=args.language)
            )
            print(f"Модель: {transcript.model}")
            print()
            print(transcript.text or "(речи нет)")
        case "extract":
            draft = await mediator.send(ExtractRecipe(url=args.url))
            used = [
                name
                for name, value in (
                    ("описание", draft.text.description),
                    ("субтитры", draft.text.subtitles),
                    ("распознанная речь", draft.text.transcript),
                )
                if value.strip()
            ]
            print(f"Текст из: {', '.join(used) or 'только название'}")
            print()
            print(format_recipe(draft.recipe) if draft.recipe else "Рецепта в видео нет.")
            if args.show_text:
                print("\n--- Исходный текст ---\n" + draft.text.combined())
            if args.save and draft.recipe:
                result = await mediator.send(
                    SaveRecipe(recipe=draft.recipe, source_text=draft.text)
                )
                state = "Сохранён" if result.created else "Уже был сохранён раньше"
                print(f"\n{state}: {result.saved.id}")
        case "list":
            recipes = await mediator.send(ListRecipes())
            for saved in recipes:
                date = saved.saved_at.strftime("%Y-%m-%d")
                print(
                    f"{saved.id}  {date}  {saved.recipe.source.platform:<9}  {saved.recipe.title}"
                )
            print(f"Всего: {len(recipes)}")
        case "show":
            saved = await mediator.send(GetRecipe(recipe_id=args.recipe_id))
            print(format_recipe(saved.recipe))
            print(f"Сохранён: {saved.saved_at:%Y-%m-%d %H:%M}, id {saved.id}")
        case "delete":
            await mediator.send(DeleteRecipe(recipe_id=args.recipe_id))
            print(f"Удалён: {args.recipe_id}")


def main(argv: Sequence[str], mediator: Mediator) -> None:
    try:
        asyncio.run(run(build_parser().parse_args(argv), mediator))
    except (DomainError, ApplicationError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        if isinstance(error, VideoUnavailableError) and error.detail:
            print(f"Ответ платформы: {error.detail}", file=sys.stderr)
        raise SystemExit(1) from error
