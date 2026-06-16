from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .live_models import PriceZone


class MarketBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"
    INSUFFICIENT = "insufficient"


class ZoneKind(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    BULLISH_FVG = "bullish_fvg"
    BEARISH_FVG = "bearish_fvg"
    BULLISH_ORDER_BLOCK = "bullish_order_block"
    BEARISH_ORDER_BLOCK = "bearish_order_block"
    LIQUIDITY_HIGH = "liquidity_high"
    LIQUIDITY_LOW = "liquidity_low"


class SwingPoint(BaseModel):
    timeframe: str
    kind: str
    time: datetime
    price: float = Field(gt=0)
    strength: int = Field(ge=1)


class StructureEvent(BaseModel):
    timeframe: str
    kind: str
    time: datetime
    price: float = Field(gt=0)
    description: str


class TimeframeStructure(BaseModel):
    timeframe: str
    bias: MarketBias
    last_close: float = Field(gt=0)
    atr: float = Field(gt=0)
    swing_highs: list[SwingPoint]
    swing_lows: list[SwingPoint]
    events: list[StructureEvent]
    summary: str


class AnalysisZone(BaseModel):
    id: str
    timeframe: str
    kind: ZoneKind
    lower: float = Field(gt=0)
    upper: float = Field(gt=0)
    start_time: datetime
    end_time: datetime
    status: str
    strength: str
    touches: int = Field(ge=1)
    rationale: str


class AnalysisTrendLine(BaseModel):
    id: str
    timeframe: str
    kind: str
    start_time: datetime
    start_price: float = Field(gt=0)
    end_time: datetime
    end_price: float = Field(gt=0)


class FlagPattern(BaseModel):
    timeframe: str
    direction: str  # "bull" | "bear"
    status: str  # "forming" | "breakout"
    pole_start_time: datetime
    pole_start_price: float = Field(gt=0)
    pole_end_time: datetime
    pole_end_price: float = Field(gt=0)
    flag_start_time: datetime
    flag_end_time: datetime
    flag_upper: float = Field(gt=0)
    flag_lower: float = Field(gt=0)
    rationale: str


class ScenarioTarget(BaseModel):
    label: str
    price: float = Field(gt=0)
    reward_risk: float = Field(gt=0)


class TradeScenario(BaseModel):
    direction: str
    status: str
    quality: str
    entry_zone: PriceZone
    trigger: str
    invalidation_price: float = Field(gt=0)
    targets: list[ScenarioTarget]
    evidence: list[str]
    conflicts: list[str]


class MarketAnalysisSnapshot(BaseModel):
    symbol: str
    generated_at: datetime
    last_price: float = Field(gt=0)
    preferred_direction: str
    decision: str
    structures: list[TimeframeStructure]
    zones: list[AnalysisZone]
    trend_lines: list[AnalysisTrendLine]
    flags: list[FlagPattern] = Field(default_factory=list)
    scenarios: list[TradeScenario]
    methodology_note: str = (
        "Geometry is deterministic; scenario quality is a confluence label, not a win probability."
    )
