from .models import (
    PositionSizeConstraint,
    PositionSizeRequest,
    PositionSizeResult,
    ScoreRequest,
    ScoreResult,
)

SCORE_WEIGHTS = {
    "higher_timeframe_alignment": 0.20,
    "market_structure": 0.15,
    "volume_impulse": 0.15,
    "level_quality": 0.10,
    "entry_confirmation": 0.10,
    "liquidity": 0.10,
    "market_regime": 0.10,
    "reward_risk": 0.10,
}


def calculate_quality_score(request: ScoreRequest) -> ScoreResult:
    values = request.components.model_dump()
    raw_score = sum(values[name] * weight for name, weight in SCORE_WEIGHTS.items())
    total_penalty = min(sum(request.penalties.values()), 100.0)
    score = round(max(0.0, min(100.0, raw_score - total_penalty)), 2)

    if score < 60:
        band = "reject"
    elif score < 70:
        band = "watch"
    elif score < 80:
        band = "standard"
    else:
        band = "strong"

    return ScoreResult(
        quality_score=score,
        band=band,
        calibrated_probability=None,
        total_penalty=round(total_penalty, 2),
    )


def calculate_position_size(request: PositionSizeRequest) -> PositionSizeResult:
    requested_risk_usdt = request.equity_usdt * (request.risk_percent / 100)
    stop_distance = abs(request.entry_price - request.stop_price)
    risk_quantity = requested_risk_usdt / stop_distance
    margin_quantity = request.equity_usdt * request.leverage / request.entry_price
    quantity = min(risk_quantity, margin_quantity)
    notional = quantity * request.entry_price
    margin = notional / request.leverage
    risk_usdt = quantity * stop_distance
    binding_constraint = (
        PositionSizeConstraint.RISK
        if risk_quantity <= margin_quantity
        else PositionSizeConstraint.MARGIN
    )

    return PositionSizeResult(
        requested_risk_usdt=round(requested_risk_usdt, 8),
        risk_usdt=round(risk_usdt, 8),
        effective_risk_percent=round(risk_usdt / request.equity_usdt * 100, 6),
        stop_distance_percent=round(stop_distance / request.entry_price * 100, 6),
        quantity=round(quantity, 8),
        notional_usdt=round(notional, 8),
        estimated_margin_usdt=round(margin, 8),
        margin_utilization_percent=round(margin / request.equity_usdt * 100, 6),
        binding_constraint=binding_constraint,
    )
