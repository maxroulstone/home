"""Reconnect HA sessions and refresh observations before resuming delivery."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from math import isfinite

from .client import AuthenticationError, HAClient, HAClientError, ProtocolError
from .models import EntityState, ServiceCall, StateChanged


class HAConnectionManager:
    """Own successive HA connections; ``HAClient`` owns each individual one.

    ``run`` calls the snapshot handler on every connection, then delivers changes
    to one consumer in order. Handlers are awaited, so they must finish promptly.
    Cancel ``run`` to stop it and close the active connection.

    A snapshot and a subscription aren't atomic: buffered changes can overlap
    the snapshot. Consumers reconciling state must compare ``last_updated`` and
    must not treat a refreshed snapshot as proof that a new trigger occurred.
    Changes missed during an outage cannot be reconstructed from current states.
    """

    def __init__(
        self,
        client_factory: Callable[[], HAClient],
        *,
        retry_delay: float = 1,
        max_retry_delay: float = 30,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not (isfinite(retry_delay) and isfinite(max_retry_delay)) or not (
            0 < retry_delay <= max_retry_delay
        ):
            raise ValueError("Retry delays must be finite and 0 < retry <= maximum")

        self._client_factory = client_factory
        self._retry_delay = retry_delay
        self._max_retry_delay = max_retry_delay
        self._sleep = sleep
        self._client: HAClient | None = None
        self._running = False

    async def run(
        self,
        on_snapshot: Callable[[list[EntityState]], Awaitable[None]],
        on_change: Callable[[StateChanged], Awaitable[None]],
    ) -> None:
        """Retry transport failures; propagate invalid auth/protocol or handler bugs.

        Subscribing before reading states retains changes arriving during refresh.
        Retry delay doubles up to the cap and resets after a successful refresh.
        """
        if self._running:
            raise RuntimeError("HA connection manager is already running")

        self._running = True
        delay = self._retry_delay
        try:
            while True:
                # The stack also closes a client when subscription/refresh fails.
                async with AsyncExitStack() as stack:
                    try:
                        client = await stack.enter_async_context(self._client_factory())
                        await client.subscribe_state_changes()
                        states = await client.get_states()
                    except AuthenticationError, ProtocolError:
                        raise
                    except HAClientError:
                        pass  # Connection/setup failed; close before waiting to retry.
                    else:
                        delay = self._retry_delay
                        self._client = client
                        try:
                            await on_snapshot(states)
                            await self._listen(client, on_change)
                        finally:
                            self._client = None

                await self._sleep(delay)
                delay = min(delay * 2, self._max_retry_delay)
        finally:
            self._client = None
            self._running = False

    async def _listen(
        self,
        client: HAClient,
        on_change: Callable[[StateChanged], Awaitable[None]],
    ) -> None:
        while True:
            try:
                change = await client.next_state_change()
            except AuthenticationError, ProtocolError:
                raise
            except HAClientError:
                return  # End this session so run can establish a new one.

            # Handler failures must escape rather than being mistaken for an outage.
            await on_change(change)

    async def call_service(self, call: ServiceCall) -> None:
        """Send once on the refreshed connection; never queue or replay actions.

        A failed call may already have taken effect in HA. The caller must use
        reported device state to decide whether another action is appropriate.
        """
        client = self._client
        if client is None:
            raise HAClientError("HA connection is not ready")

        await client.call_service(call)
