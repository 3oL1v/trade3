from datetime import UTC, datetime, timedelta

import pytest

from trade3_api.auto_signal_journal import (
    AutoSignalJournal,
    benchmark_return_pct,
    directional_return_pct,
)
from trade3_api.auto_signal_models import AutoSignalRequest


def test_directional_return_inverts_for_shorts() -> None:
    assert directional_return_pct("long", 100, 110) == 0.1
    assert directional_return_pct("short", 100, 90) == 0.1
    assert directional_return_pct("short", 100, 110) == -0.1


def test_neutral_calls_have_no_directional_return() -> None:
    assert directional_return_pct("neutral", 100, 110) is None


def test_benchmark_return_is_always_long() -> None:
    assert benchmark_return_pct(100, 105) == 0.05
    assert benchmark_return_pct(None, 105) is None


async def _journal(tmp_path) -> AutoSignalJournal:
    journal = AutoSignalJournal(str(tmp_path / "auto.sqlite3"))
    await journal.initialize()
    return journal


@pytest.mark.asyncio
async def test_records_and_lists_a_signal(tmp_path) -> None:
    journal = await _journal(tmp_path)
    recorded = await journal.record(
        AutoSignalRequest(
            symbol="BTCUSDT",
            direction="long",
            decision_price=100.0,
            benchmark_symbol="BTCUSDT",
            benchmark_price=100.0,
        ),
        datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
    )
    assert recorded.id >= 1
    assert recorded.outcome_at is None
    signals = await journal.list_signals()
    assert [s.symbol for s in signals] == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_only_matured_signals_are_due(tmp_path) -> None:
    journal = await _journal(tmp_path)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    await journal.record(
        AutoSignalRequest(symbol="BTCUSDT", direction="long", decision_price=100.0),
        now - timedelta(hours=9),
    )
    await journal.record(
        AutoSignalRequest(symbol="ETHUSDT", direction="short", decision_price=100.0),
        now - timedelta(hours=1),
    )
    due = await journal.due_unresolved(horizon_hours=8, now=now)
    assert [s.symbol for s in due] == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_resolve_scores_excess_over_benchmark(tmp_path) -> None:
    journal = await _journal(tmp_path)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    recorded = await journal.record(
        AutoSignalRequest(
            symbol="SOLUSDT",
            direction="long",
            decision_price=100.0,
            benchmark_symbol="BTCUSDT",
            benchmark_price=200.0,
        ),
        now - timedelta(hours=9),
    )
    # SOL +10%, BTC benchmark +4% -> excess +6%.
    resolved = await journal.resolve(recorded.id, 110.0, 208.0, now)
    assert resolved.forward_return_pct == 0.1
    assert resolved.benchmark_return_pct == 0.04
    assert resolved.excess_return_pct == 0.06
    assert resolved.outcome_at is not None


@pytest.mark.asyncio
async def test_stats_count_directional_wins_and_coin_toss(tmp_path) -> None:
    journal = await _journal(tmp_path)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    # Four directional calls, three winners; one neutral that must not be scored.
    winners = [("AAUSDT", 100.0, 110.0), ("BBUSDT", 100.0, 105.0), ("CCUSDT", 100.0, 101.0)]
    for symbol, entry, exit_ in winners:
        rec = await journal.record(
            AutoSignalRequest(symbol=symbol, direction="long", decision_price=entry),
            now - timedelta(hours=9),
        )
        await journal.resolve(rec.id, exit_, None, now)
    loser = await journal.record(
        AutoSignalRequest(symbol="DDUSDT", direction="long", decision_price=100.0),
        now - timedelta(hours=9),
    )
    await journal.resolve(loser.id, 95.0, None, now)
    await journal.record(
        AutoSignalRequest(symbol="EEUSDT", direction="neutral", decision_price=100.0),
        now - timedelta(hours=9),
    )

    stats = await journal.stats(horizon_hours=8, now=now)
    assert stats.total == 5
    assert stats.neutrals == 1
    assert stats.directional == 4
    assert stats.directional_resolved == 4
    assert stats.win_rate == 0.75
    # 3 wins of 4 -> z = (3 - 2) / sqrt(1) = 1.0
    assert stats.coin_toss_z == 1.0
    assert {row.symbol for row in stats.by_symbol} == {"AAUSDT", "BBUSDT", "CCUSDT", "DDUSDT"}
