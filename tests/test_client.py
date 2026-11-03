"""Tests for the Atomberg API client."""

from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

import aiohttp
import pytest

from atomberg_api import (
    API_URL,
    AtombergAuthError,
    AtombergClient,
    AtombergConnectionError,
    AtombergDevice,
    AtombergError,
)

TOKEN_URL = f"{API_URL}/v1/get_access_token"
DEVICES_URL = f"{API_URL}/v1/get_list_of_devices"
STATE_URL = f"{API_URL}/v1/get_device_state"
COMMAND_URL = f"{API_URL}/v1/send_command"
PIN_URL = f"{API_URL}/v1/get_lock_dynamic_pin"
TOKEN_RESPONSE = {"status": "Success", "message": {"access_token": "access-1"}}


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        return self._body


class FakeSession:
    """Minimal stand-in for aiohttp.ClientSession."""

    def __init__(self) -> None:
        self._responses: dict[str, list[Any]] = defaultdict(list)
        self.calls: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(
        self,
        url: str,
        *,
        payload: Any = None,
        body: str | None = None,
        status: int = 200,
        exception: Exception | None = None,
        repeat: bool = False,
    ) -> None:
        """Queue a response for a URL."""
        text = body if body is not None else json.dumps(payload)
        self._responses[url].append((status, text, exception, repeat))

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        """Return the next queued response for the URL."""
        self.calls[url].append({"method": method, **kwargs})
        queue = self._responses[url]
        status, text, exception, repeat = queue[0]
        if not repeat and len(queue) > 1:
            queue.pop(0)
        if exception is not None:
            raise exception
        return _Response(status, text)


@pytest.fixture
def mocked() -> FakeSession:
    """Return a fake session."""
    return FakeSession()


@pytest.fixture
def client(mocked: FakeSession) -> AtombergClient:
    """Return a client using the fake session."""
    return AtombergClient(mocked, "key", "refresh")  # type: ignore[arg-type]


def _calls(mocked: FakeSession, url: str) -> list[dict[str, Any]]:
    return mocked.calls[url]


async def test_token_is_reused(mocked: FakeSession, client: AtombergClient) -> None:
    """One token request serves several calls and headers are set."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(
        DEVICES_URL,
        payload={"status": "Success", "message": {"devices_list": []}},
        repeat=True,
    )

    assert await client.async_get_devices() == []
    await client.async_get_devices()

    token_calls = _calls(mocked, TOKEN_URL)
    assert len(token_calls) == 1
    assert token_calls[0]["headers"]["Authorization"] == "Bearer refresh"
    assert token_calls[0]["headers"]["x-api-key"] == "key"
    device_calls = _calls(mocked, DEVICES_URL)
    assert device_calls[0]["headers"]["Authorization"] == "Bearer access-1"


async def test_rejected_access_token_refreshes_once(
    mocked: FakeSession, client: AtombergClient
) -> None:
    """A 401 triggers exactly one token refresh and retry before failing."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE, repeat=True)
    mocked.add(DEVICES_URL, status=401, repeat=True)

    with pytest.raises(AtombergAuthError):
        await client.async_get_devices()

    assert len(_calls(mocked, TOKEN_URL)) == 2
    assert len(_calls(mocked, DEVICES_URL)) == 2


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, AtombergAuthError),
        (403, AtombergAuthError),
        (500, AtombergConnectionError),
    ],
)
async def test_token_request_errors(
    mocked: FakeSession,
    client: AtombergClient,
    status: int,
    exception: type[AtombergError],
) -> None:
    """Token endpoint errors map to the right exception."""
    mocked.add(TOKEN_URL, status=status)

    with pytest.raises(exception):
        await client.async_get_devices()


async def test_connection_error(mocked: FakeSession, client: AtombergClient) -> None:
    """A network failure maps to a connection error."""
    mocked.add(TOKEN_URL, exception=TimeoutError())

    with pytest.raises(AtombergConnectionError):
        await client.async_get_devices()


