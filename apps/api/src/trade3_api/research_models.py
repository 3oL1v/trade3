from datetime import datetime

from pydantic import BaseModel, Field


class ReplayTrade(BaseModel):
    symbol: str
    direction: str
    score: float = Field(ge=0, le=100)
    signal_at: datetime
    entered_at: datetime
    closed_at: datetime | None
    outcome: str | None
    gross_result_r: float
    net_result_r: float
    fee_cost_r: float = Field(ge=0)
    slippage_cost_r: float = Field(ge=0)


class ReplayBreakdown(BaseModel):
    label: str
    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    cumulative_net_r: float | None
    max_drawdown_r: float | None = Field(default=None, ge=0)


class HistoricalReplayReport(BaseModel):
    generated_at: datetime
    strategy: str = "trend_pullback_v1"
    execution_policy: str = "tp1_or_stop_all_out_v1"
    symbols: list[str]
    start: datetime
    end: datetime
    warmup_days: int = Field(ge=1)
    spread_bps: float = Field(ge=0)
    taker_fee_rate_pct: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    total_recorded_signals: int = Field(ge=0)
    resolved_trades: int = Field(ge=0)
    censored_signals: int = Field(ge=0)
    ambiguous_signals: int = Field(ge=0)
    skipped_signals: int = Field(default=0, ge=0)
    gross_expectancy_r: float | None
    net_expectancy_r: float | None
    average_fee_cost_r: float | None = Field(default=None, ge=0)
    average_slippage_cost_r: float | None = Field(default=None, ge=0)
    average_total_cost_r: float | None = Field(default=None, ge=0)
    overall: ReplayBreakdown
    score_buckets: list[ReplayBreakdown]
    directions: list[ReplayBreakdown]
    trades: list[ReplayTrade]
    limitations: list[str]


class StrategyResearchStatus(BaseModel):
    strategy: str
    status: str
    tested_start: datetime
    tested_end: datetime
    tested_symbols: list[str]
    resolved_trades: int = Field(ge=0)
    net_expectancy_r: float
    profit_factor: float = Field(ge=0)
    approved_for_calls: bool
    note: str
