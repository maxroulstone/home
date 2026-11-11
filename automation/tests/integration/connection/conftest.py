"""Wait for the manager's initial snapshot and reset its test helper."""

import asyncio

import pytest_asyncio

from automation.ha.connection import HAConnectionManager
from automation.ha.models import EntityState, ServiceCall


PROBE = "input_boolean.simulation_probe"


@pytest_asyncio.fixture
async def connected_manager(
    manager: HAConnectionManager, snapshots: asyncio.Queue[list[EntityState]]
) -> HAConnectionManager:
    async with asyncio.timeout(20):
        await snapshots.get()
    await manager.call_service(
        ServiceCall(domain="input_boolean", service="turn_off", entity_ids=(PROBE,))
    )
    return manager
