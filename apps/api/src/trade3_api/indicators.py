from .live_models import TimeframeMetrics
from .market_models import Candle


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        raise ValueError(f"at least {period} values are required")
    seed = sum(values[:period]) / period
    result = [seed]
    multiplier = 2 / (period + 1)
    for value in values[period:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def aligned_ema(values: list[float], period: int) -> list[float | None]:
    return [None] * (period - 1) + ema(values, period)


def atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        raise ValueError(f"at least {period + 1} candles are required")
    ranges = []
    for previous, current in zip(candles, candles[1:], strict=False):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    value = sum(ranges[:period]) / period
    for true_range in ranges[period:]:
        value = ((value * (period - 1)) + true_range) / period
    return value


def timeframe_metrics(candles: list[Candle], interval: str) -> TimeframeMetrics:
    closed = [candle for candle in candles if candle.is_closed]
    if len(closed) < 55:
        raise ValueError("at least 55 closed candles are required")
    closes = [candle.close for candle in closed]
    ema_20_values = ema(closes, 20)
    ema_50_values = ema(closes, 50)
    ema_20 = ema_20_values[-1]
    ema_50 = ema_50_values[-1]
    slope_base = ema_20_values[-4]
    slope_pct = (ema_20 - slope_base) / slope_base * 100 if slope_base else 0
    atr_14 = atr(closed, 14)
    previous_volumes = [candle.volume for candle in closed[-21:-1]]
    average_volume = sum(previous_volumes) / len(previous_volumes)
    volume_ratio = closed[-1].volume / average_volume if average_volume else 0
    close = closed[-1].close
    return TimeframeMetrics(
        interval=interval,
        close=close,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_20_slope_pct=slope_pct,
        atr_14=atr_14,
        atr_percent=atr_14 / close * 100 if close else 0,
        volume_ratio=volume_ratio,
        closed_candles=len(closed),
        last_closed_at=closed[-1].start_time,
    )
