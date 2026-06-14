import pytest

from trade3_api.execution import model_execution


def test_modeled_execution_matches_long_cost_contract() -> None:
    result = model_execution(
        direction="long",
        entry_price=101,
        stop_price=98,
        exit_reference_price=104,
        taker_fee_rate_pct=0.055,
        slippage_bps=2,
    )

    assert result.gross_result_r == 1
    assert result.entry_fill_price == pytest.approx(101.0202)
    assert result.exit_fill_price == pytest.approx(103.9792)
    assert result.net_result_r == pytest.approx(0.94875)


def test_modeled_execution_rejects_zero_risk() -> None:
    with pytest.raises(ValueError, match="positive risk"):
        model_execution(
            direction="short",
            entry_price=100,
            stop_price=100,
            exit_reference_price=90,
            taker_fee_rate_pct=0.055,
            slippage_bps=2,
        )
