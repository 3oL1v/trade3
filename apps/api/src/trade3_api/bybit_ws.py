import asyncio
import json
import ssl
from collections.abc import Awaitable, Callable
from typing import Any

import truststore
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class BybitPublicStream:
    def __init__(
        self,
        url: str,
        on_message: Callable[[dict[str, Any]], Awaitable[bool]],
        heartbeat_seconds: float = 20,
    ) -> None:
        self._url = url
        self._on_message = on_message
        self._heartbeat_seconds = heartbeat_seconds

    async def run(
        self,
        symbols: list[str],
        intervals: list[str],
        stop_event: asyncio.Event,
        on_reconnect: Callable[[str | None], None],
        on_connected: Callable[[], None],
    ) -> None:
        delay = 1.0
        while not stop_event.is_set():
            error: str | None = None
            try:
                await self._run_connection(symbols, intervals, stop_event, on_connected)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError, TimeoutError, ValueError) as exc:
                error = str(exc)
            if stop_event.is_set():
                break
            on_reconnect(error)
            await _wait_or_stop(stop_event, delay)
            delay = min(delay * 2, 30)

    async def _run_connection(
        self,
        symbols: list[str],
        intervals: list[str],
        stop_event: asyncio.Event,
        on_connected: Callable[[], None],
    ) -> None:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        async with connect(
            self._url,
            ssl=ssl_context,
            ping_interval=None,
            open_timeout=15,
            close_timeout=5,
            max_queue=2048,
        ) as websocket:
            topics = [f"tickers.{symbol}" for symbol in symbols]
            topics.extend(f"allLiquidation.{symbol}" for symbol in symbols)
            topics.extend(
                f"kline.{interval}.{symbol}" for symbol in symbols for interval in intervals
            )
            await websocket.send(
                json.dumps({"req_id": "trade3-market-data", "op": "subscribe", "args": topics})
            )
            on_connected()
            heartbeat = asyncio.create_task(self._heartbeat(websocket, stop_event))
            try:
                while not stop_event.is_set():
                    raw = await asyncio.wait_for(websocket.recv(), timeout=45)
                    message = json.loads(raw)
                    if message.get("op") in {"subscribe", "ping", "pong"}:
                        if message.get("success") is False:
                            raise ValueError(f"Bybit WS command failed: {message}")
                        continue
                    await self._on_message(message)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, websocket: Any, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await _wait_or_stop(stop_event, self._heartbeat_seconds)
            if not stop_event.is_set():
                await websocket.send(json.dumps({"req_id": "trade3-ping", "op": "ping"}))


async def _wait_or_stop(stop_event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        pass
