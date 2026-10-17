"""CLI entrypoint: the ``receipt`` command."""

import sys

from receipt.application.mediator import Mediator
from receipt.bootstrap.container import build_container
from receipt.bootstrap.logs import configure_logging
from receipt.bootstrap.settings import Settings
from receipt.presentation.cli import app


def main() -> None:
    container = build_container()
    configure_logging(container.resolve(Settings).log_level)
    app.main(sys.argv[1:], container.resolve(Mediator))
