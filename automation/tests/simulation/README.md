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
after each test. This helper has no physical device attached; virtual lights
will have their own tests once configured.

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
fixture waits until the probe and its service are usable; the recovery test also
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

Verified against HA 2026.10.4: all ten integration tests and all 42 unit tests
passed. Virtual lights and motion scenarios are the next additions.
