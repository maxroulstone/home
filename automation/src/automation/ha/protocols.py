"""Capabilities used by Home Assistant adapters."""

from typing import Protocol

from .models import ServiceCall


class HAServiceCaller(Protocol):
    """Send HA service requests without exposing connection management."""

    async def call_service(self, call: ServiceCall) -> None:
        """Send once and await acknowledgement, without queueing or replaying.

        Success acknowledges the request; it does not confirm device state.
        Raise HAClientError if the connection is not ready or the call fails.
        A failed call may already have taken effect.
        """
        ...
