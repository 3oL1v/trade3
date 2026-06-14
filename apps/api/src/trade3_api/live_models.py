from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EngineState(StrEnum):
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class LiveTicker(BaseModel):
    symbol: str
    last_price: float = Field(gt=0)
    mark_price: float = Field(ge=0)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    turnover_24h_usdt: float = Field(ge=0)
    open_interest_usdt: float = Field(ge=0)
    funding_rate: float
    source_time: datetime
    received_at: datetime


class LiveEngineStatus(BaseModel):
    state: EngineState
    enabled: bool
    journal_enabled: bool
    symbols: list[str]
    intervals: list[str]
    started_at: datetime | None
    last_message_at: datetime | None
    last_universe_refresh_at: datetime | None
    reconnect_count: int = Field(ge=0)
    last_error: str | None
    clock_skew_seconds: float | None
    clock_synchronized: bool
    ticker_count: int = Field(ge=0)
    candle_series_count: int = Field(ge=0)


class TimeframeMetrics(BaseModel):
    interval: str
    close: float
    ema_20: float
    ema_50: float
    ema_20_slope_pct: float
    atr_14: float
    atr_percent: float
    volume_ratio: float
    closed_candles: int
    last_closed_at: datetime


class PriceZone(BaseModel):
    lower: float = Field(gt=0)
    upper: float = Field(gt=0)


class TradeTarget(BaseModel):
    label: str
    price: float = Field(gt=0)
    reward_risk: float = Field(gt=0)


class TrendPullbackPlan(BaseModel):
    setup_type: str = "trend_pullback"
    status: str
    pullback_zone: PriceZone
    trigger_price: float = Field(gt=0)
    entry_zone: PriceZone
    invalidation_price: float = Field(gt=0)
    structural_target: float | None = Field(default=None, gt=0)
    risk_per_unit: float = Field(gt=0)
    structural_reward_risk: float | None = Field(default=None, gt=0)
    stop_distance_atr: float = Field(gt=0)
    touched_at: datetime | None
    confirmation_at: datetime | None
    targets: list[TradeTarget]
    notes: list[str]


class IntradayCandidate(BaseModel):
    rank: int = Field(ge=1)
    symbol: str
    direction: str
    score: float = Field(ge=0, le=100)
    state: str
    last_price: float
    spread_bps: float
    funding_rate_pct: float
    turnover_24h_usdt: float
    open_interest_usdt: float
    pullback_distance_atr: float
    timeframe_1h: TimeframeMetrics
    timeframe_15m: TimeframeMetrics
    timeframe_5m: TimeframeMetrics
    reasons: list[str]
    trade_plan: TrendPullbackPlan | None = None


class IntradayScan(BaseModel):
    generated_at: datetime
    engine_state: EngineState
    universe_size: int
    analyzed_count: int
    candidates: list[IntradayCandidate]
    score_note: str = "Deterministic setup-quality score; not a win probability."
