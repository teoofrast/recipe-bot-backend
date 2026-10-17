import argparse
import asyncio
import sys
from collections.abc import Sequence

from receipt.application.errors import ApplicationError, VideoUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.system.ping import Ping, PingStream
from receipt.application.video.get_video_info import GetVideoInfo
from receipt.application.video.get_video_text import GetVideoText
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.domain.errors import DomainError


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
    return parser


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


def main(argv: Sequence[str], mediator: Mediator) -> None:
    try:
        asyncio.run(run(build_parser().parse_args(argv), mediator))
    except (DomainError, ApplicationError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        if isinstance(error, VideoUnavailableError) and error.detail:
            print(f"Ответ платформы: {error.detail}", file=sys.stderr)
        raise SystemExit(1) from error
