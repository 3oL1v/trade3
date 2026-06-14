from datetime import UTC, datetime, timedelta

import pytest

from trade3_api.historical_replay import (
    _average,
    _breakdown,
    _closed_window,
    _historical_ticker,
)
from trade3_api.market_models import Candle
from trade3_api.research_models import ReplayTrade


def candle(start: datetime, close: float = 100, turnover: float = 1_000) -> Candle:
    return Candle(
        start_time=start,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10,
        turnover_usdt=turnover,
        is_closed=True,
    )


def test_closed_window_never_exposes_unclosed_higher_timeframe() -> None:
    base = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    candles = [
        candle(base),
        candle(base + timedelta(minutes=15)),
        candle(base + timedelta(minutes=30)),
    ]
    close_times = [item.start_time + timedelta(minutes=15) for item in candles]

    visible = _closed_window(candles, close_times, base + timedelta(minutes=20))

    assert [item.start_time for item in visible] == [base]
    assert all(
        item.start_time + timedelta(minutes=15) <= base + timedelta(minutes=20) for item in visible
    )


def test_historical_ticker_uses_fixed_spread_and_rolling_turnover() -> None:
    now = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    candles = [
        candle(now - timedelta(minutes=10), turnover=1_000),
        candle(now - timedelta(minutes=5), close=100, turnover=2_000),
    ]

    ticker = _historical_ticker("BTCUSDT", candles[-1], now, candles, spread_bps=2)

    spread_bps = (ticker.ask_price - ticker.bid_price) / ticker.last_price * 10_000
    assert spread_bps == pytest.approx(2)
    assert ticker.turnover_24h_usdt == 3_000
    assert ticker.received_at == now


def test_replay_breakdown_uses_chronological_net_results() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    results = [0.9, -1.1, -1.0, 0.8]
    trades = [
        ReplayTrade(
            symbol="BTCUSDT",
            direction="long",
            score=80,
            signal_at=base + timedelta(hours=index),
            entered_at=base + timedelta(hours=index),
            closed_at=base + timedelta(hours=index, minutes=30),
            outcome="target_complete" if result > 0 else "stop_before_target",
            gross_result_r=1 if result > 0 else -1,
            net_result_r=result,
            fee_cost_r=0.05,
            slippage_cost_r=0.05,
        )
        for index, result in enumerate(results)
    ]

    breakdown = _breakdown("all", trades)

    assert breakdown.trades == 4
    assert breakdown.win_rate == 0.5
    assert breakdown.expectancy_r == -0.1
    assert breakdown.cumulative_net_r == -0.4
    assert breakdown.max_drawdown_r == 2.1
    assert _average(results) == -0.1