async def test_bad_token_response(mocked: FakeSession, client: AtombergClient) -> None:
    """A token response without a token raises."""
    mocked.add(TOKEN_URL, payload={"status": "Success", "message": {}})

    with pytest.raises(AtombergError):
        await client.async_get_devices()


async def test_invalid_json(mocked: FakeSession, client: AtombergClient) -> None:
    """A non-JSON body raises."""
    mocked.add(TOKEN_URL, body="not json")

    with pytest.raises(AtombergError):
        await client.async_get_devices()


@pytest.mark.parametrize(
    "body",
    [
        {"status": "Failure", "message": "nope"},
        {"status": "Success", "message": {"unexpected": []}},
    ],
)
async def test_bad_device_list(
    mocked: FakeSession, client: AtombergClient, body: dict[str, Any]
) -> None:
    """Unexpected device list responses raise."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(DEVICES_URL, payload=body)

    with pytest.raises(AtombergError):
        await client.async_get_devices()


async def test_get_devices_parses(mocked: FakeSession, client: AtombergClient) -> None:
    """Devices are parsed into AtombergDevice objects."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(
        DEVICES_URL,
        payload={
            "status": "Success",
            "message": {
                "devices_list": [
                    {"device_id": "abc", "name": "Fan", "series": "I1", "model": "M"}
                ]
            },
        },
    )

    devices = await client.async_get_devices()

    assert len(devices) == 1
    assert isinstance(devices[0], AtombergDevice)
    assert devices[0].device_id == "abc"


async def test_get_states(mocked: FakeSession, client: AtombergClient) -> None:
    """States are keyed by device ID."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(
        STATE_URL,
        payload={
            "status": "Success",
            "message": {"device_state": [{"device_id": "abc", "power": True}]},
        },
    )

    assert await client.async_get_states() == {
        "abc": {"device_id": "abc", "power": True}
    }


async def test_bad_states(mocked: FakeSession, client: AtombergClient) -> None:
    """Unexpected state responses raise."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(STATE_URL, payload={"status": "Success", "message": {}})

    with pytest.raises(AtombergError):
        await client.async_get_states()


async def test_send_command_payload(
    mocked: FakeSession, client: AtombergClient
) -> None:
    """The command request body is correct."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(COMMAND_URL, payload={"status": "Success", "message": {}})

    await client.async_send_command("abc", {"speed": 4})

    assert _calls(mocked, COMMAND_URL)[0]["json"] == {
        "device_id": "abc",
        "command": {"speed": 4},
    }


@pytest.mark.parametrize(
    ("window", "expected_body"),
    [
        ((None, None), {"device_id": "abc"}),
        ((10, 20), {"device_id": "abc", "start_time": 10, "end_time": 20}),
    ],
)
async def test_guest_pin_request(
    mocked: FakeSession,
    client: AtombergClient,
    window: tuple[int | None, int | None],
    expected_body: dict[str, Any],
) -> None:
    """The guest PIN request body and response parsing."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(
        PIN_URL,
        payload={"status": "Success", "message": {"data": {"otp": "123456"}}},
    )

    pin = await client.async_get_guest_pin("abc", *window)

    assert pin == {"otp": "123456"}
    assert _calls(mocked, PIN_URL)[0]["json"] == expected_body


async def test_guest_pin_bad_response(
    mocked: FakeSession, client: AtombergClient
) -> None:
    """A response without PIN data raises."""
    mocked.add(TOKEN_URL, payload=TOKEN_RESPONSE)
    mocked.add(PIN_URL, payload={"status": "Success", "message": {}})

    with pytest.raises(AtombergError):
        await client.async_get_guest_pin("abc")


async def test_client_error_maps(mocked: FakeSession, client: AtombergClient) -> None:
    """An aiohttp client error maps to a connection error."""
    mocked.add(TOKEN_URL, exception=aiohttp.ClientError("boom"))

    with pytest.raises(AtombergConnectionError):
        await client.async_get_devices()
