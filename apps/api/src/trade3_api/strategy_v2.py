from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .execution import model_execution
from .indicators import aligned_ema, atr, timeframe_metrics
from .market_models import Candle


class StrategyV2Parameters(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_trend_separation_atr: float = Field(default=0.35, ge=0.1, le=1.5)
    pullback_lookback: int = Field(default=4, ge=2, le=10)
    pullback_band_atr: float = Field(default=0.25, ge=0.05, le=0.75)
    min_stop_atr: float = Field(default=1.25, ge=0.5, le=2.5)
    min_stop_percent: float = Field(default=0.75, ge=0.25, le=1.5)
    max_stop_percent: float = Field(default=3.0, ge=1.5, le=5.0)
    target_r: float = Field(default=2.0, ge=1.2, le=4.0)
    min_volume_ratio: float = Field(default=1.1, ge=0.6, le=2.0)
    min_close_strength: float = Field(default=0.65, ge=0.5, le=0.85)
    stop_buffer_atr: float = Field(default=0.25, ge=0.05, le=0.5)
    max_modeled_cost_r: float = Field(default=0.2, ge=0.1, le=0.35)
    max_hold_hours: int = Field(default=12, ge=4, le=24)

    @model_validator(mode="after")
    def validate_stop_range(self) -> "StrategyV2Parameters":
        if self.min_stop_percent >= self.max_stop_percent:
            raise ValueError("min_stop_percent must be below max_stop_percent")
        return self


DEFAULT_PARAMETERS = StrategyV2Parameters()
MIN_TREND_SEPARATION_ATR = DEFAULT_PARAMETERS.min_trend_separation_atr
PULLBACK_LOOKBACK = DEFAULT_PARAMETERS.pullback_lookback
PULLBACK_BAND_ATR = DEFAULT_PARAMETERS.pullback_band_atr
MIN_STOP_ATR = DEFAULT_PARAMETERS.min_stop_atr
MIN_STOP_PERCENT = DEFAULT_PARAMETERS.min_stop_percent
MAX_STOP_PERCENT = DEFAULT_PARAMETERS.max_stop_percent
TARGET_R = DEFAULT_PARAMETERS.target_r
MIN_VOLUME_RATIO = DEFAULT_PARAMETERS.min_volume_ratio
MAX_MODELED_COST_R = DEFAULT_PARAMETERS.max_modeled_cost_r


class V2Signal(BaseModel):
    symbol: str
    direction: str
    score: float = Field(ge=0, le=100)
    signal_at: datetime
    confirmation_at: datetime
    pullback_at: datetime
    estimated_entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    estimated_target_price: float = Field(gt=0)
    estimated_cost_r: float = Field(ge=0)


def find_v2_signal(
    *,
    symbol: str,
    candles_15m: list[Candle],
    candles_1h: list[Candle],
    evaluation_at: datetime,
    tick_size: float,
    taker_fee_rate_pct: float,
    slippage_bps: float,
    parameters: StrategyV2Parameters = DEFAULT_PARAMETERS,
) -> V2Signal | None:
    closed_15m = _closed(candles_15m)
    closed_1h = _closed(candles_1h)
    if len(closed_15m) < 60 or len(closed_1h) < 55:
        return None
    confirmation = closed_15m[-1]
    if confirmation.start_time + timedelta(minutes=15) != evaluation_at:
        return None

    metrics_1h = timeframe_metrics(closed_1h, "60")
    metrics_15m = timeframe_metrics(closed_15m, "15")
    separation = abs(metrics_1h.ema_20 - metrics_1h.ema_50) / metrics_1h.atr_14
    if separation < parameters.min_trend_separation_atr:
        return None
    direction = _direction(metrics_1h, metrics_15m)
    if direction is None:
        return None

    closes = [candle.close for candle in closed_15m]
    ema_20_values = aligned_ema(closes, 20)
    ema_50_values = aligned_ema(closes, 50)
    current_atr = atr(closed_15m, 14)
    pullback_index = _pullback_index(
        direction,
        closed_15m,
        ema_20_values,
        ema_50_values,
        current_atr,
        parameters,
    )
    if pullback_index is None:
        return None
    if not _confirmation_holds(
        direction,
        closed_15m,
        pullback_index,
        metrics_15m,
        parameters,
    ):
        return None

    entry = confirmation.close
    stop = _stop(
        direction,
        closed_15m[pullback_index:],
        entry,
        current_atr,
        tick_size,
        parameters,
    )
    risk = abs(entry - stop)
    stop_percent = risk / entry * 100
    if not parameters.min_stop_percent <= stop_percent <= parameters.max_stop_percent:
        return None
    target = _round(
        entry
        + (risk * parameters.target_r if direction == "long" else -risk * parameters.target_r),
        tick_size,
        ROUND_FLOOR if direction == "long" else ROUND_CEILING,
    )
    execution = model_execution(
        direction=direction,
        entry_price=entry,
        stop_price=stop,
        exit_reference_price=target,
        taker_fee_rate_pct=taker_fee_rate_pct,
        slippage_bps=slippage_bps,
    )
    estimated_cost = execution.fee_cost_r + execution.slippage_cost_r
    if estimated_cost > parameters.max_modeled_cost_r:
        return None

    score = 70.0
    score += min(10, max(0, (separation - parameters.min_trend_separation_atr) * 20))
    score += min(10, max(0, (metrics_15m.volume_ratio - parameters.min_volume_ratio) * 10))
    score += min(
        10,
        max(0, (_close_strength(direction, confirmation) - parameters.min_close_strength) * 30),
    )
    return V2Signal(
        symbol=symbol,
        direction=direction,
        score=round(score, 2),
        signal_at=evaluation_at,
        confirmation_at=confirmation.start_time,
        pullback_at=closed_15m[pullback_index].start_time,
        estimated_entry_price=entry,
        stop_price=stop,
        estimated_target_price=target,
        estimated_cost_r=round(estimated_cost, 4),
    )


def _direction(metrics_1h, metrics_15m) -> str | None:
    if (
        metrics_1h.close > metrics_1h.ema_20 > metrics_1h.ema_50
        and metrics_1h.ema_20_slope_pct > 0
        and metrics_15m.close > metrics_15m.ema_20 > metrics_15m.ema_50
        and metrics_15m.ema_20_slope_pct > 0
    ):
        return "long"
    if (
        metrics_1h.close < metrics_1h.ema_20 < metrics_1h.ema_50
        and metrics_1h.ema_20_slope_pct < 0
        and metrics_15m.close < metrics_15m.ema_20 < metrics_15m.ema_50
        and metrics_15m.ema_20_slope_pct < 0
    ):
        return "short"
    return None


def _pullback_index(
    direction: str,
    candles: list[Candle],
    ema_20_values: list[float | None],
    ema_50_values: list[float | None],
    current_atr: float,
    parameters: StrategyV2Parameters,
) -> int | None:
    start = max(50, len(candles) - parameters.pullback_lookback - 1)
    for index in range(len(candles) - 2, start - 1, -1):
        ema_20 = ema_20_values[index]
        ema_50 = ema_50_values[index]
        if ema_20 is None or ema_50 is None:
            continue
        candle = candles[index]
        overlaps = (
            candle.low <= ema_20 + current_atr * parameters.pullback_band_atr
            and candle.high >= ema_20 - current_atr * parameters.pullback_band_atr
        )
        holds = candle.close > ema_50 if direction == "long" else candle.close < ema_50
        if overlaps and holds:
            return index
    return None


def _confirmation_holds(
    direction: str,
    candles: list[Candle],
    pullback_index: int,
    metrics_15m,
    parameters: StrategyV2Parameters,
) -> bool:
    confirmation = candles[-1]
    prior = candles[-2]
    strength = _close_strength(direction, confirmation)
    if (
        metrics_15m.volume_ratio < parameters.min_volume_ratio
        or strength < parameters.min_close_strength
    ):
        return False
    if direction == "long":
        trigger = max(candle.high for candle in candles[pullback_index:-1])
        return confirmation.close > trigger and confirmation.close > prior.high
    trigger = min(candle.low for candle in candles[pullback_index:-1])
    return confirmation.close < trigger and confirmation.close < prior.low


def _stop(
    direction: str,
    setup_candles: list[Candle],
    entry: float,
    current_atr: float,
    tick_size: float,
    parameters: StrategyV2Parameters,
) -> float:
    buffer = current_atr * parameters.stop_buffer_atr
    minimum_risk = max(
        current_atr * parameters.min_stop_atr,
        entry * parameters.min_stop_percent / 100,
    )
    if direction == "long":
        structural = min(candle.low for candle in setup_candles) - buffer
        return _round(min(structural, entry - minimum_risk), tick_size, ROUND_FLOOR)
    structural = max(candle.high for candle in setup_candles) + buffer
    return _round(max(structural, entry + minimum_risk), tick_size, ROUND_CEILING)


def _close_strength(direction: str, candle: Candle) -> float:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return 0
    position = (candle.close - candle.low) / candle_range
    return position if direction == "long" else 1 - position


def _round(value: float, tick_size: float, rounding: str) -> float:
    tick = Decimal(str(tick_size))
    units = (Decimal(str(value)) / tick).to_integral_value(rounding=rounding)
    return float(units * tick)


def _closed(candles: list[Candle]) -> list[Candle]:
    return sorted(
        (candle for candle in candles if candle.is_closed),
        key=lambda candle: candle.start_time,
    )
