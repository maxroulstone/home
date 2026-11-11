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

Integration tests remain separately runnable and require the local HA simulation:

```bash
uv run pytest tests/integration -q
```

See [simulation setup and commands](simulation/README.md).
