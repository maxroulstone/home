"""Read reported states and request actions through HA's WebSocket API."""

import asyncio
import json
from datetime import datetime
from types import TracebackType
from typing import Self

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .models import EntityState, JSONValue, ServiceCall, StateChanged


class HAClientError(Exception):
    """Home Assistant could not complete the requested operation."""


class AuthenticationError(HAClientError):
    """Home Assistant rejected the access token."""


class ProtocolError(HAClientError):
    """Home Assistant returned an unexpected or malformed response."""


class HAClient:
    """An authenticated HA connection managed with ``async with``.

    Entering connects and authenticates; exiting closes the connection. Commands
    share that connection; one background reader routes responses by request ID.
    Connection/authentication and each command have separate timeouts. Tokens and
    server response bodies are never included in error messages.
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
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, JSONValue]]] = {}
        self._events: asyncio.Queue[dict[str, JSONValue]] = asyncio.Queue(maxsize=256)
        self._subscription_id: int | None = None
        self._subscription_lock = asyncio.Lock()

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
            self._events = asyncio.Queue(maxsize=256)
            self._reader = asyncio.create_task(self._read_messages(self._socket))
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
        reader, self._reader = self._reader, None
        self._subscription_id = None
        self._events.shutdown(immediate=True)
        self._fail_pending(HAClientError("HA connection closed"))
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if socket is not None:
            try:
                await socket.close()
            except OSError, WebSocketException:
                # Cleanup must not replace the original error with server details.
                pass

    def _fail_pending(self, error: HAClientError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _read_messages(self, socket: ClientConnection) -> None:
        """Own receiving after authentication; route results and retain events."""
        try:
            while True:
                message = await _receive(socket)
                if message.get("type") == "event":
                    try:
                        self._events.put_nowait(message)
                    except asyncio.QueueFull:
                        raise ProtocolError("HA event buffer is full") from None
                    continue
                request_id = message.get("id")
                if (
                    message.get("type") != "result"
                    or type(request_id) is not int  # Reject bools too: True == 1.
                    # Check IDs we've issued, rather than just those in _pending:
                    # requests may time out or be cancelled before its response arrives.
                    # That late response is valid but should be ignored.
                    or not 0 < request_id < self._next_id
                ):
                    raise ProtocolError("Unexpected HA response")
                future = self._pending.get(request_id)
                if future is not None and not future.done():
                    future.set_result(message)
                # Late results for timed-out/cancelled requests are discarded.
        except HAClientError as error:
            self._fail_pending(error)
        except OSError, WebSocketException:
            self._fail_pending(HAClientError("HA connection failed"))
        finally:
            await self._close()

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

    async def _request(
        self, command: str, **parameters: JSONValue
    ) -> dict[str, JSONValue]:
        """Return the successful response, including its ID for subscriptions."""
        socket = self._socket
        if socket is None:
            raise HAClientError("Use HAClient inside an async with block")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, JSONValue]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        sent = False
        try:
            async with asyncio.timeout(self._timeout):
                await socket.send(
                    json.dumps({**parameters, "id": request_id, "type": command})
                )
                sent = True
                response = await future
            if response.get("success") is False:
                raise HAClientError("HA rejected request")
            if response.get("success") is not True:
                raise ProtocolError("Invalid HA result")
            return response
        except TimeoutError:
            if not sent:
                await self._close()
            raise HAClientError("HA request timed out") from None
        except OSError, WebSocketException:
            await self._close()
            raise HAClientError("HA connection failed") from None
        except asyncio.CancelledError:
            # Interrupting send may leave the transport unusable. Cancelling a
            # response wait only retires that request; others can continue.
            if not sent:
                await self._close()
            raise
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # Consume a disconnect error even if send failed before awaiting.
                future.exception()

    async def get_states(self) -> list[EntityState]:
        """Read a snapshot using the already authenticated connection."""
        response = await self._request("get_states")
        result = response.get("result")
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

    async def subscribe_state_changes(self) -> None:
        """Start one shared state-change stream; repeated calls are a no-op."""
        async with self._subscription_lock:
            if self._subscription_id is not None:  # subscription already exists
                return
            try:
                response = await self._request(
                    "subscribe_events", event_type="state_changed"
                )
            except HAClientError, asyncio.CancelledError:
                # HA may have subscribed even if its acknowledgement was lost.
                await self._close()
                raise
            subscription_id = response.get("id")
            if type(subscription_id) is not int:
                raise ProtocolError("Invalid HA subscription ID")
            self._subscription_id = subscription_id

    async def next_state_change(self) -> StateChanged:
        """Wait for the next change; this stream is intended for one consumer.

        Disconnect/unsubscribe raises HAClientError rather than waiting forever.
        Subscribe again and refresh state after opening a new connection.
        """
        if self._subscription_id is None:
            raise HAClientError("Subscribe to state changes before reading events")
        queue, subscription_id = self._events, self._subscription_id
        try:
            while True:
                message = await queue.get()
                if message.get("id") == subscription_id:
                    return _parse_state_change(message.get("event"))
        except asyncio.QueueShutDown:
            raise HAClientError("HA state-change stream closed") from None

    async def unsubscribe_state_changes(self) -> None:
        """Stop the stream and discard buffered events from that subscription."""
        async with self._subscription_lock:
            if self._subscription_id is None:
                return
            try:
                await self._request(
                    "unsubscribe_events", subscription=self._subscription_id
                )
            except HAClientError, asyncio.CancelledError:
                # Close if we cannot confirm HA stopped sending events.
                await self._close()
                raise
            self._subscription_id = None
            self._events.shutdown(immediate=True)
            self._events = asyncio.Queue(maxsize=256)


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


def _parse_state_change(value: JSONValue) -> StateChanged:
    try:
        if not isinstance(value, dict) or value.get("event_type") != "state_changed":
            raise ValueError
        data, time_fired = value["data"], value["time_fired"]
        if not isinstance(data, dict) or not isinstance(time_fired, str):
            raise ValueError
        entity_id = data["entity_id"]
        if not isinstance(entity_id, str):
            raise ValueError
        old, new = data["old_state"], data["new_state"]
        old_state = _parse_state(old) if old is not None else None
        new_state = _parse_state(new) if new is not None else None
        if any(s.entity_id != entity_id for s in (old_state, new_state) if s):
            raise ValueError
        timestamp = datetime.fromisoformat(time_fired)
        if timestamp.tzinfo is None:
            raise ValueError
        return StateChanged(entity_id, old_state, new_state, timestamp)
    except KeyError, ValueError, TypeError:
        raise ProtocolError("Invalid state-change event from HA") from None
