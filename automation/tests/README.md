# Tests

Run commands from the `automation/` directory.

## Unit tests

Unit tests follow the source structure and run without Home Assistant:

```text
unit/
├── devices/          # Device state and event models
├── presence/         # Person presence models
└── ha/
    ├── test_client.py
    ├── test_connection.py
    ├── adapters/     # HA observations and commands translated for devices
    ├── models/       # HA states, WebSocket messages and service calls
    └── routing/      # Delivery, stale events and observation history
```

```bash
uv run pytest -q
uv run pytest tests/unit/ha/adapters -q
uv run pytest tests/unit/ha/routing -q
```

Fixtures and helpers stay beside the tests that use them. Pytest uses importlib
mode so different folders can have descriptive filenames such as `test_motion.py`
without module-name collisions.

## Integration tests

Integration tests require the local HA simulation and are grouped by behaviour:

```text
integration/
├── conftest.py       # Local HA clients, shared manager and restart support
├── client/           # Authentication, states, service calls and subscriptions
├── connection/       # Connection manager, disconnection and recovery
├── lights/           # Light commands, reported state and routed observations
└── sensors/          # Motion, illuminance and availability
```

Each folder keeps its own setup fixtures in `conftest.py`. Shared connection
fixtures remain at the integration-test root. Helpers and virtual devices are
reset by their fixtures.

```bash
docker --context desktop-linux compose -f tests/simulation/compose.yaml up -d
uv run pytest tests/integration -q
uv run pytest tests/integration/client -q
uv run pytest tests/integration/connection -q
uv run pytest tests/integration/lights -q
uv run pytest tests/integration/sensors -q
```

The simulation UI is at [localhost:18123](http://localhost:18123). Tests use its
local account token from the Git-ignored `.local/simulation/ha-token` file at the
repository root. Complete local HA onboarding and create that token on first use.

Disconnection and recovery tests restart only the local simulation HA container.
Run integration tests sequentially because they share its virtual devices.
