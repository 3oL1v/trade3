import pytest
from pydantic import ValidationError

from trade3_api.models import PositionSizeRequest, ScoreComponents, ScoreRequest
from trade3_api.services import calculate_position_size, calculate_quality_score


def test_quality_score_applies_weights_and_penalties() -> None:
    request = ScoreRequest(
        symbol="BTCUSDT",
        direction="long",
        setup_type="trend_pullback",
        components=ScoreComponents(
            higher_timeframe_alignment=90,
            market_structure=80,
            volume_impulse=75,
            level_quality=80,
            entry_confirmation=70,
            liquidity=100,
            market_regime=85,
            reward_risk=80,
        ),
        penalties={"adverse_funding": 4, "nearby_resistance": 3},
    )

    result = calculate_quality_score(request)

    assert result.quality_score == 75.75
    assert result.band == "standard"
    assert result.calibrated_probability is None


def test_position_size_uses_monetary_risk_not_leverage() -> None:
    result = calculate_position_size(
        PositionSizeRequest(
            equity_usdt=10_000,
            risk_percent=0.25,
            entry_price=100,
            stop_price=99,
            leverage=2,
        )
    )

    assert result.requested_risk_usdt == 25
    assert result.risk_usdt == 25
    assert result.effective_risk_percent == 0.25
    assert result.quantity == 25
    assert result.notional_usdt == 2_500
    assert result.estimated_margin_usdt == 1_250
    assert result.margin_utilization_percent == 12.5
    assert result.binding_constraint == "risk"


def test_position_size_is_capped_by_available_margin() -> None:
    result = calculate_position_size(
        PositionSizeRequest(
            equity_usdt=1_000,
            risk_percent=0.5,
            entry_price=100,
            stop_price=99.9,
            leverage=2,
        )
    )

    assert result.requested_risk_usdt == 5
    assert result.risk_usdt == 2
    assert result.effective_risk_percent == 0.2
    assert result.quantity == 20
    assert result.notional_usdt == 2_000
    assert result.estimated_margin_usdt == 1_000
    assert result.margin_utilization_percent == 100
    assert result.binding_constraint == "margin"


def test_risk_above_initial_policy_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PositionSizeRequest(
            equity_usdt=10_000,
            risk_percent=0.75,
            entry_price=100,
            stop_price=99,
            leverage=2,
        )
