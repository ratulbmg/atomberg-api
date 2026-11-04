<p align="center"><img src="https://raw.githubusercontent.com/ratulbmg/atomberg-api/main/docs/logo.png" width="128" alt="atomberg-api logo"></p>

# atomberg-api

Async Python client for the [Atomberg public cloud API](https://developer.atomberg-iot.com/).
It supports Atomberg fans, water purifiers, and smart locks, and is used by the
Home Assistant `atomberg` integration.

This is an unofficial community library. It is not affiliated with or endorsed by Atomberg.

## Installation

```bash
pip install atomberg-api
```

## Usage

You need an API key and a refresh token, which you generate in the Atomberg Home app
(see the [developer portal](https://developer.atomberg-iot.com/)). Keep them private.

```python
import asyncio

import aiohttp

from atomberg_api import AtombergClient


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = AtombergClient(session, "YOUR_API_KEY", "YOUR_REFRESH_TOKEN")
        for device in await client.async_get_devices():
            print(device.name, device.device_type)
        states = await client.async_get_states()
        print(states)


asyncio.run(main())
```

## API limits

The public API allows 100 requests per day per account, shared with the Atomberg Home app
and any other tools using the same account. One call to `async_get_states()` returns the
state of every device.

## Errors

- `AtombergAuthError`: the API key or refresh token was rejected.
- `AtombergConnectionError`: a network or server error.
- `AtombergError`: any other unexpected response. The two errors above inherit from it.

## Development

```bash
pip install -e ".[test]"
pytest
```

## License

MIT
