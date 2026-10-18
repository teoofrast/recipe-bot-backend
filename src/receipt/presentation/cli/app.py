import argparse
import asyncio
import sys
from collections.abc import Sequence

from receipt.application.errors import ApplicationError, VideoUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.ports.assistant import (
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
    ToolEvent,
)
from receipt.application.ports.recipe_index import RecipeFilters
from receipt.application.recipes.ask import AskQuestion
from receipt.application.recipes.collection import (
    DeleteRecipe,
    GetRecipe,
    ListRecipes,
    SaveRecipe,
)
from receipt.application.recipes.extract_recipe import ExtractRecipe
from receipt.application.recipes.import_recipe import (
    CreateImportJob,
    GetImportStatus,
    ImportRecipe,
)
from receipt.application.recipes.search import ReindexRecipes, SearchRecipes
from receipt.application.system.ping import Ping, PingStream
from receipt.application.video.get_video_frames import GetVideoFrames
from receipt.application.video.get_video_info import GetVideoInfo
from receipt.application.video.get_video_text import GetVideoText
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.domain.errors import DomainError
from receipt.domain.import_job import ImportJob, ImportStatus
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
    frames = commands.add_parser("frames", help="download the video and describe its frames")
    frames.add_argument("url")
    extract = commands.add_parser("extract", help="extract the recipe from a video (not saved)")
    extract.add_argument("url")
    extract.add_argument("--show-text", action="store_true", help="also print the source text")
    extract.add_argument("--save", action="store_true", help="save it to the collection")
    commands.add_parser("list", help="list saved recipes, newest first")
    show = commands.add_parser("show", help="show a saved recipe")
    show.add_argument("recipe_id")
    delete = commands.add_parser("delete", help="delete a saved recipe")
    delete.add_argument("recipe_id")
    search = commands.add_parser("search", help="find saved recipes by meaning")
    search.add_argument("text")
    search.add_argument("--max-minutes", type=int, help="only recipes known to take at most N")
    search.add_argument("--tag", action="append", default=[], help="required tag (repeatable)")
    search.add_argument("--cuisine")
    search.add_argument("--limit", type=int, default=5)
    commands.add_parser("reindex", help="rebuild the search index from the saved recipes")
    import_ = commands.add_parser("import", help="import a recipe from a video: extract and save")
    import_.add_argument("url")
    ask = commands.add_parser("ask", help="ask the assistant about the saved recipes")
    ask.add_argument("text")
    commands.add_parser("chat", help="talk to the assistant; it remembers the conversation")
    return parser


async def print_answer(mediator: Mediator, chat_id: str, text: str) -> None:
    """Prints the answer as it streams in: tokens, lookups, sources."""
    async for event in mediator.stream(AskQuestion(chat_id=chat_id, text=text)):
        match event:
            case TokenEvent(text=piece):
                print(piece, end="", flush=True)
            case ToolEvent(description=description):
                print(f"\n… {description}", flush=True)
            case SourcesEvent(recipes=recipes):
                print("\n\nИсточники:")
                for source in recipes:
                    print(f"  • {source.title} ({source.recipe_id}) — {source.url}")
            case ErrorEvent(message=message):
                print(f"\nОшибка: {message}", file=sys.stderr)
            case DoneEvent():
                print()


STATUS_TEXT = {
    ImportStatus.QUEUED: "в очереди",
    ImportStatus.READING: "читаю описание и субтитры",
    ImportStatus.TRANSCRIBING: "распознаю речь",
    ImportStatus.WATCHING: "смотрю видео",
    ImportStatus.EXTRACTING: "извлекаю рецепт",
    ImportStatus.SAVING: "сохраняю",
    ImportStatus.DONE: "готово",
    ImportStatus.NO_RECIPE: "в видео нет рецепта",
    ImportStatus.FAILED: "ошибка",
}


async def import_with_progress(url: str, mediator: Mediator) -> ImportJob:
    """Starts the import and watches its status, the way the API and the bot will."""
    job = await mediator.send(CreateImportJob(url=url))
    task = asyncio.create_task(mediator.send(ImportRecipe(url=url, job_id=job.id)))
    shown = None
    while not task.done():
        status = (await mediator.send(GetImportStatus(job_id=job.id))).status
        if status != shown:
            print(f"… {STATUS_TEXT[status]}", flush=True)
            shown = status
        await asyncio.wait({task}, timeout=0.5)
    return await task


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
        case "frames":
            described = await mediator.send(GetVideoFrames(url=args.url))
            print(f"Модель: {described.model}")
            print()
            print(described.text)
        case "extract":
            draft = await mediator.send(ExtractRecipe(url=args.url))
            used = [
                name
                for name, value in (
                    ("описание", draft.text.description),
                    ("субтитры", draft.text.subtitles),
                    ("распознанная речь", draft.text.transcript),
                    ("кадры", draft.text.frames),
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
        case "search":
            filters = RecipeFilters(
                max_minutes=args.max_minutes, cuisine=args.cuisine, tags=tuple(args.tag)
            )
            found = await mediator.send(
                SearchRecipes(text=args.text, filters=filters, limit=args.limit)
            )
            for item in found:
                print(f"{item.score:.2f}  {item.saved.id}  {item.saved.recipe.title}")
            if not found:
                print("Ничего не найдено.")
        case "reindex":
            count = await mediator.send(ReindexRecipes())
            print(f"Проиндексировано рецептов: {count}")
        case "import":
            job = await import_with_progress(args.url, mediator)
            if job.status is ImportStatus.DONE:
                assert job.recipe_id is not None
                saved = await mediator.send(GetRecipe(recipe_id=job.recipe_id))
                state = "Уже был сохранён раньше" if job.already_saved else "Сохранён"
                print(f"\n{state}: {saved.id}\n")
                print(format_recipe(saved.recipe))
            elif job.status is ImportStatus.NO_RECIPE:
                print("\nРецепта в видео нет.")
            else:
                print(f"\nОшибка: {job.error}", file=sys.stderr)
                raise SystemExit(1)
        case "ask":
            await print_answer(mediator, "cli", args.text)
        case "chat":
            print("Вопросы о ваших рецептах. Пустая строка — выход.")
            while question := (await asyncio.to_thread(input, "\n> ")).strip():
                await print_answer(mediator, "cli-chat", question)


def main(argv: Sequence[str], mediator: Mediator) -> None:
    try:
        asyncio.run(run(build_parser().parse_args(argv), mediator))
    except (DomainError, ApplicationError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        if isinstance(error, VideoUnavailableError) and error.detail:
            print(f"Ответ платформы: {error.detail}", file=sys.stderr)
        raise SystemExit(1) from error
