# Local Home Assistant simulation

A fresh Home Assistant instance for testing our Python client and, later, lounge
rules with virtual devices. It uses normal Docker bridge networking; outbound
network isolation is not enforced.

Configuration is in `ha/configuration.yaml`. HA stores users, credentials, and its
runtime data in the simulation's own `ha-config` Docker volume. Production
configuration, credentials, and devices are not configured here.

Run these commands from `automation/` with a local Docker engine.

Start:

```bash
docker compose -f tests/simulation/compose.yaml up -d
```

Open <http://localhost:18123> and create a new local user during onboarding.
The client WebSocket URL is `ws://127.0.0.1:18123/api/websocket`.
Use credentials/tokens created in this local instance.

For this checkout's verification run, a local user was already created. Its login
details are stored in the Git-ignored `.local/simulation/login.json` at the
repository root, and its test token is in `.local/simulation/ha-token`.

## Client integration tests

In the local HA user profile, open **Security → Long-lived access tokens** and
create a token. Save just that token in `.local/simulation/ha-token` relative to
the repository root (this directory is Git-ignored). Use a token from this fresh
simulation, not production.

Separate tests cover connection/authentication, reading states, a service call
changing reported state, and receiving a subscription event. The last two use
`input_boolean.simulation_probe`, with shared fixtures resetting it before and
after each test. This helper has no physical device attached.

```bash
uv run pytest tests/integration -q
```

Separate manager tests cover the initial connection, reconnection, refreshed
states, events after reconnection, and rejected actions while disconnected.
A client test checks that stopping HA wakes a waiting consumer with an error.
They stop/start only this simulation's `homeassistant` service, using the local
Docker Desktop `desktop-linux` context, and restart it in cleanup even if an
assertion fails. Run these tests serially against a dedicated simulation.

HA can accept API connections before its helpers finish loading. The restart
fixture waits until the probe, virtual light, and probe service are usable; the recovery test also
allows the helper to appear as a creation event after the new snapshot.

Run just the manager integration tests:

```bash
uv run pytest tests/integration/test_ha_connection.py -q
```

Unit tests remain the default and need no running HA:

```bash
uv run pytest
```

Logs and stop:

```bash
docker compose -f tests/simulation/compose.yaml logs -f homeassistant
docker compose -f tests/simulation/compose.yaml down
```

