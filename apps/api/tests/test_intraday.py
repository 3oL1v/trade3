from datetime import UTC, datetime, timedelta

from trade3_api.intraday import analyze_market
from trade3_api.live_models import LiveTicker
from trade3_api.market_models import Candle


def trend_candles(interval_minutes: int, count: int = 80) -> list[Candle]:
    start = datetime.now(UTC) - timedelta(minutes=interval_minutes * count)
    return [
        Candle(
            start_time=start + timedelta(minutes=interval_minutes * index),
            open=100 + index * 0.2,
            high=101.2 + index * 0.2,
            low=99 + index * 0.2,
            close=100.2 + index * 0.2,
            volume=100 + index,
            turnover_usdt=10_000 + index,
            is_closed=True,
        )
        for index in range(count)
    ]


def test_intraday_analysis_returns_long_candidate() -> None:
    now = datetime.now(UTC)
    ticker = LiveTicker(
        symbol="BTCUSDT",
        last_price=116,
        mark_price=116,
        bid_price=115.99,
        ask_price=116.01,
        turnover_24h_usdt=1_000_000_000,
        open_interest_usdt=500_000_000,
        funding_rate=0.0001,
        source_time=now - timedelta(seconds=45),
        received_at=now,
    )
    candidate = analyze_market(
        "BTCUSDT",
        ticker,
        {
            "5": trend_candles(5),
            "15": trend_candles(15),
            "60": trend_candles(60),
        },
        now,
    )

    assert candidate is not None
    assert candidate.direction == "long"
    assert candidate.score >= 55
    assert candidate.timeframe_5m.closed_candles == 80


def test_intraday_analysis_rejects_wide_spread() -> None:
    now = datetime.now(UTC)
    ticker = LiveTicker(
        symbol="WIDEUSDT",
        last_price=100,
        mark_price=100,
        bid_price=99.9,
        ask_price=100.1,
        turnover_24h_usdt=1_000_000_000,
        open_interest_usdt=500_000_000,
        funding_rate=0,
        source_time=now,
        received_at=now,
    )

    candidate = analyze_market(
        "WIDEUSDT",
        ticker,
        {
            "5": trend_candles(5),
            "15": trend_candles(15),
            "60": trend_candles(60),
        },
        now,
        max_spread_bps=5,
    )

    assert candidate is None
