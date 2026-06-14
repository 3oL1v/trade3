from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class SetupType(StrEnum):
    TREND_PULLBACK = "trend_pullback"
    BREAKOUT_RETEST = "breakout_retest"
    LIQUIDITY_SWEEP_REVERSAL = "liquidity_sweep_reversal"


class ScoreComponents(BaseModel):
    higher_timeframe_alignment: float = Field(ge=0, le=100)
    market_structure: float = Field(ge=0, le=100)
    volume_impulse: float = Field(ge=0, le=100)
    level_quality: float = Field(ge=0, le=100)
    entry_confirmation: float = Field(ge=0, le=100)
    liquidity: float = Field(ge=0, le=100)
    market_regime: float = Field(ge=0, le=100)
    reward_risk: float = Field(ge=0, le=100)


class ScoreRequest(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}USDT$")
    direction: Direction
    setup_type: SetupType
    components: ScoreComponents
    penalties: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_penalties(self) -> "ScoreRequest":
        invalid = {name: value for name, value in self.penalties.items() if not 0 <= value <= 100}
        if invalid:
            raise ValueError(f"penalties must be between 0 and 100: {invalid}")
        return self


class ScoreResult(BaseModel):
    quality_score: float
    band: str
    calibrated_probability: float | None = None
    total_penalty: float


class PositionSizeRequest(BaseModel):
    equity_usdt: float = Field(gt=0)
    risk_percent: float = Field(gt=0, le=0.5)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    leverage: float = Field(ge=1, le=3)

    @model_validator(mode="after")
    def validate_stop(self) -> "PositionSizeRequest":
        if self.entry_price == self.stop_price:
            raise ValueError("entry_price and stop_price must differ")
        return self


class PositionSizeConstraint(StrEnum):
    RISK = "risk"
    MARGIN = "margin"


class PositionSizeResult(BaseModel):
    requested_risk_usdt: float
    risk_usdt: float
    effective_risk_percent: float
    stop_distance_percent: float
    quantity: float
    notional_usdt: float
    estimated_margin_usdt: float
    margin_utilization_percent: float
    binding_constraint: PositionSizeConstraint
