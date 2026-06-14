from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DecisionAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    DEFER = "defer"


class DecisionDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class ManualDecisionRequest(BaseModel):
    """A discretionary decision the user makes against the analysis shown to them.

    The full analysis and AI snapshots are stored verbatim so the record always
    reflects exactly what was on screen when the user decided.
    """

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}USDT$")
    action: DecisionAction
    direction: DecisionDirection = DecisionDirection.NONE
    ai_verdict: str | None = None
    ai_conviction: str | None = None
    snapshot_generated_at: datetime | None = None
    note: str | None = Field(default=None, max_length=2000)
    analysis_snapshot: dict[str, Any] | None = None
    ai_review: dict[str, Any] | None = None


class ManualDecision(BaseModel):
    id: int = Field(ge=1)
    symbol: str
    action: DecisionAction
    direction: DecisionDirection
    ai_verdict: str | None
    ai_conviction: str | None
    agreed_with_ai: bool | None
    snapshot_generated_at: datetime | None
    recorded_at: datetime
    note: str | None
    analysis_snapshot: dict[str, Any] | None
    ai_review: dict[str, Any] | None


class ManualDecisionList(BaseModel):
    decisions: list[ManualDecision]


class ManualDecisionStats(BaseModel):
    total: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    deferred: int = Field(ge=0)
    longs: int = Field(ge=0)
    shorts: int = Field(ge=0)
    accept_rate: float | None
    ai_comparable: int = Field(ge=0)
    agreed_with_ai: int = Field(ge=0)
    agreement_rate: float | None
    note: str = (
        "Manual discretionary decisions, separate from the retired deterministic-strategy "
        "journal. Trade outcomes are not tracked yet."
    )
