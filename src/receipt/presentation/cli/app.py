import argparse
import asyncio
from collections.abc import Sequence

from receipt.application.mediator import Mediator
from receipt.application.system.ping import Ping, PingStream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="receipt", description="Recipe bot CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ping", help="send Ping through the mediator")
    ping_stream = commands.add_parser("ping-stream", help="stream PingStream chunks")
    ping_stream.add_argument("--count", type=int, default=3)
    return parser


async def run(args: argparse.Namespace, mediator: Mediator) -> None:
    match args.command:
        case "ping":
            pong = await mediator.send(Ping())
            print(f"{pong.message} at {pong.at.isoformat()}")
        case "ping-stream":
            async for pong in mediator.stream(PingStream(count=args.count)):
                print(f"{pong.message} at {pong.at.isoformat()}")


def main(argv: Sequence[str], mediator: Mediator) -> None:
    asyncio.run(run(build_parser().parse_args(argv), mediator))
