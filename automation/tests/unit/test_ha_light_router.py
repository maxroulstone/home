"""Route only current observations of registered lights to their recipients."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from automation.devices.light import LightState
from automation.ha.adapters.light import HALight
from automation.ha.models import EntityState, StateChanged
from automation.ha.protocols import HAServiceCaller
from automation.ha.routing.lights import HALightRouter


pytestmark = pytest.mark.asyncio
UPDATED = datetime(2026, 10, 28, 12, tzinfo=UTC)


def entity(power="on", seconds=0, entity_id="light.lounge"):
    timestamp = UPDATED + timedelta(seconds=seconds)
    return EntityState(
        entity_id=entity_id,
        state=power,
        attributes={},
        last_changed=timestamp,
        last_updated=timestamp,
    )


def change(power="on", seconds=0, entity_id="light.lounge"):
    state = entity(power, seconds, entity_id)
    return StateChanged(
        entity_id=entity_id,
        old_state=None,
        new_state=state,
        time_fired=state.last_updated,
    )


@pytest.fixture
def registered_light():
    light = HALight(MagicMock(spec_set=HAServiceCaller), entity_id="light.lounge")
    handler = AsyncMock()
    router = HALightRouter()
    router.register(light, on_state_received=handler)
    return router, handler


async def test_snapshot_delivers_domain_state_and_ignores_other_entities(
    registered_light,
):
    router, handler = registered_light
    await router.handle_state_snapshot([entity(), entity(entity_id="light.hallway")])

    handler.assert_awaited_once_with(LightState(power="on", updated_at=UPDATED))


async def test_change_delivers_domain_state(registered_light):
    router, handler = registered_light
    await router.handle_state_change(change())

    handler.assert_awaited_once_with(LightState(power="on", updated_at=UPDATED))


async def test_unregistered_entity_change_is_ignored(registered_light):
    router, handler = registered_light
    await router.handle_state_change(change(entity_id="light.hallway"))

    handler.assert_not_awaited()


async def test_each_registered_light_has_its_own_handler(registered_light):
    router, lounge_handler = registered_light
    hallway_handler = AsyncMock()
    hallway = HALight(MagicMock(spec_set=HAServiceCaller), entity_id="light.hallway")
    router.register(hallway, on_state_received=hallway_handler)
    await router.handle_state_change(change(entity_id="light.hallway"))

    lounge_handler.assert_not_awaited()
    hallway_handler.assert_awaited_once_with(LightState(power="on", updated_at=UPDATED))


@pytest.mark.parametrize("seconds", [-1, 0])
async def test_older_or_duplicate_events_do_not_replace_snapshot(
    registered_light, seconds
):
    router, handler = registered_light
    await router.handle_state_snapshot([entity()])
    handler.reset_mock()
    await router.handle_state_change(change("off", seconds))

    handler.assert_not_awaited()


async def test_newer_event_is_delivered(registered_light):
    router, handler = registered_light
    await router.handle_state_snapshot([entity()])
    handler.reset_mock()
    await router.handle_state_change(change("off", 1))

    handler.assert_awaited_once_with(
        LightState(power="off", updated_at=UPDATED + timedelta(seconds=1))
    )


async def test_reconnection_snapshot_is_delivered_even_if_unchanged(registered_light):
    router, handler = registered_light
    await router.handle_state_snapshot([entity()])
    await router.handle_state_snapshot([entity()])

    state = LightState(power="on", updated_at=UPDATED)
    assert handler.await_args_list == [call(state), call(state)]


async def test_missing_snapshot_entity_clears_previous_observation(registered_light):
    router, handler = registered_light
    await router.handle_state_snapshot([entity()])
    await router.handle_state_snapshot([])

    assert handler.await_args_list == [
        call(LightState(power="on", updated_at=UPDATED)),
        call(None),
    ]


async def test_removed_entity_delivers_unavailable_state(registered_light):
    router, handler = registered_light
    removed_at = UPDATED + timedelta(seconds=1)
    await router.handle_state_change(
        StateChanged(
            entity_id="light.lounge",
            old_state=entity(),
            new_state=None,
            time_fired=removed_at,
        )
    )

    handler.assert_awaited_once_with(
        LightState(power="unavailable", updated_at=removed_at)
    )


async def test_duplicate_registration_is_rejected(registered_light):
    router, _ = registered_light
    duplicate = HALight(MagicMock(spec_set=HAServiceCaller), entity_id="light.lounge")

    with pytest.raises(ValueError, match="already registered"):
        router.register(duplicate, on_state_received=AsyncMock())


async def test_failed_delivery_propagates_without_advancing_latest_state(
    registered_light,
):
    router, handler = registered_light
    handler.side_effect = ValueError("Handler failed")
    with pytest.raises(ValueError, match="Handler failed"):
        await router.handle_state_change(change())

    handler.side_effect = None
    await router.handle_state_change(change())
    assert handler.await_count == 2


async def test_invalid_stale_event_is_ignored_before_translation(registered_light):
    router, handler = registered_light
    await router.handle_state_snapshot([entity()])
    handler.reset_mock()
    await router.handle_state_change(change(power="invalid", seconds=-1))

    handler.assert_not_awaited()
