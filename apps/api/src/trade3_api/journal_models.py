from datetime import datetime

from pydantic import BaseModel, Field

from .live_models import TradeTarget


class TargetHit(BaseModel):
    label: str
    price: float = Field(gt=0)
    reward_risk: float = Field(gt=0)
    hit_at: datetime


class JournalSignal(BaseModel):
    id: int = Field(ge=1)
    fingerprint: str
    symbol: str
    direction: str
    setup_type: str
    plan_status: str
    lifecycle_state: str
    outcome: str | None
    score: float = Field(ge=0, le=100)
    signal_at: datetime
    recorded_at: datetime
    entered_at: datetime | None
    closed_at: datetime | None
    entry_lower: float = Field(gt=0)
    entry_upper: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    structural_reward_risk: float | None
    targets: list[TradeTarget]
    target_hits: list[TargetHit]
    mfe_r: float = Field(ge=0)
    mae_r: float = Field(ge=0)
    result_r: float | None
    execution_policy: str
    taker_fee_rate_pct: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    exit_reference_price: float | None
    entry_fill_price: float | None
    exit_fill_price: float | None
    fee_cost_r: float | None = Field(default=None, ge=0)
    slippage_cost_r: float | None = Field(default=None, ge=0)
    net_result_r: float | None
    last_evaluated_at: datetime | None


class JournalSignalList(BaseModel):
    signals: list[JournalSignal]


class JournalStats(BaseModel):
    total_signals: int = Field(ge=0)
    pending_entry: int = Field(ge=0)
    active: int = Field(ge=0)
    closed: int = Field(ge=0)
    entered: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    expired_without_entry: int = Field(ge=0)
    missed_at_recording: int = Field(ge=0)
    stop_before_target: int = Field(ge=0)
    stop_after_target: int = Field(ge=0)
    tp1_hits: int = Field(ge=0)
    tp2_hits: int = Field(ge=0)
    structure_hits: int = Field(ge=0)
    tp1_hit_rate: float | None
    average_mfe_r: float | None
    average_mae_r: float | None
    execution_policy: str
    taker_fee_rate_pct: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    resolved_trades: int = Field(ge=0)
    net_wins: int = Field(ge=0)
    net_losses: int = Field(ge=0)
    net_breakeven: int = Field(ge=0)
    net_win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    cumulative_net_r: float | None
    max_drawdown_r: float | None = Field(default=None, ge=0)
    average_fee_cost_r: float | None = Field(default=None, ge=0)
    average_slippage_cost_r: float | None = Field(default=None, ge=0)
    minimum_sample_size: int = Field(ge=1)
    sample_sufficient: bool
    funding_included: bool = False
    note: str = (
        "Conservative virtual baseline; funding and real order-book impact are not included."
    )
