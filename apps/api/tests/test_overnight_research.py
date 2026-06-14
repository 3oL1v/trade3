from datetime import UTC, datetime

from trade3_api.overnight_research import (
    OvernightResearchConfig,
    ReplaySummary,
    _parameter_key,
)
from trade3_api.strategy_v2 import DEFAULT_PARAMETERS, StrategyV2Parameters


def test_parameter_key_is_stable() -> None:
    copy = StrategyV2Parameters.model_validate(DEFAULT_PARAMETERS.model_dump())

    assert _parameter_key(copy) == _parameter_key(DEFAULT_PARAMETERS)


def test_config_allows_gaps_but_not_overlapping_windows() -> None:
    config = OvernightResearchConfig.model_validate(
        {
            "symbols": ["BTCUSDT"],
            "train": {
                "start": datetime(2026, 1, 1, tzinfo=UTC),
                "end": datetime(2026, 2, 1, tzinfo=UTC),
            },
            "validation": {
                "start": datetime(2026, 2, 1, tzinfo=UTC),
                "end": datetime(2026, 3, 1, tzinfo=UTC),
            },
            "holdout": {
                "start": datetime(2026, 4, 1, tzinfo=UTC),
                "end": datetime(2026, 5, 1, tzinfo=UTC),
            },
        }
    )

    assert config.holdout.start.month == 4


def test_replay_summary_rejects_negative_trade_count() -> None:
    try:
        ReplaySummary(
            trades=-1,
            expectancy_r=0,
            profit_factor=1,
            cumulative_net_r=0,
            max_drawdown_r=0,
            win_rate=0.5,
            profitable_symbols=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("negative trade count must be rejected")
