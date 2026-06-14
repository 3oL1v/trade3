import asyncio
from datetime import UTC, datetime, timedelta

from .bybit import BybitPublicClient
from .flow_models import (
    LiquidationPrint,
    LiquidationWindow,
    MarketFlowSnapshot,
    OrderBookBand,
    OrderBookSnapshot,
    PublicTrade,
    TradeFlowWindow,
)
from .live_store import LiveMarketStore


async def build_market_flow_snapshot(
    *,
    symbol: str,
    client: BybitPublicClient,
    store: LiveMarketStore,
    now: datetime | None = None,
) -> MarketFlowSnapshot:
    generated_at = now or datetime.now(UTC)
    orderbook, trades = await asyncio.gather(
        client.get_orderbook(symbol, limit=200),
        client.get_recent_trades(symbol, limit=500),
    )
    liquidations = await store.liquidations(symbol, window_minutes=60, now=generated_at)
    best_bid = orderbook.bids[0].price
    best_ask = orderbook.asks[0].price
    mid_price = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid_price * 10_000
    return MarketFlowSnapshot(
        symbol=symbol,
        generated_at=generated_at,
        orderbook_source_time=orderbook.source_time,
        mid_price=mid_price,
        spread_bps=spread_bps,
        orderbook_bands=[
            _orderbook_band(orderbook, mid_price, distance_bps) for distance_bps in (10, 25)
        ],
        trade_flow=_trade_flow(
            trades,
            generated_at,
            window_seconds=60,
            sample_limit=500,
        ),
        liquidations=[
            _liquidation_window(liquidations, generated_at, minutes) for minutes in (5, 15, 60)
        ],
    )


def _orderbook_band(
    orderbook: OrderBookSnapshot,
    mid_price: float,
    distance_bps: int,
) -> OrderBookBand:
    distance = distance_bps / 10_000
    bid_floor = mid_price * (1 - distance)
    ask_ceiling = mid_price * (1 + distance)
    bid_notional = sum(
        level.price * level.size for level in orderbook.bids if level.price >= bid_floor
    )
    ask_notional = sum(
        level.price * level.size for level in orderbook.asks if level.price <= ask_ceiling
    )
    depth_complete = (
        bool(orderbook.bids)
        and bool(orderbook.asks)
        and orderbook.bids[-1].price <= bid_floor
        and orderbook.asks[-1].price >= ask_ceiling
    )
    return OrderBookBand(
        distance_bps=distance_bps,
        bid_notional_usdt=bid_notional,
        ask_notional_usdt=ask_notional,
        imbalance=_imbalance(bid_notional, ask_notional),
        depth_complete=depth_complete,
    )


def _trade_flow(
    trades: list[PublicTrade],
    now: datetime,
    window_seconds: int,
    sample_limit: int,
) -> TradeFlowWindow:
    cutoff = now - timedelta(seconds=window_seconds)
    recent = [trade for trade in trades if cutoff <= trade.time <= now + timedelta(seconds=5)]
    buy_notional = sum(trade.price * trade.size for trade in recent if trade.side.lower() == "buy")
    sell_notional = sum(
        trade.price * trade.size for trade in recent if trade.side.lower() == "sell"
    )
    return TradeFlowWindow(
        window_seconds=window_seconds,
        trade_count=len(recent),
        taker_buy_usdt=buy_notional,
        taker_sell_usdt=sell_notional,
        imbalance=_imbalance(buy_notional, sell_notional),
        sample_truncated=(
            len(trades) >= sample_limit
            and bool(trades)
            and min(trade.time for trade in trades) > cutoff
        ),
    )


def _liquidation_window(
    events: list[LiquidationPrint],
    now: datetime,
    window_minutes: int,
) -> LiquidationWindow:
    cutoff = now - timedelta(minutes=window_minutes)
    recent = [event for event in events if cutoff <= event.time <= now + timedelta(seconds=5)]
    long_notional = sum(event.notional_usdt for event in recent if event.position_side == "long")
    short_notional = sum(event.notional_usdt for event in recent if event.position_side == "short")
    return LiquidationWindow(
        window_minutes=window_minutes,
        event_count=len(recent),
        long_liquidated_usdt=long_notional,
        short_liquidated_usdt=short_notional,
        imbalance=_imbalance(short_notional, long_notional),
    )


def _imbalance(positive: float, negative: float) -> float:
    total = positive + negative
    if total <= 0:
        return 0
    return (positive - negative) / total
