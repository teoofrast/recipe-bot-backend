from datetime import UTC, datetime

import punq
import pytest

from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.bootstrap.container import build_container
from receipt.bootstrap.settings import Settings
from tests.fakes import FakeClock

FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def container() -> punq.Container:
    """Production wiring with external adapters replaced by fakes."""
    container = build_container(Settings(_env_file=None))
    container.register(Clock, instance=FakeClock(FIXED_NOW))
    return container


@pytest.fixture
def mediator(container: punq.Container) -> Mediator:
    return container.resolve(Mediator)
