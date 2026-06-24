from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .analysis_models import MarketBias
from .flow_models import MarketFlowSnapshot


class AiVerdict(StrEnum):
    LONG_CANDIDATE = "long_candidate"
    SHORT_CANDIDATE = "short_candidate"
    WAIT = "wait"


class AiConviction(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AiReviewStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class AiSummaryCode(StrEnum):
    ALIGNED_LONG = "aligned_long"
    ALIGNED_SHORT = "aligned_short"
    MIXED_CONTEXT = "mixed_context"
    RANGE_CONTEXT = "range_context"
    TRIGGER_PENDING = "trigger_pending"
    NO_EDGE = "no_edge"


class AiObservedBiases(BaseModel):
    h4: MarketBias
    h1: MarketBias
    m15: MarketBias
    m5: MarketBias


class AiReviewPayload(BaseModel):
    observed_biases: AiObservedBiases
    verdict: AiVerdict
    conviction: AiConviction
    summary_code: AiSummaryCode
    supporting_fact_ids: list[str] = Field(default_factory=list, max_length=5)
    counter_fact_ids: list[str] = Field(default_factory=list, max_length=5)
    wait_condition_ids: list[str] = Field(default_factory=list, max_length=5)


class AiMarketReview(BaseModel):
    symbol: str
    status: AiReviewStatus
    model: str
    generated_at: datetime
    snapshot_generated_at: datetime
    runtime_ms: int = Field(ge=0)
    advisory_only: bool = True
    market_flow: MarketFlowSnapshot | None = None
    observed_biases: AiObservedBiases
    verdict: AiVerdict
    conviction: AiConviction
    summary_code: AiSummaryCode
    supporting_fact_ids: list[str]
    counter_fact_ids: list[str]
    wait_condition_ids: list[str]
    headline: str
    thesis: str
    confirmations: list[str]
    counterarguments: list[str]
    wait_for: list[str]
    limitations: list[str] = Field(default_factory=list)
