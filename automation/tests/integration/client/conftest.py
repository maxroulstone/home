"""A resettable HA helper for client service-call tests."""

from collections.abc import AsyncIterator

import pytest_asyncio

from automation.ha.client import HAClient
from automation.ha.models import ServiceCall


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
