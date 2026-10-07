"""Read reported states and request actions through HA's WebSocket API."""

import asyncio
import json
from datetime import datetime
from types import TracebackType
from typing import Self

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .models import EntityState, JSONValue, ServiceCall


class HAClientError(Exception):
    """Home Assistant could not complete the requested operation."""


class AuthenticationError(HAClientError):
    """Home Assistant rejected the access token."""


class ProtocolError(HAClientError):
    """Home Assistant returned an unexpected or malformed response."""


class HAClient:
    """An authenticated HA connection managed with ``async with``.

    Entering connects and authenticates; exiting closes the connection. Commands
    share that connection and run one at a time. Connection/authentication and
    each command have separate timeouts. Tokens and server response bodies are
    never included in error messages.
    """

    def __init__(
        self, websocket_url: str, access_token: str, *, timeout: float = 10
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._url = websocket_url
        self._token = access_token
        self._timeout = timeout
        self._socket: ClientConnection | None = None
        self._next_id = 1
        self._request_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        """Open the connection and authenticate before exposing the client."""
        if self._socket is not None:
            raise HAClientError("HA client is already connected")
        try:
            async with asyncio.timeout(self._timeout):
                self._socket = await connect(
                    self._url,
                    proxy=None,
                    open_timeout=self._timeout,
                    close_timeout=1,
                )
                await self._authenticate(self._socket)
            self._next_id = 1
        except BaseException as error:
            # Failed entry doesn't call __aexit__; cancellation needs cleanup too.
            await self._close()
            if isinstance(error, TimeoutError):
                raise HAClientError("HA connection/authentication timed out") from None
            if isinstance(error, (OSError, WebSocketException)):
                raise HAClientError("HA connection failed") from None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection, including when the caller's block raises."""
        await self._close()

    async def _close(self) -> None:
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                await socket.close()
            except OSError, WebSocketException:
                # Cleanup must not replace the original error with server details.
                pass

    async def _authenticate(self, socket: ClientConnection) -> None:
        hello = await _receive(socket)
        if hello.get("type") != "auth_required":
            raise ProtocolError("Expected HA authentication challenge")
        await socket.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth = await _receive(socket)
        if auth.get("type") == "auth_invalid":
            raise AuthenticationError("HA authentication failed")
        if auth.get("type") != "auth_ok":
            raise ProtocolError("Expected HA authentication confirmation")

    async def _request(self, command: str, **parameters: JSONValue) -> JSONValue:
        """Send one command and receive its matching result."""
        async with self._request_lock:
            socket = self._socket
            if socket is None:
                raise HAClientError("Use HAClient inside an async with block")
            request_id = self._next_id
            self._next_id += 1
            try:
                async with asyncio.timeout(self._timeout):
                    await socket.send(
                        json.dumps({**parameters, "id": request_id, "type": command})
                    )
                    response = await _receive(socket)
                    if (
                        response.get("type") != "result"
                        or response.get("id") != request_id
                    ):
                        raise ProtocolError("Expected result for HA request")
                    if response.get("success") is False:
                        raise HAClientError("HA rejected request")
                    if response.get("success") is not True:
                        raise ProtocolError("Invalid HA result")
                    return response.get("result")
            except TimeoutError:
                await self._close()
                raise HAClientError("HA request timed out") from None
            except OSError, WebSocketException:
                await self._close()
                raise HAClientError("HA connection failed") from None
            except ProtocolError, asyncio.CancelledError:
                # A late response could corrupt the next command's exchange.
                await self._close()
                raise

    async def get_states(self) -> list[EntityState]:
        """Read a snapshot using the already authenticated connection."""
        result = await self._request("get_states")
        if not isinstance(result, list):
            raise ProtocolError("Invalid get_states result")
        return [_parse_state(value) for value in result]

    async def call_service(self, call: ServiceCall) -> None:
        """Execute a service call; device state must be confirmed separately."""
        await self._request(
            "call_service",
            domain=call.domain,
            service=call.service,
            target={"entity_id": list(call.entity_ids)},
            service_data=call.data,
        )


async def _receive(socket: ClientConnection) -> dict[str, JSONValue]:
    try:
        message: JSONValue = json.loads(await socket.recv())
    except ValueError, UnicodeError:
        raise ProtocolError("Invalid JSON from HA") from None
    if not isinstance(message, dict):
        raise ProtocolError("Expected a JSON object from HA")
    return message


def _parse_state(value: JSONValue) -> EntityState:
    try:
        if not isinstance(value, dict):
            raise ValueError
        entity_id, state = value["entity_id"], value["state"]
        attributes = value["attributes"]
        if not isinstance(entity_id, str) or not isinstance(state, str):
            raise ValueError
        if not isinstance(attributes, dict):
            raise ValueError
        last_changed, last_updated = value["last_changed"], value["last_updated"]
        if not isinstance(last_changed, str) or not isinstance(last_updated, str):
            raise ValueError
        changed = datetime.fromisoformat(last_changed)
        updated = datetime.fromisoformat(last_updated)
        if changed.tzinfo is None or updated.tzinfo is None:
            raise ValueError
        return EntityState(entity_id, state, attributes, changed, updated)
    except KeyError, ValueError, TypeError:
        raise ProtocolError("Invalid entity state from HA") from None
