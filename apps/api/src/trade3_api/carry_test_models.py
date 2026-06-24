from datetime import datetime

from pydantic import BaseModel, Field


class CarryPositionRequest(BaseModel):
    """A market-neutral carry position the collector opens on paper, no execution.

    The directional price move is assumed hedged out (perp short + spot long, or
    the reverse), so the realized result is the funding collected over the window
    minus the round-trip fees on both legs.
    """

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}USDT$")
    side: str  # "short_perp_long_spot" | "long_perp_short_spot"
    entry_funding_rate_pct: float
    entry_apr_pct: float
    funding_interval_hours: float = Field(gt=0)
    round_trip_fee_pct: float = Field(ge=0)


class CarryPosition(BaseModel):
    id: int = Field(ge=1)
    symbol: str
    side: str
    entry_funding_rate_pct: float
    entry_apr_pct: float
    funding_interval_hours: float
    round_trip_fee_pct: float
    opened_at: datetime
    resolved_at: datetime | None
    realized_funding_pct: float | None
    net_carry_pct: float | None
    annualized_net_apr_pct: float | None
    funding_events: int | None


class CarryPositionList(BaseModel):
    positions: list[CarryPosition]


class CarryTestStats(BaseModel):
    total: int = Field(ge=0)
    open_positions: int = Field(ge=0)
    resolved: int = Field(ge=0)
    due_for_resolution: int = Field(ge=0)
    win_rate_after_fees: float | None
    positive_after_fees: int = Field(ge=0)
    mean_realized_funding_pct: float | None
    mean_net_carry_pct: float | None
    mean_annualized_net_apr_pct: float | None
    horizon_hours: float
    scan_seconds: float
    note: str = (
        "Paper forward test of market-neutral funding carry. Each position assumes the "
        "directional move is hedged out, so the result is the funding actually realized "
        "over the holding window minus the round-trip taker fees on both legs. It ignores "
        "basis drift, spot-short borrow cost, and slippage, so treat it as an optimistic "
        "upper bound on net carry, not live P&L."
    )