Reset (deletes this simulation's users, credentials, and runtime data):

```bash
docker compose -f tests/simulation/compose.yaml down --volumes
```

After resetting HA, create a new local user/token and replace the old token file.

## Virtual lounge light

`light.lounge` is HA's built-in template light in optimistic mode. It handles real
`light.turn_on`/`light.turn_off` service calls and publishes state, brightness,
colour temperature, and RGB attributes. Its action lists are empty because there
is no physical device to control. Tests never write arbitrary HA states.

The dashboard at <http://localhost:18123/lovelace/lounge> has a light card for
manual control. Simulation YAML files are mounted read-only; after editing them,
restart this simulation's HA service:

```bash
docker compose -f tests/simulation/compose.yaml up -d
docker compose -f tests/simulation/compose.yaml restart homeassistant
```

Separate tests call `HALight` through the real connection manager and check
reported on/off, brightness, colour temperature, and RGB. They now read the
backend-independent `LightState` model. Additional tests verify state-change event
translation and the optimistic light's assumed-state flag. Shared
setup resets the light's brightness/colour and turns it off; cleanup leaves it
off. Run them with:

```bash
uv run pytest tests/integration/test_ha_light.py -q
```

This virtual device immediately accepts supported commands. It cannot verify
physical colour accuracy, device-specific capability limits, radio/network
delivery, transition timing, or delayed/unavailable physical devices. HA reports
this optimistic light as assumed state; accepted commands are not independent
physical-device confirmation.

Reference: [HA template light documentation](https://www.home-assistant.io/integrations/template/#light).

Reported observations are translated by `HALight.parse_state(entity)` for a
snapshot and `HALight.parse_change(event)` for an event. The result is a strict,
frozen Pydantic `LightState`: power, brightness percentage, Kelvin, RGB, source
update timestamp, and whether the state is assumed. Unknown and unavailable are
kept separate from off. A removed HA entity becomes unavailable.

The parsing methods do not cache state or mark commands as confirmed.
`HALightRouter` now handles registration, translation and delivery automatically.
Example startup wiring:

```python
manager = HAConnectionManager(client_factory)
lounge_light = HALight(manager, entity_id="light.lounge")
router = HALightRouter()
router.register(lounge_light, on_state_received=handle_lounge_light)
await manager.run(router.handle_state_snapshot, router.handle_state_change)
```

`handle_lounge_light` is an async function accepting `LightState | None`. It
receives a baseline on every snapshot, including reconnection. A missing entity
produces `None` so the recipient can clear old state without inventing a source
timestamp. A removal event produces an unavailable `LightState` with the event's
timestamp. Later duplicate/older events are ignored using the source update time;
a new snapshot resets the comparison baseline. Handlers run sequentially and
exceptions propagate. Register one handler per light before starting the manager.

The application entry point is not wired yet; this example describes how startup
will connect a light to an automation handler. No credentials are embedded here.
Two focused tests verify that real HA snapshots and changes reach the registered
recipient without manual parsing:

```bash
uv run pytest tests/integration/test_ha_light_router.py -q
```

## Motion and illuminance adapters

The production backup exposes two entities for the Candeo lounge sensor:
`binary_sensor.lounge_motion_occupancy` and `sensor.lounge_motion_illuminance`.
`HAMotionSensor` and `HAIlluminanceSensor` in `ha/adapters/` translate these
independently into `MotionState` and `IlluminanceState`. They have no commands,
connection dependency, or hidden mutable history. Both expose `entity_id`,
`parse_state`, and `parse_change`; pass `previous_state` to preserve known history
across snapshots, unavailable states, or removals.

An initial on snapshot seeds movement from HA's `last_changed`, not the time the
snapshot was fetched. Subsequent snapshots preserve supplied movement history.
Motion events advance it for a new on report, including a forced repeated on.
Attribute-only changes and recovery from unavailable aren't new movement.

Illuminance accepts numeric HA state strings in lux, including zero. If a unit is
reported it must be `lx`. It preserves an old reading's sample time on attribute
updates, availability changes and unchanged snapshots. A forced report can give
an unchanged lux value a new report time. `measured_at` uses HA's `last_changed` as
evidence of sample report time; this is not a device-supplied measurement clock.

The Node-RED backup consumes raw `zigbee2mqtt/lounge_motion` messages. Our current
HA `state_changed` subscription is not yet proven to preserve every such report.
HA MQTT entities can suppress unchanged values unless configured to forward them
(for example with [force_update](https://www.home-assistant.io/integrations/binary_sensor.mqtt/#force_update)).
The backup cannot establish the active retained discovery configuration or runtime
behaviour. No production discovery settings have been changed.

These adapters are unit-tested with controlled timestamps. `HAMotionRouter`
and `HAIlluminanceRouter` now register and deliver their domain states separately:

```python
motion_router.register(motion_sensor, on_state_received=handle_motion_state)
illuminance_router.register(
    illuminance_sensor, on_state_received=handle_illuminance_state
)
```

All three typed routers inherit from `HAStateRouter` in `ha/routing/state.py`.
The base class provides snapshot delivery, source-timestamp filtering, and committing
history after successful delivery. Each router instance owns its registrations and
history. Each subclass exposes a device-specific `register()` method, which calls
the base class's `_register()` helper with its adapter's translation functions and
missing-entity history policy: light history is cleared; motion and illuminance
history is retained. The snapshot and change handlers are inherited unchanged.
Stale events are ignored before translation for all three routers, including lights.

Both sensor routers provide `handle_state_snapshot` and `handle_state_change`,
matching the light router. Application-level callbacks can forward each HA snapshot/change to the
routers. They pass explicit previous state into the adapters, ignore unrelated
entities and stale/duplicate updates, and await recipients sequentially. Handler
errors propagate. Snapshots are delivered on every connection, even unchanged.

A missing snapshot entity delivers `None` and resets the session's comparison
baseline, while retaining known movement/sample history for reappearance. A
removal event delivers an unavailable model and keeps that history. Each entity
has one recipient; registration happens before processing observations.

Router tests use HA-shaped Pydantic models only. No MQTT client, broker or device
connection is added to the development stack. HA-only sensor integration scenarios,
coordinating readings before rule evaluation, and application startup wiring are
still separate steps. No physical sensor is connected here.

```bash
uv run pytest tests/unit/test_ha_motion.py tests/unit/test_ha_illuminance.py -q
```

Run the focused sensor router tests:

```bash
uv run pytest tests/unit/test_ha_motion_router.py tests/unit/test_ha_illuminance_router.py -q
```
