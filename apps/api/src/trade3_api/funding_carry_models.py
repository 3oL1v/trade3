from datetime import datetime

from pydantic import BaseModel, Field


class CarryOpportunity(BaseModel):
    """A market-neutral funding-carry candidate for one symbol.

    Carry is collected by holding the perp short + spot long when funding is
    positive (or the reverse when negative), so the directional price move
    cancels and you net the funding minus trading costs. Annualized figures
    assume the current funding rate persists — they are an upper bound, which is
    why the realized-history fields and the breakeven horizon matter.
    """

    symbol: str
    base_coin: str
    last_price: float = Field(gt=0)
    funding_rate_pct: float
    funding_interval_hours: float = Field(gt=0)
    annualized_apr_pct: float
    side: str  # "short_perp_long_spot" | "long_perp_short_spot"
    side_label: str
    easily_hedgeable: bool
    breakeven_hours: float | None
    turnover_24h_usdt: float
    open_interest_usdt: float
    mean_funding_rate_pct: float | None
    positive_fraction: float | None
    history_samples: int = Field(ge=0)


class CarryBoard(BaseModel):
    generated_at: datetime
    source_time: datetime
    taker_fee_rate_pct: float
    round_trip_fee_pct: float
    eligible_count: int = Field(ge=0)
    opportunities: list[CarryOpportunity] = Field(default_factory=list)
    note: str = (
        "Market-neutral funding carry, research only. Annualized APR assumes the "
        "current funding rate persists, so treat it as an upper bound; the realized "
        "mean and same-sign fraction over recent history show how stable it has been. "
        "breakeven_hours is how long the hedge must be held for funding to cover the "
        "round-trip taker fees on both legs. Negative-funding rows need a spot short "
        "(borrow), which is harder, so easily_hedgeable is false for them."
    )
