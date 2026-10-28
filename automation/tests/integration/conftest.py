"""Connection setup and cleanup for the local HA simulation."""

import asyncio
import subprocess
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio

from automation.ha.client import (
    AuthenticationError,
    HAClient,
    HAClientError,
    ProtocolError,
)
from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall, StateChanged


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


@pytest.fixture
def snapshots() -> asyncio.Queue[list[EntityState]]:
    return asyncio.Queue()


@pytest.fixture
def changes() -> asyncio.Queue[StateChanged]:
    return asyncio.Queue()


@pytest.fixture
def disconnected() -> asyncio.Event:
    return asyncio.Event()


@pytest_asyncio.fixture
async def manager(
    client_factory: Callable[[], HAClient],
    snapshots: asyncio.Queue[list[EntityState]],
    changes: asyncio.Queue[StateChanged],
    disconnected: asyncio.Event,
) -> AsyncIterator[HAConnectionManager]:
    async def retry_sleep(delay: float) -> None:
        disconnected.set()  # A failed session has ended; the manager is retrying.
        await asyncio.sleep(delay)

    connection = HAConnectionManager(
        client_factory, retry_delay=0.2, max_retry_delay=1, sleep=retry_sleep
    )
    async with asyncio.TaskGroup() as tasks:
        running = tasks.create_task(connection.run(snapshots.put, changes.put))
        try:
            yield connection
        finally:
            running.cancel()


@pytest.fixture
def stopped_simulation(
    client_factory: Callable[[], HAClient],
) -> Callable[[], AbstractAsyncContextManager[None]]:
    """Stop only local simulation HA; always restart and wait for its test helper."""
    compose_file = Path(__file__).resolve().parents[1] / "simulation/compose.yaml"

    async def compose(action: str) -> None:
        await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "--context",
                "desktop-linux",
                "compose",
                "--project-name",
                "home-automation-sim",
                "--file",
                str(compose_file),
                action,
                "homeassistant",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )

    @asynccontextmanager
    async def stopped() -> AsyncGenerator[None]:
        try:
            await compose("stop")
            yield
        finally:
            await compose("start")
            async with asyncio.timeout(60):
                while True:
                    try:
                        async with client_factory() as client:
                            states = await client.get_states()
                            required = {
                                "input_boolean.simulation_probe",
                                "light.lounge",
                            }
                            if required.issubset(state.entity_id for state in states):
                                await client.call_service(
                                    ServiceCall(
                                        domain="input_boolean",
                                        service="turn_off",
                                        entity_ids=("input_boolean.simulation_probe",),
                                    )
                                )
                                break
                    except AuthenticationError, ProtocolError:
                        raise
                    except HAClientError:
                        pass
                    await asyncio.sleep(0.5)

    return stopped
