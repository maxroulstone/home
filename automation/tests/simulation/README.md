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
