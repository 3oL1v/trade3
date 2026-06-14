from datetime import UTC, datetime

from trade3_api.fixed_verification import (
    SymbolSummary,
    VerificationCriteria,
    evaluate_verification,
)
from trade3_api.overnight_research import ReplaySummary
from trade3_api.research_models import ReplayTrade


def _trade(symbol: str, result: float, minute: int) -> ReplayTrade:
    timestamp = datetime(2025, 7, 1, 0, minute, tzinfo=UTC)
    return ReplayTrade(
        symbol=symbol,
        direction="long",
        score=80,
        signal_at=timestamp,
        entered_at=timestamp,
        closed_at=timestamp,
        outcome="target_complete" if result > 0 else "stop_before_target",
        gross_result_r=result,
        net_result_r=result,
        fee_cost_r=0,
        slippage_cost_r=0,
    )


def test_verification_requires_every_predeclared_check() -> None:
    trades = [
        _trade("BTCUSDT", 2, 0),
        _trade("BTCUSDT", -1, 1),
        _trade("ETHUSDT", 2, 2),
        _trade("ETHUSDT", -1, 3),
    ]
    windows = [
        ReplaySummary(
            trades=2,
            expectancy_r=0.5,
            profit_factor=2,
            cumulative_net_r=1,
            max_drawdown_r=1,
            win_rate=0.5,
            profitable_symbols=2,
        ),
        ReplaySummary(
            trades=2,
            expectancy_r=0.5,
            profit_factor=2,
            cumulative_net_r=1,
            max_drawdown_r=1,
            win_rate=0.5,
            profitable_symbols=2,
        ),
    ]
    symbols = [
        SymbolSummary(
            symbol="BTCUSDT",
            trades=2,
            expectancy_r=0.5,
            cumulative_net_r=1,
            profit_factor=2,
            win_rate=0.5,
        ),
        SymbolSummary(
            symbol="ETHUSDT",
            trades=2,
            expectancy_r=0.5,
            cumulative_net_r=1,
            profit_factor=2,
            win_rate=0.5,
        ),
    ]
    criteria = VerificationCriteria(
        minimum_total_trades=4,
        minimum_profitable_symbols=2,
        minimum_aggregate_profit_factor=1.5,
        maximum_single_symbol_profit_share=0.5,
    )

    decision = evaluate_verification(criteria, windows, symbols, trades)

    assert decision.passed is True
    assert all(decision.checks.values())
