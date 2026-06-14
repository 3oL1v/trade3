from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trade3_api.journal import SignalJournal
from trade3_api.live_models import (
    IntradayCandidate,
    PriceZone,
    TimeframeMetrics,
    TradeTarget,
    TrendPullbackPlan,
)
from trade3_api.market_models import Candle


def candidate(
    *,
    direction: str = "long",
    status: str = "ready",
    confirmation_at: datetime | None = None,
) -> IntradayCandidate:
    confirmation = confirmation_at or datetime(2026, 6, 12, 10, 0, tzinfo=UTC)
    metrics = TimeframeMetrics(
        interval="5",
        close=101,
        ema_20=100,
        ema_50=99,
        ema_20_slope_pct=0.1,
        atr_14=3,
        atr_percent=3,
        volume_ratio=1.2,
        closed_candles=80,
        last_closed_at=confirmation,
    )
    long = direction == "long"
    return IntradayCandidate(
        rank=1,
        symbol="BTCUSDT",
        direction=direction,
        score=82,
        state="candidate",
        last_price=101,
        spread_bps=0.5,
        funding_rate_pct=0.01,
        turnover_24h_usdt=1_000_000_000,
        open_interest_usdt=500_000_000,
        pullback_distance_atr=0.5,
        timeframe_1h=metrics.model_copy(update={"interval": "60"}),
        timeframe_15m=metrics.model_copy(update={"interval": "15"}),
        timeframe_5m=metrics,
        reasons=["test"],
        trade_plan=TrendPullbackPlan(
            status=status,
            pullback_zone=PriceZone(lower=99, upper=100),
            trigger_price=100,
            entry_zone=PriceZone(
                lower=100 if long else 102,
                upper=101 if long else 103,
            ),
            invalidation_price=98 if long else 105,
            structural_target=110 if long else 93,
            risk_per_unit=3,
            structural_reward_risk=3,
            stop_distance_atr=1,
            touched_at=confirmation - timedelta(minutes=5),
            confirmation_at=confirmation,
            targets=[
                TradeTarget(label="TP1", price=104 if long else 99, reward_risk=1),
                TradeTarget(label="TP2", price=107 if long else 96, reward_risk=2),
            ],
            notes=[],
        ),
    )


def candle(
    start_time: datetime,
    *,
    low: float,
    high: float,
    close: float = 101,
) -> Candle:
    return Candle(
        start_time=start_time,
        open=101,
        high=high,
        low=low,
        close=close,
        volume=100,
        turnover_usdt=10_000,
        is_closed=True,
    )


