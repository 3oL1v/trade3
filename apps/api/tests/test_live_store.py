from datetime import UTC, datetime

import pytest

from trade3_api.live_store import LiveMarketStore


@pytest.mark.asyncio
async def test_ticker_delta_merges_with_snapshot() -> None:
    store = LiveMarketStore()
    snapshot = {
        "topic": "tickers.BTCUSDT",
        "type": "snapshot",
        "ts": 1_700_000_000_000,
        "data": {
            "symbol": "BTCUSDT",
            "lastPrice": "100",
            "markPrice": "100.1",
            "bid1Price": "99.9",
            "ask1Price": "100.1",
            "turnover24h": "1000000",
            "openInterestValue": "500000",
            "fundingRate": "0.0001",
        },
    }
    delta = {
        "topic": "tickers.BTCUSDT",
        "type": "delta",
        "ts": 1_700_000_001_000,
        "data": {"symbol": "BTCUSDT", "lastPrice": "101"},
    }

    assert await store.apply_message(snapshot) is True
    assert await store.apply_message(delta) is True
    ticker = await store.ticker("BTCUSDT")

    assert ticker is not None
    assert ticker.last_price == 101
    assert ticker.bid_price == 99.9
    assert ticker.source_time == datetime.fromtimestamp(1_700_000_001, tz=UTC)
    assert await store.clock_skew_seconds() is not None


@pytest.mark.asyncio
async def test_kline_update_replaces_same_open_candle() -> None:
    store = LiveMarketStore()

    def message(close: str, confirm: bool) -> dict:
        return {
            "topic": "kline.5.BTCUSDT",
            "ts": 1_700_000_000_000,
            "data": [
                {
                    "start": 1_699_999_800_000,
                    "open": "100",
                    "high": "102",
                    "low": "99",
                    "close": close,
                    "volume": "10",
                    "turnover": "1000",
                    "confirm": confirm,
                }
            ],
        }

    await store.apply_message(message("101", False))
    await store.apply_message(message("102", True))
    candles = await store.candles("BTCUSDT", "5")

    assert len(candles) == 1
    assert candles[0].close == 102
    assert candles[0].is_closed is True


@pytest.mark.asyncio
async def test_all_liquidation_message_is_stored_with_position_side() -> None:
    store = LiveMarketStore()
    message = {
        "topic": "allLiquidation.BTCUSDT",
        "type": "snapshot",
        "ts": 1_700_000_000_000,
        "data": [
            {
                "T": 1_700_000_000_000,
                "s": "BTCUSDT",
                "S": "Buy",
                "v": "2",
                "p": "100",
            },
            {
                "T": 1_700_000_001_000,
                "s": "BTCUSDT",
                "S": "Sell",
                "v": "3",
                "p": "101",
            },
        ],
    }

    assert await store.apply_message(message) is True
    events = await store.liquidations(
        "BTCUSDT",
        window_minutes=60,
        now=datetime.fromtimestamp(1_700_000_002, tz=UTC),
    )

    assert [event.position_side for event in events] == ["long", "short"]
    assert events[0].notional_usdt == 200
    assert events[1].notional_usdt == 303
