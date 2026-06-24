from datetime import datetime

from pydantic import BaseModel, Field


class AutoSignalRequest(BaseModel):
    """A signal the system emits on its own, with no human in the loop.

    The collector snapshots the deterministic ``preferred_direction`` for a
    symbol and records the price at that moment together with the benchmark
    price, so the call can be scored against a buy-and-hold benchmark later.
    """

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}USDT$")
    direction: str
    decision_price: float | None = Field(default=None, gt=0)
    generated_at: datetime | None = None
    benchmark_symbol: str | None = None
    benchmark_price: float | None = Field(default=None, gt=0)


class AutoSignal(BaseModel):
    id: int = Field(ge=1)
    symbol: str
    direction: str
    decision_price: float | None
    generated_at: datetime | None
    recorded_at: datetime
    outcome_price: float | None
    outcome_at: datetime | None
    forward_return_pct: float | None
    benchmark_symbol: str | None
    benchmark_price: float | None
    benchmark_outcome_price: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None


class AutoSignalList(BaseModel):
    signals: list[AutoSignal]


class AutoSymbolBreakdown(BaseModel):
    symbol: str
    resolved: int = Field(ge=0)
    win_rate: float | None
    average_return_pct: float | None
    average_excess_return_pct: float | None


class AutoSignalStats(BaseModel):
    total: int = Field(ge=0)
    longs: int = Field(ge=0)
    shorts: int = Field(ge=0)
    neutrals: int = Field(ge=0)
    directional: int = Field(ge=0)
    pending_resolution: int = Field(ge=0)
    due_for_resolution: int = Field(ge=0)
    resolved: int = Field(ge=0)
    directional_resolved: int = Field(ge=0)
    win_rate: float | None
    average_return_pct: float | None
    benchmark_resolved: int = Field(ge=0)
    average_excess_return_pct: float | None
    beat_benchmark_rate: float | None
    coin_toss_z: float | None
    by_symbol: list[AutoSymbolBreakdown] = Field(default_factory=list)
    horizon_hours: float = 8
    scan_seconds: float = 1800
    note: str = (
        "Автоматический форвард-тест направленного сигнала системы (preferred_direction). "
        "Человек не участвует: сырая направленная доходность сравнивается с buy-and-hold "
        "по BTC, до комиссий. |z| выше ~2 означает, что win rate на этой выборке вряд ли "
        "объясним подбрасыванием монеты."
    )
