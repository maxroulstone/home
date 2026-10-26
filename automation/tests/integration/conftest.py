"""Connection setup and cleanup for the local HA simulation."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio

from automation.ha.client import HAClient
from automation.ha.models import ServiceCall


@pytest.fixture
def client_factory() -> Callable[[], HAClient]:
    token_file = Path(__file__).resolve().parents[3] / ".local/simulation/ha-token"
    if not token_file.is_file():
        pytest.fail(
            "Local HA token missing; see tests/simulation/README.md", pytrace=False
        )
    return lambda: HAClient(
        "ws://127.0.0.1:18123/api/websocket", token_file.read_text().strip()
    )


@pytest_asyncio.fixture
async def client(client_factory: Callable[[], HAClient]) -> AsyncIterator[HAClient]:
    async with client_factory() as connected:
        yield connected


@pytest_asyncio.fixture
async def probe(client: HAClient) -> AsyncIterator[str]:
    off = ServiceCall(
        domain="input_boolean",
        service="turn_off",
        entity_ids=("input_boolean.simulation_probe",),
    )
    await client.call_service(off)
    try:
        yield off.entity_ids[0]
    finally:
        await client.call_service(off)
