from datetime import UTC, datetime, timedelta

import pytest

from trade3_api.flow_models import (
    OrderBookLevel,
    OrderBookSnapshot,
    PublicTrade,
)
from trade3_api.live_store import LiveMarketStore
from trade3_api.market_flow import build_market_flow_snapshot


class FakeClient:
    def __init__(self, now: datetime) -> None:
        self.now = now

    async def get_orderbook(self, symbol: str, limit: int) -> OrderBookSnapshot:
        assert limit == 200
        return OrderBookSnapshot(
            symbol=symbol,
            source_time=self.now,
            matching_engine_time=self.now,
            update_id=1,
            sequence=2,
            bids=[
                OrderBookLevel(price=100, size=20),
                OrderBookLevel(price=99.9, size=10),
            ],
            asks=[
                OrderBookLevel(price=100.1, size=5),
                OrderBookLevel(price=100.2, size=3),
            ],
        )

    async def get_recent_trades(self, symbol: str, limit: int) -> list[PublicTrade]:
        assert limit == 500
        return [
            PublicTrade(
                symbol=symbol,
                price=100,
                size=10,
                side="Buy",
                time=self.now - timedelta(seconds=10),
            ),
            PublicTrade(
                symbol=symbol,
                price=100,
                size=2,
                side="Sell",
                time=self.now - timedelta(seconds=20),
            ),
            PublicTrade(
                symbol=symbol,
                price=100,
                size=100,
                side="Sell",
                time=self.now - timedelta(minutes=2),
            ),
        ]


@pytest.mark.asyncio
async def test_market_flow_calculates_book_trade_and_liquidation_imbalance() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = LiveMarketStore()
    await store.apply_message(
        {
            "topic": "allLiquidation.BTCUSDT",
            "type": "snapshot",
            "ts": int(now.timestamp() * 1000),
            "data": [
                {
                    "T": int((now - timedelta(minutes=2)).timestamp() * 1000),
                    "s": "BTCUSDT",
                    "S": "Sell",
                    "v": "5",
                    "p": "100",
                }
            ],
        }
    )

    snapshot = await build_market_flow_snapshot(
        symbol="BTCUSDT",
        client=FakeClient(now),
        store=store,
        now=now,
    )

    assert snapshot.orderbook_bands[0].imbalance > 0
    assert snapshot.orderbook_bands[0].depth_complete is True
    assert snapshot.trade_flow.trade_count == 2
    assert snapshot.trade_flow.imbalance > 0
    assert snapshot.trade_flow.sample_truncated is False
    assert snapshot.liquidations[0].short_liquidated_usdt == 500
    assert snapshot.liquidations[0].imbalance == 1
