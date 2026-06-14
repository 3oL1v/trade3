from datetime import UTC, datetime, timedelta

import httpx
import pytest

from trade3_api.bybit import BybitApiError, BybitPublicClient


def _response(result: dict, time: int = 1_700_000_000_000) -> httpx.Response:
    return httpx.Response(
        200,
        json={"retCode": 0, "retMsg": "OK", "result": result, "time": time},
    )


@pytest.mark.asyncio
async def test_candles_are_chronological_and_mark_open_candle() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["category"] == "linear"
        return _response(
            {
                "symbol": "BTCUSDT",
                "list": [
                    ["1699999200000", "100", "102", "99", "101", "10", "1000"],
                    ["1699998300000", "98", "101", "97", "100", "12", "1190"],
                ],
            },
            time=1_700_000_000_000,
        )

    client = BybitPublicClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        result = await client.get_candles("BTCUSDT", "15", 2)
    finally:
        await client.close()

    assert [candle.open for candle in result.candles] == [98, 100]
    assert result.candles[0].is_closed is True
    assert result.candles[1].is_closed is False
    assert result.source_time == datetime.fromtimestamp(1_700_000_000, tz=UTC)


@pytest.mark.asyncio
async def test_bybit_ret_code_raises_api_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"retCode": 10001, "retMsg": "invalid request", "result": {}, "time": 0},
        )

    client = BybitPublicClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(BybitApiError, match="retCode=10001"):
            await client.get_linear_tickers()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_bybit_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0

    async def no_sleep(_: float) -> None:
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(
                200,
                json={
                    "retCode": 10006,
                    "retMsg": "Too many visits",
                    "result": {},
                    "time": 0,
                },
            )
        return _response({"list": []})

    monkeypatch.setattr("trade3_api.bybit.asyncio.sleep", no_sleep)
    client = BybitPublicClient(
        "https://example.test",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        tickers, _ = await client.get_linear_tickers()
    finally:
        await client.close()

    assert requests == 2
    assert tickers == []


@pytest.mark.asyncio
async def test_instrument_tick_size_is_parsed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "baseCoin": "BTC",
                        "contractType": "LinearPerpetual",
                        "status": "Trading",
                        "quoteCoin": "USDT",
                        "settleCoin": "USDT",
                        "isPreListing": False,
                        "launchTime": "1585526400000",
                        "priceFilter": {"tickSize": "0.10"},
                    }
                ],
                "nextPageCursor": "",
            }
        )

    client = BybitPublicClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        instruments = await client.get_usdt_perpetual_instruments()
    finally:
        await client.close()

    assert instruments[0].tick_size == 0.1


@pytest.mark.asyncio
async def test_historical_candles_paginate_backward_and_deduplicate() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=20)
    starts = [
        int((start + timedelta(minutes=offset)).timestamp() * 1000) for offset in (0, 5, 10, 15)
    ]
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.params["start"] == str(starts[0])
        assert request.url.params["limit"] == "1000"
        rows = (
            [
                [str(starts[3]), "103", "104", "102", "103.5", "10", "1000"],
                [str(starts[2]), "102", "103", "101", "102.5", "10", "1000"],
            ]
            if requests == 1
            else [
                [str(starts[2]), "102", "103", "101", "102.5", "10", "1000"],
                [str(starts[1]), "101", "102", "100", "101.5", "10", "1000"],
                [str(starts[0]), "100", "101", "99", "100.5", "10", "1000"],
            ]
        )
        return _response({"symbol": "BTCUSDT", "list": rows})

    client = BybitPublicClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        candles = await client.get_historical_candles("BTCUSDT", "5", start, end)
    finally:
        await client.close()

    assert requests == 2
    assert [candle.start_time for candle in candles] == [
        start + timedelta(minutes=offset) for offset in (0, 5, 10, 15)
    ]
    assert all(candle.is_closed for candle in candles)


@pytest.mark.asyncio
async def test_orderbook_and_recent_trades_are_parsed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/orderbook"):
            return _response(
                {
                    "s": "BTCUSDT",
                    "b": [["100", "2"], ["99", "3"]],
                    "a": [["101", "4"], ["102", "5"]],
                    "ts": 1_700_000_000_000,
                    "cts": 1_699_999_999_900,
                    "u": 10,
                    "seq": 20,
                }
            )
        return _response(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "price": "101",
                        "size": "0.5",
                        "side": "Buy",
                        "time": "1700000000000",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "price": "100",
                        "size": "0.25",
                        "side": "Sell",
                        "time": "1699999999000",
                    },
                ],
            }
        )

    client = BybitPublicClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        orderbook = await client.get_orderbook("BTCUSDT", 50)
        trades = await client.get_recent_trades("BTCUSDT", 100)
    finally:
        await client.close()

    assert orderbook.bids[0].price == 100
    assert orderbook.asks[0].size == 4
    assert orderbook.update_id == 10
    assert trades[0].side == "Buy"
    assert trades[0].price * trades[0].size == 50.5
