from datetime import datetime

from pydantic import BaseModel, Field


class LinearInstrument(BaseModel):
    symbol: str
    base_coin: str
    contract_type: str
    status: str
    quote_coin: str
    settle_coin: str
    is_pre_listing: bool
    launch_time: datetime
    tick_size: float = Field(gt=0)


class LinearTicker(BaseModel):
    symbol: str
    last_price: float
    turnover_24h_usdt: float
    volume_24h: float
    open_interest_usdt: float
    bid_price: float
    ask_price: float
    funding_rate: float
    price_change_24h_pct: float


class MarketCandidate(BaseModel):
    rank: int = Field(ge=1)
    symbol: str
    base_coin: str
    last_price: float
    turnover_24h_usdt: float
    open_interest_usdt: float
    spread_bps: float
    funding_rate_pct: float
    price_change_24h_pct: float
    launch_time: datetime
    listing_age_days: int = Field(ge=0)
    tick_size: float = Field(gt=0)


class UniverseCriteria(BaseModel):
    quote_coin: str = "USDT"
    contract_type: str = "LinearPerpetual"
    max_spread_bps: float
    min_turnover_24h_usdt: float
    min_open_interest_usdt: float
    min_listing_age_days: int
    max_abs_funding_rate_pct: float
    max_abs_price_change_24h_pct: float
    allowed_base_coins: list[str]
    excluded_base_coins: list[str]


class MarketUniverse(BaseModel):
    exchange: str = "bybit"
    generated_at: datetime
    source_time: datetime
    requested_limit: int
    eligible_count: int
    rejected_count: int
    criteria: UniverseCriteria
    markets: list[MarketCandidate]


class Candle(BaseModel):
    start_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover_usdt: float
    is_closed: bool


class CandleSeries(BaseModel):
    exchange: str = "bybit"
    symbol: str
    interval: str
    source_time: datetime
    candles: list[Candle]
