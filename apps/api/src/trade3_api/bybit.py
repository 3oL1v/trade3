import asyncio
import ssl
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import httpx
import truststore

from .market_models import Candle, CandleSeries, LinearInstrument, LinearTicker
from .flow_models import OrderBookLevel, OrderBookSnapshot, PublicTrade

SUPPORTED_INTERVALS_MINUTES = {
    "5": 5,
    "15": 15,
    "60": 60,
    "240": 240,
}


class BybitApiError(RuntimeError):
    pass


class BybitPublicClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        minimum_request_interval_seconds: float = 0,
    ) -> None:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            verify=ssl_context,
            headers={"User-Agent": "Trade3/0.1 public-market-data"},
        )
        self._max_retries = max_retries
        self._minimum_request_interval_seconds = minimum_request_interval_seconds
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._instrument_cache: tuple[float, list[LinearInstrument]] | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._throttle()
                response = await self._client.get(path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Bybit HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                ret_code = payload.get("retCode")
                if ret_code == 10006:
                    raise httpx.HTTPStatusError(
                        "Bybit API rate limit",
                        request=response.request,
                        response=response,
                    )
                if ret_code != 0:
                    raise BybitApiError(f"Bybit retCode={ret_code}: {payload.get('retMsg')}")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = 1.0 if "rate limit" in str(exc).lower() else 0.25
                    await asyncio.sleep(delay * (2**attempt))

        raise BybitApiError(f"Bybit request failed after retries: {last_error}") from last_error

    async def _throttle(self) -> None:
        if self._minimum_request_interval_seconds <= 0:
            return
        async with self._request_lock:
            elapsed = monotonic() - self._last_request_at
            remaining = self._minimum_request_interval_seconds - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = monotonic()

    async def get_usdt_perpetual_instruments(self) -> list[LinearInstrument]:
        if self._instrument_cache and monotonic() - self._instrument_cache[0] < 3600:
            return self._instrument_cache[1]

        instruments: list[LinearInstrument] = []
        cursor = ""
        while True:
            params: dict[str, Any] = {
                "category": "linear",
                "status": "Trading",
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            payload = await self._get("/v5/market/instruments-info", params)
            result = payload["result"]
            for item in result["list"]:
                if (
                    item.get("contractType") == "LinearPerpetual"
                    and item.get("quoteCoin") == "USDT"
                    and item.get("settleCoin") == "USDT"
                    and not item.get("isPreListing", False)
                ):
                    instruments.append(
                        LinearInstrument(
                            symbol=item["symbol"],
                            base_coin=item["baseCoin"],
                            contract_type=item["contractType"],
                            status=item["status"],
                            quote_coin=item["quoteCoin"],
                            settle_coin=item["settleCoin"],
                            is_pre_listing=item.get("isPreListing", False),
                            launch_time=_milliseconds_to_datetime(item["launchTime"]),
                            tick_size=float(item["priceFilter"]["tickSize"]),
                        )
                    )
            cursor = result.get("nextPageCursor", "")
            if not cursor:
                break

        self._instrument_cache = (monotonic(), instruments)
        return instruments

    async def get_linear_tickers(self) -> tuple[list[LinearTicker], datetime]:
        payload = await self._get("/v5/market/tickers", {"category": "linear"})
        tickers = [
            LinearTicker(
                symbol=item["symbol"],
                last_price=_float(item.get("lastPrice")),
                turnover_24h_usdt=_float(item.get("turnover24h")),
                volume_24h=_float(item.get("volume24h")),
                open_interest_usdt=_float(item.get("openInterestValue")),
                bid_price=_float(item.get("bid1Price")),
                ask_price=_float(item.get("ask1Price")),
                funding_rate=_float(item.get("fundingRate")),
                price_change_24h_pct=_float(item.get("price24hPcnt")) * 100,
            )
            for item in payload["result"]["list"]
        ]
        return tickers, _milliseconds_to_datetime(payload["time"])

    async def get_candles(self, symbol: str, interval: str, limit: int) -> CandleSeries:
        if interval not in SUPPORTED_INTERVALS_MINUTES:
            raise ValueError(f"unsupported interval: {interval}")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        payload = await self._get(
            "/v5/market/kline",
            {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
        )
        source_time = _milliseconds_to_datetime(payload["time"])
        interval_delta = timedelta(minutes=SUPPORTED_INTERVALS_MINUTES[interval])
        candles = [
            Candle(
                start_time=_milliseconds_to_datetime(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                turnover_usdt=float(row[6]),
                is_closed=_milliseconds_to_datetime(row[0]) + interval_delta <= source_time,
            )
            for row in reversed(payload["result"]["list"])
        ]
        return CandleSeries(
            symbol=payload["result"]["symbol"],
            interval=interval,
            source_time=source_time,
            candles=candles,
        )

    async def get_orderbook(self, symbol: str, limit: int = 200) -> OrderBookSnapshot:
        if not 1 <= limit <= 1000:
            raise ValueError("orderbook limit must be between 1 and 1000")
        payload = await self._get(
            "/v5/market/orderbook",
            {"category": "linear", "symbol": symbol, "limit": limit},
        )
        result = payload["result"]
        return OrderBookSnapshot(
            symbol=result["s"],
            source_time=_milliseconds_to_datetime(result["ts"]),
            matching_engine_time=_milliseconds_to_datetime(result["cts"]),
            update_id=int(result["u"]),
            sequence=int(result["seq"]),
            bids=[
                OrderBookLevel(price=float(row[0]), size=float(row[1]))
                for row in result["b"]
                if float(row[1]) > 0
            ],
            asks=[
                OrderBookLevel(price=float(row[0]), size=float(row[1]))
                for row in result["a"]
                if float(row[1]) > 0
            ],
        )

    async def get_recent_trades(self, symbol: str, limit: int = 500) -> list[PublicTrade]:
        if not 1 <= limit <= 1000:
            raise ValueError("recent trade limit must be between 1 and 1000")
        payload = await self._get(
            "/v5/market/recent-trade",
            {"category": "linear", "symbol": symbol, "limit": limit},
        )
        return [
            PublicTrade(
                symbol=item["symbol"],
                price=float(item["price"]),
                size=float(item["size"]),
                side=item["side"],
                time=_milliseconds_to_datetime(item["time"]),
            )
            for item in payload["result"]["list"]
            if float(item["size"]) > 0
        ]

    async def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        if interval not in SUPPORTED_INTERVALS_MINUTES:
            raise ValueError(f"unsupported interval: {interval}")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start >= end:
            raise ValueError("start must be before end")

        start_ms = int(start.timestamp() * 1000)
        page_end_ms = int(end.timestamp() * 1000)
        interval_delta = timedelta(minutes=SUPPORTED_INTERVALS_MINUTES[interval])
        candles_by_time: dict[datetime, Candle] = {}

        while page_end_ms >= start_ms:
            payload = await self._get(
                "/v5/market/kline",
                {
                    "category": "linear",
                    "symbol": symbol,
                    "interval": interval,
                    "start": start_ms,
                    "end": page_end_ms,
                    "limit": 1000,
                },
            )
            rows = payload["result"]["list"]
            if not rows:
                break
            oldest_ms = min(int(row[0]) for row in rows)
            for row in rows:
                candle_start = _milliseconds_to_datetime(row[0])
                if candle_start < start or candle_start >= end:
                    continue
                candle = Candle(
                    start_time=candle_start,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    turnover_usdt=float(row[6]),
                    is_closed=candle_start + interval_delta <= end,
                )
                if candle.is_closed:
                    candles_by_time[candle_start] = candle
            if oldest_ms <= start_ms:
                break
            next_end_ms = oldest_ms - 1
            if next_end_ms >= page_end_ms:
                raise BybitApiError("Bybit kline pagination did not advance")
            page_end_ms = next_end_ms

        return sorted(candles_by_time.values(), key=lambda candle: candle.start_time)


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _milliseconds_to_datetime(value: str | int) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