@pytest.mark.asyncio
async def test_journal_deduplicates_confirmation_signal(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    recorded_at = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    assert await journal.record_candidates([candidate()], recorded_at) == 1
    assert await journal.record_candidates([candidate()], recorded_at) == 0

    signals = await journal.list_signals()
    assert len(signals) == 1
    assert signals[0].signal_at == recorded_at
    assert signals[0].lifecycle_state == "pending_entry"


@pytest.mark.asyncio
async def test_journal_releases_sqlite_file_handles(tmp_path) -> None:
    database = Path(tmp_path) / "journal.sqlite3"
    journal = SignalJournal(str(database))
    await journal.initialize()
    await journal.list_signals()

    database.unlink()

    assert not database.exists()


@pytest.mark.asyncio
async def test_journal_tracks_entry_target_then_stop(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    candles = [
        candle(signal_time, low=100, high=102),
        candle(signal_time + timedelta(minutes=5), low=100, high=104.5),
        candle(signal_time + timedelta(minutes=10), low=97.5, high=103),
    ]
    assert await journal.evaluate({"BTCUSDT": candles}, signal_time + timedelta(minutes=15)) == 1

    signal = (await journal.list_signals())[0]
    assert signal.lifecycle_state == "closed"
    assert signal.outcome == "stop_after_target"
    assert signal.entered_at == signal_time
    assert [hit.label for hit in signal.target_hits] == ["TP1"]
    assert signal.mfe_r > 1
    assert signal.mae_r > 1
    assert signal.result_r == 1
    assert signal.entry_fill_price == pytest.approx(101.0202)
    assert signal.exit_fill_price == pytest.approx(103.9792)
    assert signal.fee_cost_r == pytest.approx(0.037583)
    assert signal.slippage_cost_r == pytest.approx(0.013667)
    assert signal.net_result_r == pytest.approx(0.94875)

    stats = await journal.stats()
    assert stats.entered == 1
    assert stats.tp1_hits == 1
    assert stats.stop_after_target == 1
    assert stats.tp1_hit_rate == 1
    assert stats.resolved_trades == 1
    assert stats.net_wins == 1
    assert stats.expectancy_r == pytest.approx(0.9487)
    assert stats.cumulative_net_r == pytest.approx(0.9487)
    assert stats.sample_sufficient is False


@pytest.mark.asyncio
async def test_journal_applies_costs_to_stop_result(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    candles = [
        candle(signal_time, low=100, high=102),
        candle(signal_time + timedelta(minutes=5), low=97.5, high=102),
    ]
    await journal.evaluate({"BTCUSDT": candles}, signal_time + timedelta(minutes=10))

    signal = (await journal.list_signals())[0]
    assert signal.outcome == "stop_before_target"
    assert signal.result_r == -1
    assert signal.net_result_r is not None
    assert signal.net_result_r < -1

    stats = await journal.stats()
    assert stats.resolved_trades == 1
    assert stats.net_losses == 1
    assert stats.net_win_rate == 0
    assert stats.max_drawdown_r == pytest.approx(round(abs(signal.net_result_r), 4))


@pytest.mark.asyncio
async def test_tp1_resolves_baseline_while_observation_remains_active(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    candles = [
        candle(signal_time, low=100, high=102),
        candle(signal_time + timedelta(minutes=5), low=100, high=104.5),
    ]
    await journal.evaluate({"BTCUSDT": candles}, signal_time + timedelta(minutes=10))

    signal = (await journal.list_signals())[0]
    assert signal.lifecycle_state == "active"
    assert signal.outcome is None
    assert signal.net_result_r is not None
    assert signal.net_result_r > 0
    assert (await journal.stats()).resolved_trades == 1


@pytest.mark.asyncio
async def test_active_expiry_uses_latest_closed_price_for_baseline_exit(tmp_path) -> None:
    journal = SignalJournal(
        str(tmp_path / "journal.sqlite3"),
        active_expiry_hours=1,
    )
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    candles = [
        candle(signal_time, low=100, high=102),
        candle(
            signal_time + timedelta(minutes=55),
            low=100,
            high=103,
            close=102,
        ),
    ]
    await journal.evaluate({"BTCUSDT": candles}, signal_time + timedelta(hours=1, minutes=5))

    signal = (await journal.list_signals())[0]
    assert signal.lifecycle_state == "closed"
    assert signal.outcome == "expired_active"
    assert signal.exit_reference_price == 102
    assert signal.result_r == pytest.approx(1 / 3)
    assert signal.net_result_r is not None


@pytest.mark.asyncio
async def test_journal_marks_same_candle_stop_and_target_ambiguous(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    crossing = candle(signal_time, low=97, high=105)
    await journal.evaluate({"BTCUSDT": [crossing]}, signal_time + timedelta(minutes=5))

    signal = (await journal.list_signals())[0]
    assert signal.lifecycle_state == "closed"
    assert signal.outcome == "ambiguous"
    assert signal.result_r is None


@pytest.mark.asyncio
async def test_journal_marks_same_candle_entry_and_target_ambiguous(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    signal_time = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
    await journal.record_candidates([candidate()], signal_time)

    crossing = candle(signal_time, low=100, high=105)
    await journal.evaluate({"BTCUSDT": [crossing]}, signal_time + timedelta(minutes=5))

    signal = (await journal.list_signals())[0]
    assert signal.lifecycle_state == "closed"
    assert signal.outcome == "ambiguous"
    assert signal.entered_at == signal_time


@pytest.mark.asyncio
async def test_missed_plan_is_closed_without_evaluation(tmp_path) -> None:
    journal = SignalJournal(str(tmp_path / "journal.sqlite3"))
    await journal.initialize()
    recorded_at = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    assert await journal.record_candidates([candidate(status="missed")], recorded_at) == 1
    signal = (await journal.list_signals())[0]

    assert signal.lifecycle_state == "closed"
    assert signal.outcome == "missed_at_recording"
    assert signal.entered_at is None
