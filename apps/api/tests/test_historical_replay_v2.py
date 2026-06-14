from datetime import UTC, datetime

import pytest

from trade3_api.historical_replay_v2 import _evaluate_position, _open_position
from trade3_api.market_models import Candle
from trade3_api.strategy_v2 import V2Signal


def signal(direction: str = "long") -> V2Signal:
    now = datetime(2026, 4, 13, 10, 0, tzinfo=UTC)
    return V2Signal(
        symbol="BTCUSDT",
        direction=direction,
        score=85,
        signal_at=now,
        confirmation_at=now,
        pullback_at=now,
        estimated_entry_price=100,
        stop_price=99 if direction == "long" else 101,
        estimated_target_price=102 if direction == "long" else 98,
        estimated_cost_r=0.15,
    )


def candle(*, open_price: float, low: float, high: float, close: float) -> Candle:
    return Candle(
        start_time=datetime(2026, 4, 13, 10, 0, tzinfo=UTC),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=10,
        turnover_usdt=1_000,
        is_closed=True,
    )


def test_v2_uses_next_5m_open_and_recomputes_two_r_target() -> None:
    position = _open_position(signal(), entry_price=100.2)

    assert position is not None
    assert position.entry_price == 100.2
    assert position.stop_price == 99
    assert position.target_price == pytest.approx(102.6)


def test_v2_marks_same_candle_stop_and_target_as_ambiguous() -> None:
    position = _open_position(signal(), entry_price=100)

    assert position is not None
    result = _evaluate_position(
        position,
        candle(open_price=100, low=98.5, high=102.5, close=101),
        taker_fee_rate_pct=0.055,
        slippage_bps=2,
    )

    assert result == "ambiguous"


def test_v2_target_result_includes_costs() -> None:
    position = _open_position(signal(), entry_price=100)

    assert position is not None
    result = _evaluate_position(
        position,
        candle(open_price=100, low=99.5, high=102.1, close=102),
        taker_fee_rate_pct=0.055,
        slippage_bps=2,
    )

    assert result is not None and result != "ambiguous"
    assert result.gross_result_r == 2
    assert result.net_result_r < 2
    assert result.net_result_r > 1.8
