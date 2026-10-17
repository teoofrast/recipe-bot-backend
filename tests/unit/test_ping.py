from receipt.application.mediator import Mediator
from receipt.application.system.ping import Ping, PingStream, Pong
from tests.conftest import FIXED_NOW


async def test_ping_goes_through_container_with_fake_clock(mediator: Mediator) -> None:
    assert await mediator.send(Ping()) == Pong(message="pong", at=FIXED_NOW)


async def test_ping_stream_yields_requested_number_of_pongs(mediator: Mediator) -> None:
    pongs = [pong async for pong in mediator.stream(PingStream(count=2))]

    assert pongs == [
        Pong(message="pong 1", at=FIXED_NOW),
        Pong(message="pong 2", at=FIXED_NOW),
    ]
