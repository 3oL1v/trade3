from datetime import UTC, datetime, timedelta

from trade3_api.indicators import atr, ema, timeframe_metrics
from trade3_api.market_models import Candle


def candles(count: int = 60) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            start_time=start + timedelta(minutes=5 * index),
            open=100 + index,
            high=101.5 + index,
            low=99.5 + index,
            close=101 + index,
            volume=100 + index,
            turnover_usdt=10_000 + index,
            is_closed=True,
        )
        for index in range(count)
    ]


def test_ema_and_atr_are_deterministic() -> None:
    values = [float(value) for value in range(1, 21)]
    assert ema(values, 10)[0] == 5.5
    assert atr(candles(), 14) == 2.0


def test_timeframe_metrics_use_closed_candles_only() -> None:
    series = candles()
    open_candle = series[-1].model_copy(update={"close": 1000, "is_closed": False})
    metrics = timeframe_metrics(series[:-1] + [open_candle], "5")

    assert metrics.close == series[-2].close
    assert metrics.closed_candles == 59
    assert metrics.ema_20 > metrics.ema_50
