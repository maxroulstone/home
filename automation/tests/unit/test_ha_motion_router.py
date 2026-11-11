"""Motion routing delivers domain states without losing sensor history."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from automation.devices.motion import MotionState
from automation.ha.adapters.motion import HAMotionSensor
from automation.ha.models import EntityState, StateChanged
from automation.ha.routing.motion import HAMotionRouter


pytestmark = pytest.mark.asyncio
UPDATED = datetime(2026, 10, 29, 12, tzinfo=UTC)
ENTITY_ID = "binary_sensor.lounge_motion_occupancy"


def entity(value="on", seconds=0, entity_id=ENTITY_ID):
    timestamp = UPDATED + timedelta(seconds=seconds)
    return EntityState(
        entity_id=entity_id,
        state=value,
        attributes={},
        last_changed=timestamp,
        last_updated=timestamp,
    )


def change(value="on", seconds=1, entity_id=ENTITY_ID):
    state = entity(value, seconds, entity_id)
    return StateChanged(
        entity_id=entity_id,
        old_state=entity(entity_id=entity_id),
        new_state=state,
        time_fired=state.last_updated,
    )


@pytest.fixture
def registered_sensor():
    sensor = HAMotionSensor(entity_id=ENTITY_ID)
    router = HAMotionRouter()
    handler = AsyncMock()
    router.register(sensor, on_state_received=handler)
    return router, handler


async def test_snapshot_delivers_typed_sensor_state(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_snapshot(
        [entity(), entity(entity_id="binary_sensor.hallway_motion")]
    )

    handler.assert_awaited_once_with(
        MotionState(available=True, updated_at=UPDATED, last_motion_at=UPDATED)
    )


async def test_newer_report_reaches_the_handler(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    handler.reset_mock()
    await router.handle_state_change(change())

    handler.assert_awaited_once_with(
        MotionState(
            available=True,
            updated_at=UPDATED + timedelta(seconds=1),
            last_motion_at=UPDATED + timedelta(seconds=1),
        )
    )


async def test_unregistered_sensor_is_ignored(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_change(change(entity_id="binary_sensor.hallway_motion"))

    handler.assert_not_awaited()


@pytest.mark.parametrize("seconds", [-1, 0])
async def test_stale_or_duplicate_reports_are_ignored(registered_sensor, seconds):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    handler.reset_mock()
    await router.handle_state_change(change(seconds=seconds))

    handler.assert_not_awaited()


async def test_reconnection_snapshot_is_delivered_even_if_unchanged(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    await router.handle_state_snapshot([entity()])

    assert handler.await_count == 2


async def test_availability_recovery_preserves_previous_history(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    await router.handle_state_change(change("unavailable"))
    await router.handle_state_change(
        StateChanged(
            entity_id=ENTITY_ID,
            old_state=entity("unavailable", 1),
            new_state=entity(seconds=2),
            time_fired=UPDATED + timedelta(seconds=2),
        )
    )

    assert handler.await_args.args[0].last_motion_at == UPDATED
    assert handler.await_args.args[0].available is True


async def test_missing_snapshot_clears_recipient_but_preserves_history(
    registered_sensor,
):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    await router.handle_state_snapshot([])
    handler.assert_awaited_with(None)
    await router.handle_state_snapshot([entity(seconds=10)])

    assert handler.await_args.args[0].last_motion_at == UPDATED


async def test_removed_sensor_is_unavailable_without_losing_history(registered_sensor):
    router, handler = registered_sensor
    await router.handle_state_snapshot([entity()])
    await router.handle_state_change(
        StateChanged(
            entity_id=ENTITY_ID,
            old_state=entity(),
            new_state=None,
            time_fired=UPDATED + timedelta(seconds=1),
        )
    )

    assert handler.await_args.args[0].available is False
    assert handler.await_args.args[0].last_motion_at == UPDATED


async def test_each_registered_sensor_has_its_own_recipient(registered_sensor):
    router, first_handler = registered_sensor
    second_handler = AsyncMock()
    router.register(
        HAMotionSensor(entity_id="binary_sensor.hallway_motion"),
        on_state_received=second_handler,
    )
    await router.handle_state_change(change(entity_id="binary_sensor.hallway_motion"))

    first_handler.assert_not_awaited()
    second_handler.assert_awaited_once()


async def test_duplicate_registration_is_rejected(registered_sensor):
    router, _ = registered_sensor
    with pytest.raises(ValueError, match="already registered"):
        router.register(
            HAMotionSensor(entity_id=ENTITY_ID), on_state_received=AsyncMock()
        )


async def test_handler_failure_propagates_without_advancing_state(registered_sensor):
    router, handler = registered_sensor
    handler.side_effect = ValueError("Handler failed")
    with pytest.raises(ValueError, match="Handler failed"):
        await router.handle_state_change(change())
    handler.side_effect = None
    await router.handle_state_change(change())

    assert handler.await_count == 2
