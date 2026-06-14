from datetime import datetime

from pydantic import BaseModel, Field


class OrderBookLevel(BaseModel):
    price: float = Field(gt=0)
    size: float = Field(gt=0)


class OrderBookSnapshot(BaseModel):
    symbol: str
    source_time: datetime
    matching_engine_time: datetime
    update_id: int = Field(ge=0)
    sequence: int = Field(ge=0)
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


class PublicTrade(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    size: float = Field(gt=0)
    side: str
    time: datetime


class LiquidationPrint(BaseModel):
    symbol: str
    position_side: str
    price: float = Field(gt=0)
    size: float = Field(gt=0)
    notional_usdt: float = Field(gt=0)
    time: datetime


class OrderBookBand(BaseModel):
    distance_bps: int = Field(gt=0)
    bid_notional_usdt: float = Field(ge=0)
    ask_notional_usdt: float = Field(ge=0)
    imbalance: float = Field(ge=-1, le=1)
    depth_complete: bool


class TradeFlowWindow(BaseModel):
    window_seconds: int = Field(gt=0)
    trade_count: int = Field(ge=0)
    taker_buy_usdt: float = Field(ge=0)
    taker_sell_usdt: float = Field(ge=0)
    imbalance: float = Field(ge=-1, le=1)
    sample_truncated: bool


class LiquidationWindow(BaseModel):
    window_minutes: int = Field(gt=0)
    event_count: int = Field(ge=0)
    long_liquidated_usdt: float = Field(ge=0)
    short_liquidated_usdt: float = Field(ge=0)
    imbalance: float = Field(ge=-1, le=1)


class MarketFlowSnapshot(BaseModel):
    symbol: str
    generated_at: datetime
    orderbook_source_time: datetime
    mid_price: float = Field(gt=0)
    spread_bps: float = Field(ge=0)
    orderbook_bands: list[OrderBookBand]
    trade_flow: TradeFlowWindow
    liquidations: list[LiquidationWindow]
    methodology_note: str = (
        "Orderbook is a REST snapshot without RPI orders; trade flow uses recent taker side; "
        "liquidation notional uses bankruptcy price."
    )
